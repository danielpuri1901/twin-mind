"""Every writer that puts a vector in the index must embed the same text.

They drifted once and nothing noticed. On 2026-09-29 the full build truncated
records at 1,500 characters while all four incremental writers used 2,048, so
1,749 records had a vector that depended on whether the timer or a rebuild
created it. Same record, same model, different numbers.

That class of bug is invisible from the data: the `model` column matches, the
counts match, the parity check passes. The only place it is visible is the
source, so the check belongs here.

These tests read the actual files rather than importing them, because the
plugin lives outside the package and imports differently depending on who runs
it. A grep cannot be fooled by an import path.
"""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Everything that calls Bedrock to create a stored vector.
WRITERS = [
    "pipeline/embed_corpus.py",
    "pipeline/ingest_twin_chat.py",
    "pipeline/ingest_wispr_meetings.py",
    "pipeline/backfill/rebuild_twin_chat.py",
    "pipeline/backfill/granola_backfill.py",
    "infra/hermes-plugins/twin-episodic/__init__.py",
    # The benchmark harness builds indexes too. It was left off this list at
    # first and promptly drifted, which is the exact failure the list exists
    # to prevent: a measurement built differently from the thing measured.
    "evals/longmemeval_retrieval.py",
]

CONTRACT = os.path.join(ROOT, "shared", "embedding.py")


def read(rel):
    """Empty string for a writer that is not present here.

    The repo holds one-off backfill scripts that are never deployed to the
    box, so running this there must not crash. `test_enough_writers_checked`
    stops that tolerance turning into a test that passes by finding nothing.
    """
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def present():
    return [r for r in WRITERS if os.path.exists(os.path.join(ROOT, r))]


def test_enough_writers_checked():
    """Guard the guard: tolerating missing files must not mean checking none."""
    found = present()
    assert len(found) >= 3, f"only found {len(found)} writers to check: {found}"
    assert any("embed_corpus" in f for f in found), "the full build must be checked"


def contract_value(name):
    m = re.search(rf"^{name}\s*=\s*(\S+)", read("shared/embedding.py"), re.M)
    assert m, f"{name} missing from shared/embedding.py"
    return m.group(1).strip().strip('"')


# Only the slice INSIDE the request body counts. A file may truncate text for
# a log line or a dry-run preview, and that is not an embedding decision; the
# first version of this test flagged a [:60] used to print a preview.
# `.*?` rather than `[^\]]*?`: the body contains r["text"], so a character
# class excluding ] stops before ever reaching the slice.
EMBED_SLICE = re.compile(r'"texts"\s*:\s*\[.*?\[:(\d+)\]')


def test_no_writer_hardcodes_a_truncation():
    """A bare number in the request body is how the drift happened."""
    offenders = []
    for rel in present():
        for n in EMBED_SLICE.findall(read(rel)):
            offenders.append(f"{rel} truncates the embedded text at a literal {n}")
    assert not offenders, "hardcoded truncation:\n  " + "\n  ".join(offenders)


def test_the_slice_detector_actually_detects():
    """Guard the guard: a regex that matches nothing passes every test."""
    assert EMBED_SLICE.findall('"texts": [r["text"][:2048] for r in recs]') == ["2048"]
    assert EMBED_SLICE.findall('"texts": [t[:1500] for t in texts]') == ["1500"]
    assert EMBED_SLICE.findall('print(r["text"][:60])') == []


def test_every_writer_agrees_on_the_cap():
    want = contract_value("MAX_CHARS")
    wrong = []
    for rel in present():
        body = read(rel)
        m = re.search(r"^MAX_EMBED_CHARS\s*=\s*(\d+)", body, re.M)
        if m:
            if m.group(1) != want:
                wrong.append(f"{rel}: MAX_EMBED_CHARS={m.group(1)}, contract={want}")
        elif not re.search(r"from shared\.embedding import [^\n]*MAX_CHARS", body):
            # Either declare MAX_EMBED_CHARS matching the contract, or import
            # MAX_CHARS from it under any alias. Anything else is drift.
            wrong.append(f"{rel}: declares no cap and does not import the contract")
    assert not wrong, "truncation drift:\n  " + "\n  ".join(wrong)


def test_every_writer_uses_the_same_model():
    want = contract_value("MODEL")
    wrong = []
    for rel in present():
        for found in set(re.findall(r'"(cohere\.[a-z0-9.\-]+)"', read(rel))):
            if found != want:
                wrong.append(f"{rel} embeds with {found}, contract says {want}")
    assert not wrong, "model drift:\n  " + "\n  ".join(wrong)


def test_documents_and_queries_are_embedded_differently():
    """Cohere v3 is asymmetric. Getting this backwards never errors, it only
    ranks worse, so nothing but a test will catch it."""
    for rel in present():
        body = read(rel)
        if "input_type" in body:
            assert "search_document" in body, f"{rel} writes vectors but not as search_document"
            assert "search_query" not in body, f"{rel} writes vectors using search_query"
    search = read("shared/corpus_search.py")
    assert "search_query" in search, "corpus_search must embed the QUERY as search_query"


def test_the_floor_matches_the_parity_check():
    """corpus_staleness compares FTS records above the floor against vector
    rows. A writer using a different floor makes that comparison meaningless."""
    want = contract_value("MIN_CHARS")
    staleness = read("shared/corpus_staleness.py")
    m = re.search(r"^MIN_EMBED_CHARS\s*=\s*(\d+)", staleness, re.M)
    assert m, "corpus_staleness.py has no MIN_EMBED_CHARS"
    assert m.group(1) == want, (
        f"parity check uses {m.group(1)}, embedding contract uses {want}; "
        "the parity check would report a gap that is not real")


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
            passed += 1
    print(f"\n{passed} passed")
