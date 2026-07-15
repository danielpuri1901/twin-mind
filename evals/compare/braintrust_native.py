#!/usr/bin/env python3
"""Braintrust-NATIVE LLM-as-judge scorer, using Braintrust's own autoevals.LLMClassifier
(not a hand-rolled Python function). Run it with the Braintrust CLI:
    braintrust eval evals/compare/braintrust_native.py
and push it to your Braintrust Library (reusable scorer in the UI) with:
    braintrust push evals/compare/braintrust_native.py

Model: routes through the Braintrust AI proxy. To use Bedrock, add AWS Bedrock as a
provider in Braintrust (Settings -> AI providers -> AWS Bedrock), then set
BT_JUDGE_MODEL to a Bedrock model name. Default is a standard Claude the proxy knows."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for l in open(os.path.expanduser("~/.hermes/.env")):
    if "=" in l and not l.strip().startswith("#"):
        k, v = l.strip().split("=", 1); os.environ.setdefault(k, v)
os.environ.setdefault("BRAINTRUST_APP_URL", "https://www.braintrust.dev")

import eval_task as E
from braintrust import Eval
from autoevals import LLMClassifier

MODEL = os.environ.get("BT_JUDGE_MODEL", "claude-3-5-sonnet-latest")

# The LLM-as-judge scorer, defined in Braintrust's own primitive. This is the object
# that shows up (and is editable) as a scorer in the Braintrust UI.
brief_section_judge = LLMClassifier(
    name="BriefSectionQuality",
    prompt_template=(
        "You are a strict, fair judge of ONE section of Daniel's morning-brief email.\n"
        "SECTION: {{input.section}}\n\nBRIEF:\n{{input.brief_text}}\n\n"
        "Judge only the {{input.section}} section.\n"
        "good = clear, grounded in real facts, no platitudes, no repetition of prior briefs.\n"
        "bad = vague, stale, generic, or contradictory.\n"
        "Answer 'good' or 'bad'."
    ),
    choice_scores={"good": 1, "bad": 0},
    model=MODEL,
    temperature=0,
    use_cot=True,
)


def data():
    return [{"input": {"section": r["section"], "brief_text": r["brief_text"]},
             "expected": r["label"], "metadata": {"id": r["id"]}}
            for r in E.brief_sections(24)]


Eval(
    "twin-mind",
    data=data,
    task=lambda inp: inp["section"],   # passthrough; the LLM judge reads input.brief_text
    scores=[brief_section_judge],
    experiment_name="brief-judge-native",
)
