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
DATASETS = ["brief-inbox-decisions", "brief-section-verdicts", "prep-dossier-verdicts",
            "corpus-qa", "brief-archive"] + list(E.SECTION_DATASETS)  # + 5 per-section slices


def expected_of(r):
    return r.get("expected_output") or r.get("verdict") or r.get("answer") or r.get("body")


def get_or_create(name):
    if c.has_dataset(dataset_name=name):
        return c.read_dataset(dataset_name=name)
    return c.create_dataset(dataset_name=name)


def push_datasets():
    for name in DATASETS:
        rows = E.dataset_rows(name)
        if not rows:
            print("skip", name); continue
        ds = get_or_create(name)
        inputs = [r["input"] if name == "brief-inbox-decisions" else r for r in rows]
        outputs = [{"expected": expected_of(r)} for r in rows]
        c.create_examples(inputs=inputs, outputs=outputs, dataset_id=ds.id)
        print(f"langsmith dataset {name}: {len(rows)} items")


def target(inputs):
    return {"output": E.run_task(inputs)}


def verdict_match(run, example):
    return {"key": "verdict_match",
            "score": E.score(run.outputs["output"], example.outputs.get("expected"))}


def run_experiment():
    evaluate(target, data="brief-inbox-decisions", evaluators=[verdict_match],
             experiment_prefix="inbox-decisions", client=c)


# --- the LLM-as-judge evaluator (the thing to clone + tweak in the LangSmith UI) ---
def push_brief_sections(limit):
    ds = get_or_create("brief-sections")
    rows = E.brief_sections(limit)
    c.create_examples(
        inputs=[{"section": r["section"], "brief_text": r["brief_text"], "subject": r["subject"]} for r in rows],
        outputs=[{"label": r["label"]} for r in rows], dataset_id=ds.id)
    print(f"langsmith brief-sections: {len(rows)} items")


def brief_target(inputs):
    return {"section": inputs["section"]}  # passthrough; the LLM judging happens in the evaluator


def llm_judge(run, example):
    verdict, reasoning = E.judge_section(example.inputs["brief_text"], example.inputs["section"])
    return {"key": "judge_agrees_daniel",
            "score": E.judge_agrees(verdict, example.outputs["label"]),
            "comment": f"judge={verdict} | daniel={example.outputs['label']} | {reasoning}"}


def run_brief_experiment(limit=24):
    push_brief_sections(limit)
    evaluate(brief_target, data="brief-sections", evaluators=[llm_judge],
             experiment_prefix="brief-judge", client=c)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", action="store_true", help="run the LLM-judge brief experiment")
    ap.add_argument("--limit", type=int, default=24)
    a = ap.parse_args()
    if a.brief:
        run_brief_experiment(a.limit)
    else:
        push_datasets()
        run_experiment()
    print("langsmith done - project twin-mind")
