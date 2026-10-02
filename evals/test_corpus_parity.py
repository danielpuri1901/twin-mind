"""The parity check must catch the failure that already happened, and stay quiet otherwise.

On 2026-09 twin-chat was indexed in FTS5 with 187 records and 0 vectors. Every
keyword search found it, every paraphrase missed it, and nothing reported a
problem. These tests pin both halves of the fix: the short-ack exclusion that
makes the counts legitimately comparable, and the detection of a real gap.
"""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
import corpus_staleness as cs  # noqa: E402


def build(rows, vectors):
    """A throwaway corpus pair. rows: [(source, text)], vectors: [source]."""
    d = tempfile.mkdtemp()
    fts_path, vec_path = os.path.join(d, "corpus.db"), os.path.join(d, "vectors.db")
    fts = sqlite3.connect(fts_path)
    fts.execute("CREATE VIRTUAL TABLE msgs USING fts5(source, chat, date, who, sender, text)")
    fts.executemany("INSERT INTO msgs VALUES (?,'','','','',?)", rows)
    fts.commit()
    fts.close()
    vec = sqlite3.connect(vec_path)
    vec.execute("CREATE TABLE vec_meta(rowid INTEGER PRIMARY KEY, source TEXT, chat TEXT, "
                "date TEXT, who TEXT, sender TEXT, text TEXT)")
    vec.executemany("INSERT INTO vec_meta VALUES (?,?,'','','','','')",
                    [(i, s) for i, s in enumerate(vectors, 1)])
    vec.commit()
    vec.close()
    return fts_path, vec_path


def test_healthy_corpus_is_silent():
    fts, vec = build(
        [("meeting", "long enough to embed here"),
         ("meeting", "also long enough to embed")],
        ["meeting", "meeting"])
    assert cs.vector_parity(fts, vec) == []


def test_short_acks_are_not_a_mismatch():
    """The whole point of the 12 character floor: "ok" belongs in FTS and not
    in the vector index, so it must never look like a missing vector."""
    fts, vec = build(
        [("twin-chat", "ok"),
         ("twin-chat", "yes"),
         ("twin-chat", "a proper sentence worth embedding")],
        ["twin-chat"])
    assert cs.vector_parity(fts, vec) == []


def test_missing_vector_is_caught():
    fts, vec = build(
        [("meeting", "long enough to embed here"),
         ("meeting", "also long enough to embed")],
        ["meeting"])
    assert cs.vector_parity(fts, vec) == [("meeting", 2, 1, -1)]


def test_the_twin_chat_failure_shape():
    """187 records, 0 vectors: indexed for keywords, invisible to a paraphrase."""
    rows = [("twin-chat", f"a real message number {i} with enough text") for i in range(187)]
    fts, vec = build(rows, [])
    assert cs.vector_parity(fts, vec) == [("twin-chat", 187, 0, -187)]


def test_orphan_vectors_are_caught_too():
    """A positive delta means vectors survived a purge that removed the records,
    which is how a stale hit can be returned for a message that no longer exists."""
    fts, vec = build([("gmail", "a message long enough to embed")],
                     ["gmail", "gmail", "gmail"])
    assert cs.vector_parity(fts, vec) == [("gmail", 1, 3, 2)]


def test_alert_names_the_source_and_the_gap():
    text = cs.format_parity_alert([("twin-chat", 187, 0, -187)])
    assert "twin-chat" in text and "187" in text
    assert "paraphrase" in text


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
            passed += 1
    print(f"\n{passed} passed")
