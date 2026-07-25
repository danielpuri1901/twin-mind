#!/usr/bin/env python3
"""Braintrust adapter (EU region): push the 5 datasets + run the inbox-decision experiment."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for l in open(os.path.expanduser("~/.hermes/.env")):
    if "=" in l and not l.strip().startswith("#"):
        k, v = l.strip().split("=", 1); os.environ.setdefault(k, v)
os.environ.setdefault("BRAINTRUST_APP_URL", "https://www.braintrust.dev")

import eval_task as E
import braintrust

D = os.path.expanduser("~/twin-corpus/datasets")
PROJECT = "twin-mind"
DATASETS = ["brief-inbox-decisions", "brief-section-verdicts", "prep-dossier-verdicts",
            "corpus-qa", "brief-archive"] + list(E.SECTION_DATASETS)  # + 5 per-section slices


def expected_of(r):
    return r.get("expected_output") or r.get("verdict") or r.get("answer") or r.get("body")


def push_datasets():
    for name in DATASETS:
        rows = E.dataset_rows(name)
        if not rows:
            print("skip", name); continue
        ds = braintrust.init_dataset(project=PROJECT, name=name)
        n = 0
        for r in rows:
            ds.insert(input=r, expected=expected_of(r), metadata={})
            n += 1
        print(f"braintrust dataset {name}: {n} items")
    braintrust.flush()


def verdict_match(input, output, expected, **kw):
    return E.score(output, expected)


def run_experiment():
    data = [{"input": it["input"], "expected": it["expected_output"], "metadata": {"id": it["id"]}}
            for it in E.dataset()]
    braintrust.Eval(PROJECT, data=data, task=lambda inp: E.run_task(inp),
                    scores=[verdict_match], experiment_name="inbox-decisions")


# --- LLM-as-judge scorer (the thing to clone + tweak in the Braintrust UI) ---
def judge_agrees_daniel(input, output, expected, **kw):
    verdict, reasoning = E.judge_section(input["brief_text"], input["section"])
    return {"name": "judge_agrees_daniel", "score": E.judge_agrees(verdict, expected),
            "metadata": {"judge": verdict, "daniel": expected, "reasoning": reasoning}}


def run_brief_experiment(limit=24):
    data = [{"input": {"section": r["section"], "brief_text": r["brief_text"]},
             "expected": r["label"], "metadata": {"id": r["id"]}} for r in E.brief_sections(limit)]
    braintrust.Eval(PROJECT, data=data, task=lambda inp: inp["section"],
                    scores=[judge_agrees_daniel], experiment_name="brief-judge")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--limit", type=int, default=24)
    a = ap.parse_args()
    if a.brief:
        run_brief_experiment(a.limit)
    else:
        push_datasets()
        run_experiment()
    print("braintrust done ->", os.environ.get("BRAINTRUST_APP_URL"))
