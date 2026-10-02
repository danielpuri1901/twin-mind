"""The corpus-rag counter must record every turn, and must never break one.

Whether the plugin fires at all has been unanswerable since 2026-09-24,
because it logged at INFO and the gateway journals WARNING and above. These
tests pin the replacement: a file the plugin writes itself, one line per turn,
with no message text in it.

The last test is the important one. An instrument that can break the thing it
measures is worse than no instrument, so a counter file that cannot be written
must still leave the turn working.
"""

import importlib
import json
import os
import sys
import tempfile

PLUGIN = os.path.join(os.path.dirname(__file__), "..", "infra", "hermes-plugins", "corpus-rag")


def load(stats_path, search_path=""):
    """Import the plugin fresh with the env it reads at module level."""
    os.environ["CORPUS_RAG_STATS"] = stats_path
    os.environ["CORPUS_SEARCH_PATH"] = search_path or "/nonexistent/corpus_search.py"
    sys.path.insert(0, PLUGIN)
    for name in list(sys.modules):
        if name == "__init__":
            del sys.modules[name]
    mod = importlib.import_module("__init__")
    return importlib.reload(mod)


def rows(path):
    if not os.path.exists(path):
        return []
    return [json.loads(line) for line in open(path) if line.strip()]


def test_trivial_turn_is_recorded_as_skipped():
    path = os.path.join(tempfile.mkdtemp(), "rag-stats.jsonl")
    mod = load(path)
    assert mod.on_pre_llm_call(user_message="ok") is None
    r = rows(path)
    assert len(r) == 1
    assert r[0]["outcome"] == "skipped"
    assert r[0]["reason"] == "trivial turn"


def test_no_hits_is_recorded_as_empty_not_silence():
    """A real question that finds nothing is a different event from a greeting,
    and the difference is the whole point: one means the corpus was consulted."""
    path = os.path.join(tempfile.mkdtemp(), "rag-stats.jsonl")
    mod = load(path)
    assert mod.on_pre_llm_call(user_message="what did we decide about the s3 migration") is None
    r = rows(path)
    assert len(r) == 1
    assert r[0]["outcome"] == "empty"
    assert r[0]["chars"] > 12


def test_no_message_text_is_ever_written():
    path = os.path.join(tempfile.mkdtemp(), "rag-stats.jsonl")
    mod = load(path)
    secret = "my bank password is hunter2 and my address is somewhere real"
    mod.on_pre_llm_call(user_message=secret)
    body = open(path).read()
    for word in ("password", "hunter2", "address", "bank"):
        assert word not in body, f"{word!r} leaked into the stats file"
    assert str(len(secret)) in body  # the length is fine, the content is not


def test_an_unwritable_stats_file_does_not_break_the_turn():
    mod = load("/proc/cannot/write/here/rag-stats.jsonl")
    assert mod.on_pre_llm_call(user_message="ok") is None
    assert mod.on_pre_llm_call(user_message="a real question about the corpus") is None


def test_registering_leaves_a_mark():
    """So 'did the plugin even load' is answerable from the file alone."""
    path = os.path.join(tempfile.mkdtemp(), "rag-stats.jsonl")
    mod = load(path)

    class Ctx:
        def register_hook(self, *_a, **_k):
            pass

    mod.register(Ctx())
    r = rows(path)
    assert r and r[-1]["outcome"] == "registered"
    assert r[-1]["k"] >= 1


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
            passed += 1
    print(f"\n{passed} passed")
