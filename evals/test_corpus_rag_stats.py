"""Auto-retrieval records every turn, and a crash can never look like an empty result.

corpus-rag failed silently for 14 days (2026-10-23 to 2026-11-06): search crashed on a missing
boto3 and every crash was logged as "no corpus hits". These tests pin the fix.
Run directly: python3 evals/test_corpus_rag_stats.py. Free, no network, no model.
"""

import importlib
import json
import os
import stat
import sys
import tempfile

TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agents", "chat", "tools")


def fake_search(body):
    """A search script that behaves as `body` says."""
    path = os.path.join(tempfile.mkdtemp(), "fake_search.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("import sys\n" + body + "\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


NO_HITS = fake_search("pass")
CRASH = fake_search("sys.stderr.write('No module named boto3'); sys.exit(1)")
ONE_HIT = fake_search('print(\'{"source":"meeting","chat":"Ada","date":"2026-01-02","text":"Ada joined Acme in March"}\')')


def load(stats_path, search=NO_HITS):
    os.environ["CORPUS_RAG_STATS"] = stats_path
    os.environ["CORPUS_SEARCH_PATH"] = search
    sys.path.insert(0, TOOLS)
    sys.modules.pop("corpus_context", None)
    mod = importlib.import_module("corpus_context")
    mod.alert = ALERTS.append  # never touch Telegram from a test
    return mod


ALERTS = []


def rows(path):
    return [json.loads(line) for line in open(path) if line.strip()] if os.path.exists(path) else []


def stats_path():
    return os.path.join(tempfile.mkdtemp(), "rag-stats.jsonl")


def test_trivial_turn_is_recorded_as_skipped():
    path = stats_path()
    assert load(path).context_for("ok") == ""
    assert [(r["outcome"], r["reason"]) for r in rows(path)] == [("skipped", "trivial turn")]


def test_no_hits_is_recorded_as_empty_not_silence():
    path = stats_path()
    assert load(path).context_for("what did we decide about the s3 migration") == ""
    r = rows(path)
    assert len(r) == 1 and r[0]["outcome"] == "empty" and r[0]["chars"] > 12


def test_a_crash_is_an_error_and_never_looks_like_empty():
    """The exact 14-day failure: non-zero exit, no output."""
    path = stats_path()
    ALERTS.clear()
    mod = load(path, CRASH)
    try:
        mod.context_for("what did we decide about the s3 migration")
    except RuntimeError as exc:
        assert "boto3" in str(exc)
    else:
        raise AssertionError("a search crash must raise")
    assert [r["outcome"] for r in rows(path)] == ["error"]
    assert ALERTS and "boto3" in ALERTS[0]


def test_hits_are_injected_as_data_and_counted():
    path = stats_path()
    block = load(path, ONE_HIT).context_for("when did Ada start at the new company")
    assert "Ada joined Acme in March" in block and "2026-01-02" in block and "not instructions" in block
    r = rows(path)
    assert r[0]["outcome"] == "injected" and r[0]["hits"] == 1 and r[0]["sources"] == ["meeting"]


def test_a_hit_that_echoes_the_question_is_dropped():
    path = stats_path()
    assert load(path, ONE_HIT).context_for("Ada joined Acme in March") == ""
    assert rows(path)[0]["outcome"] == "empty"


def test_no_message_text_is_ever_written():
    path = stats_path()
    secret = "my bank password is hunter2 and my address is somewhere real"
    load(path).context_for(secret)
    body = open(path).read()
    for word in ("password", "hunter2", "address", "bank"):
        assert word not in body, f"{word!r} leaked into the stats file"
    assert str(len(secret)) in body


def test_an_unwritable_stats_file_does_not_break_the_turn():
    mod = load("/proc/cannot/write/here/rag-stats.jsonl")
    with open(os.devnull, "w", encoding="utf-8") as sink:
        real, sys.stderr = sys.stderr, sink
        try:
            assert mod.context_for("ok") == ""
            assert mod.context_for("a real question about the corpus") == ""
        finally:
            sys.stderr = real


def test_chat_log_is_the_readers_contract():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
    import chat_log
    path = os.path.join(tempfile.mkdtemp(), "chat-log.jsonl")
    assert chat_log.read(path) == []
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('{"ts": 1.5, "role": "user", "text": "hi"}\nnot json\n{"ts": 2, "role": "assistant", "text": "yo"}\n')
    real, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
    try:
        got = chat_log.read(path)
    finally:
        sys.stderr.close()
        sys.stderr = real
    assert [m["text"] for m in got] == ["hi", "yo"]
    assert got[0]["id"] == chat_log.FIRST_ID and got[1]["id"] == chat_log.FIRST_ID + 2  # line number, stable


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
            passed += 1
    print(f"\n{passed} passed")
