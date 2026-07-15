#!/usr/bin/env python3
"""LangSmith adapter: push the 5 datasets + run the inbox-decision experiment.
Project: twin-mind. Reads LANGSMITH_API_KEY (+ optional LANGSMITH_ENDPOINT for EU)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for l in open(os.path.expanduser("~/.hermes/.env")):
    if "=" in l and not l.strip().startswith("#"):
        k, v = l.strip().split("=", 1); os.environ.setdefault(k, v)
os.environ.setdefault("LANGSMITH_PROJECT", "twin-mind")

import eval_task as E
from langsmith import Client, evaluate

c = Client()  # LANGSMITH_API_KEY (+ LANGSMITH_ENDPOINT if the account is EU)
D = os.path.expanduser("~/twin-corpus/datasets")
DATASETS = ["inbox-decision-answers", "brief-verdicts", "prep-verdicts", "qa-answers", "briefs-sent"]


def expected_of(r):
    return r.get("expected_output") or r.get("verdict") or r.get("answer") or r.get("body")


def get_or_create(name):
    if c.has_dataset(dataset_name=name):
        return c.read_dataset(dataset_name=name)
    return c.create_dataset(dataset_name=name)


def push_datasets():
    for name in DATASETS:
        p = os.path.join(D, name + ".jsonl")
        if not os.path.exists(p):
            print("skip", name); continue
        ds = get_or_create(name)
        rows = [json.loads(l) for l in open(p)]
        inputs = [r["input"] if name == "inbox-decision-answers" else r for r in rows]
        outputs = [{"expected": expected_of(r)} for r in rows]
        c.create_examples(inputs=inputs, outputs=outputs, dataset_id=ds.id)
        print(f"langsmith dataset {name}: {len(rows)} items")


def target(inputs):
    return {"output": E.run_task(inputs)}


def verdict_match(run, example):
    return {"key": "verdict_match",
            "score": E.score(run.outputs["output"], example.outputs.get("expected"))}


def run_experiment():
    evaluate(target, data="inbox-decision-answers", evaluators=[verdict_match],
             experiment_prefix="inbox-decisions", client=c)


if __name__ == "__main__":
    push_datasets()
    run_experiment()
    print("langsmith done - project twin-mind")
