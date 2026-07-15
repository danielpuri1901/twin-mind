#!/usr/bin/env python3
"""Langfuse adapter: push brief-sections + run the LLM judge as a scored dataset run.
(Langfuse also has a UI-native LLM-as-judge evaluator - this gives you the same data
programmatically; the UI evaluator is the other way to play with it.)"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for l in open(os.path.expanduser("~/.hermes/.env")):
    if "=" in l and not l.strip().startswith("#"):
        k, v = l.strip().split("=", 1); os.environ.setdefault(k, v)
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", os.environ.get("HERMES_LANGFUSE_PUBLIC_KEY", ""))
os.environ.setdefault("LANGFUSE_SECRET_KEY", os.environ.get("HERMES_LANGFUSE_SECRET_KEY", ""))
os.environ.setdefault("LANGFUSE_HOST", os.environ.get("HERMES_LANGFUSE_BASE_URL", "https://cloud.langfuse.com"))

import eval_task as E
from langfuse import Langfuse
lf = Langfuse()


def push_brief_sections(limit):
    lf.create_dataset(name="brief-sections")
    for r in E.brief_sections(limit):
        lf.create_dataset_item(dataset_name="brief-sections", id=f"brief-sections:{r['id']}",
                               input={"section": r["section"], "brief_text": r["brief_text"]},
                               expected_output=r["label"])
    lf.flush()


def run_brief_experiment(limit=24):
    push_brief_sections(limit)
    dataset = lf.get_dataset("brief-sections")
    n = 0
    for item in dataset.items:
        verdict, reasoning = E.judge_section(item.input["brief_text"], item.input["section"])
        agree = E.judge_agrees(verdict, item.expected_output)
        with item.run(run_name="brief-judge") as root:
            root.update_trace(input=item.input, output={"verdict": verdict, "reasoning": reasoning})
            root.score_trace(name="judge_agrees_daniel", value=agree,
                             comment=f"judge={verdict} daniel={item.expected_output}")
        n += 1
    lf.flush()
    print(f"langfuse brief-judge run: {n} items scored")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--limit", type=int, default=24)
    a = ap.parse_args()
    run_brief_experiment(a.limit)
    print("langfuse done")
