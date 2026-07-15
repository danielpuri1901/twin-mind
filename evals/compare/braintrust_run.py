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
DATASETS = ["inbox-decision-answers", "brief-verdicts", "prep-verdicts", "qa-answers", "briefs-sent"]


def expected_of(r):
    return r.get("expected_output") or r.get("verdict") or r.get("answer") or r.get("body")


def push_datasets():
    for name in DATASETS:
        p = os.path.join(D, name + ".jsonl")
        if not os.path.exists(p):
            print("skip", name); continue
        ds = braintrust.init_dataset(project=PROJECT, name=name)
        n = 0
        for line in open(p):
            r = json.loads(line)
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


if __name__ == "__main__":
    push_datasets()
    run_experiment()
    print("braintrust done ->", os.environ.get("BRAINTRUST_APP_URL"))
