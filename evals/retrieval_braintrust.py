#!/usr/bin/env python3
"""Push the retrieval eval to Braintrust as two experiments (per-turn vs windowed).

The eval LOGIC is reused verbatim from retrieval_eval.py - the retriever and the metric functions.
This file only does the Braintrust wiring, so you can read, in one place, exactly what the platform
needs from you:

    dataset  (questions + gold answer + home source)   <- lives in Braintrust too
    task     (retrieve top-k for a question)            <- YOUR code, runs on the box
    scorers  (source_recall / entity_cover / llm_recall) <- YOUR code; only the last uses an LLM

Braintrust runs the task over the dataset, applies the scorers, and stores the result as an
"experiment" you explore + diff in the UI. It does NOT run the retriever - your code does.

Deterministic scorers (source_recall, entity_cover) are plain Python - no LLM. Only llm_recall
calls a judge, because "does this context support the answer" has no code formula. This is the
point: the platform takes code scorers as first-class; you don't push everything through an LLM.

Run on the box (Bedrock instance role + local indexes):  python evals/retrieval_braintrust.py
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import retrieval_eval as RE   # retrieve, connect, embed_query, entity_coverage, llm_supported, KS, ROOT, QA

import braintrust

# Braintrust key lives in ~/.hermes/.env (same place braintrust_run.py reads it)
for line in open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)

PROJECT = "twin-mind"
INDEX = os.path.join(RE.ROOT, "index")

# The ablation ladder. Each config = ONE cleanly-named Braintrust experiment (the name IS the
# experiment name), so the compare view reads top-to-bottom as the ladder. Add a knob -> add a
# line here, build its index, run it. You never cram the whole ladder into one experiment: an
# experiment runs one config; the LADDER is the set of experiments you diff against each other.
CONFIGS = {
    "windowed-1-baseline":    {"db": os.path.join(INDEX, "vectors-windowed.db")},      # best chunking
    "windowed-2-contextual":  {"db": os.path.join(INDEX, "vectors-windowed-ctx.db")},  # + metadata in embedding
    "windowed-4-rerank":      {"db": os.path.join(INDEX, "vectors-windowed-ctx.db"),   # + Cohere Rerank 3.5
                               "rerank": True, "topn": 50},
    "perturn-chunking-proof": {"db": os.path.join(INDEX, "vectors-perturn.db")},       # the chunking A/B (done)
    # "windowed-3-hybrid":    {...},                                                   # step 3: re-verify search
}


def make_task(cfg):
    """task(question) -> retrieved chunks. Braintrust runs tasks in a THREAD POOL, and a SQLite
    connection can't cross threads - so open a fresh read-only connection inside the task. If the
    config sets rerank, pull a wider top-N by vector then Cohere-rerank down to the top."""
    db_path, do_rerank, topn = cfg["db"], cfg.get("rerank", False), cfg.get("topn", 50)

    def task(question):
        db = RE.connect(db_path)
        try:
            k = topn if do_rerank else max(RE.KS)
            chunks = RE.retrieve(db, RE.embed_query(question), k)
            return RE.rerank(question, chunks, top_k=20) if do_rerank else chunks
        finally:
            db.close()

    return task


# ---- scorers: each returns a float in [0,1], or None to mean "not scored for this row" ----

def source_recall_at(k):
    """DETERMINISTIC - did top-k include a chunk from the answer's known home meeting?"""
    def f(output, metadata=None, **kw):
        home = (metadata or {}).get("home")
        if not home:
            return None   # rows without a home (the original 24) don't get a source score
        return 1.0 if any(c.get("chat") == home.get("chat") for c in (output or [])[:k]) else 0.0
    f.__name__ = f"source_recall@{k}"
    return f


def entity_cover_at(k):
    """DETERMINISTIC - fraction of the gold answer's key tokens present in the top-k text."""
    def f(output, expected, **kw):
        return RE.entity_coverage(expected, (output or [])[:k])   # 0..1 or None
    f.__name__ = f"entity_cover@{k}"
    return f


def llm_recall_at(k):
    """LLM JUDGE - does the top-k context semantically support the gold answer? (the one non-code scorer)"""
    def f(input, output, expected, **kw):
        return 1.0 if RE.llm_supported(input, expected, (output or [])[:k]) else 0.0
    f.__name__ = f"llm_recall@{k}"
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("configs", nargs="*",
                    help="config name(s) from CONFIGS; each becomes one experiment. "
                         "Default: windowed-1-baseline")
    a = ap.parse_args()
    names = a.configs or ["windowed-1-baseline"]

    rows = [json.loads(l) for l in open(RE.QA, encoding="utf-8")]
    data = [{"input": r["question"], "expected": r["answer"],
             "metadata": {"id": r["id"], "home": r.get("home"), "citation": r.get("citation")}}
            for r in rows]
    print(f"corpus-qa: {len(data)} questions | running: {names}")

    for name in names:
        cfg = CONFIGS.get(name)
        if not cfg or not os.path.exists(cfg["db"]):
            print(f"SKIP {name}: unknown config or missing index")
            continue
        print(f"running experiment {name} ...")
        braintrust.Eval(
            PROJECT,
            data=data,
            task=make_task(cfg),
            scores=[source_recall_at(3), source_recall_at(5), source_recall_at(10)],  # tight-k: does rerank help at the top?
            experiment_name=name,
        )
        print(f"  done -> Braintrust '{PROJECT}' / experiment '{name}'")


if __name__ == "__main__":
    main()
