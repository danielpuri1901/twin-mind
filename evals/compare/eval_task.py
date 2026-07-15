#!/usr/bin/env python3
"""The ONE eval every platform runs, so the four-way comparison is apples-to-apples.

Task: the inbox-decision policy (does Daniel need to act on this message?) - our real
regression eval. Dataset: inbox-decision-answers. Scorer: deterministic verdict match
against the gold answer. Platform adapters (langfuse/langsmith/braintrust/arize) wrap
THIS module; none of the eval logic lives in an adapter.
"""
import json, os, sys

EVALS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # compare/ -> evals/
sys.path.insert(0, EVALS)
from run_regression import INBOX_DECISION_RULES, claude, code_grader  # reuse production logic

DATA = os.path.expanduser("~/twin-corpus/datasets")


def dataset():
    """List of {id, input:{scenario, available_sources}, expected_output, gold_behavior}."""
    return [json.loads(l) for l in open(os.path.join(DATA, "inbox-decision-answers.jsonl"))]


def run_task(inp):
    """inp = the item's `input` dict. Returns the model's decision text."""
    user = (f"SCENARIO:\n{inp['scenario']}\n\nAVAILABLE SOURCES:\n"
            + "\n".join(f"- {s}" for s in inp["available_sources"]))
    decision, _, _ = claude(INBOX_DECISION_RULES, user)
    return decision


def score(decision, expected_output):
    """Deterministic: 1.0 if the ACTIONABLE verdict matches gold, else 0.0."""
    ok, _ = code_grader(decision, expected_output)
    return 1.0 if ok else 0.0
