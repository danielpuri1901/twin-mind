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
try:
    from langfuse import Evaluation
except ImportError:
    from langfuse._client.datasets import Evaluation
lf = Langfuse()


def push_brief_sections(limit):
    lf.create_dataset(name="brief-sections")
    for r in E.brief_sections(limit):
        lf.create_dataset_item(dataset_name="brief-sections", id=f"brief-sections:{r['id']}",
                               input={"section": r["section"], "brief_text": r["brief_text"]},
                               expected_output=r["label"])
    lf.flush()


def _task(*, item, **kwargs):
    return item.input["section"]  # passthrough; the LLM judging is in the evaluator


def _judge_evaluator(*, input, output, expected_output, metadata=None, **kwargs):
    verdict, reasoning = E.judge_section(input["brief_text"], input["section"])
    return Evaluation(name="judge_agrees_daniel", value=E.judge_agrees(verdict, expected_output),
                      comment=f"judge={verdict} daniel={expected_output} | {reasoning}")


def run_brief_experiment(limit=24):
    push_brief_sections(limit)
    ds = lf.get_dataset("brief-sections")
    result = lf.run_experiment(name="brief-judge", run_name="brief-judge",
                               data=ds.items, task=_task, evaluators=[_judge_evaluator])
    lf.flush()
    print("langfuse brief-judge run:", getattr(result, "run_name", "done"))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--limit", type=int, default=24)
    a = ap.parse_args()
    run_brief_experiment(a.limit)
    print("langfuse done")
