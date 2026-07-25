#!/usr/bin/env python3
"""Ship-gate grader A/B on LangSmith: prompt-parse judge (old) vs structured_call judge (new).

The regression suite's model_grader used prompt-for-JSON + re.search + `except: return
{"assertions": []}` - a parse miss silently yielded zero assertions, which main() then counted as
a FAIL with no explanation (a corrupted gate number, invisible). This A/B proves the retrofit on
the gate's own dataset before it ships:

  rows       = each gold item x TRIALS fresh candidate decisions (generated once, shared by both arms)
  arm OLD    = the exact prior mechanism (prompt for JSON, regex-extract, silent default)
  arm NEW    = run_regression.model_grader (forced tool-use + Pydantic, raises loudly)
  metrics    = parse_ok (target: NEW = 1.0), assertions_complete (one verdict per gold assertion),
               agreement_with_code (judged pass == deterministic code verdict - the label anchor
               that must hold: same decisions, so the arms should agree with gold equally or better)

Read in the LangSmith compare view (EU endpoint, project twin-mind).
"""
import json
import os
import re
import sys

EVALS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EVALS)
sys.path.insert(0, EVALS)
sys.path.insert(0, ROOT)
for _l in open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8"):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k, _v)

from langsmith import Client, traceable
import run_regression as RG

DATASET = "regression-judge"
TRIALS = 3

OLD_JUDGE_SYS = RG.JUDGE_SYS + """
Return JSON only, with why BEFORE passed on each: {"assertions": [{"assertion": "...", "why": "<reasoning>", "passed": true|false}]}"""


def judge_user(inputs):
    return (f"DECISION:\n{inputs['decision']}\n\nEXPECTED OUTPUT:\n{inputs['expected_output']}\n\n"
            f"GOLD ASSERTIONS:\n" + "\n".join(f"- {a}" for a in inputs["gold_behavior"]))


@traceable(name="judge_unstructured")
def judge_unstructured(inputs):
    raw, _, _ = RG.claude(OLD_JUDGE_SYS, judge_user(inputs), max_tokens=1500, temperature=0,
                          model=RG.JUDGE_MODEL)
    try:
        d = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        asserts = d.get("assertions", [])
        return {"parsed": True, "assertions": asserts,
                "item_pass": bool(asserts) and all(a.get("passed", a.get("pass")) for a in asserts)}
    except Exception:
        return {"parsed": False, "assertions": [], "item_pass": False}   # THE silent default


@traceable(name="judge_structured")
def judge_structured(inputs):
    try:
        v = RG.model_grader({"expected_output": inputs["expected_output"],
                             "gold_behavior": inputs["gold_behavior"]}, inputs["decision"])
        return {"parsed": True, "assertions": [a.model_dump() for a in v.assertions],
                "item_pass": bool(v.assertions) and all(a.passed for a in v.assertions)}
    except Exception as e:
        return {"parsed": False, "assertions": [], "item_pass": False, "error": str(e)[:200]}


def parse_ok(outputs) -> bool:
    return bool(outputs.get("parsed"))


def assertions_complete(outputs, inputs) -> bool:
    return len(outputs.get("assertions", [])) == len(inputs["gold_behavior"])


def agreement_with_code(outputs, inputs) -> bool:
    """Label anchor: the judge's item verdict should agree with the deterministic code verdict
    for the same decision (both graders looking at one truth)."""
    return bool(outputs.get("item_pass")) == bool(inputs["code_verdict"])


def main():
    client = Client()
    items = [json.loads(l) for l in open(RG.GOLD)]
    print(f"generating {len(items)} items x {TRIALS} decisions (shared by both arms)...")
    examples = []
    for item in items:
        user = (f"SCENARIO:\n{item['input']['scenario']}\n\nAVAILABLE SOURCES:\n"
                + "\n".join(f"- {s}" for s in item["input"]["available_sources"]))
        for t in range(TRIALS):
            d, _ = RG.decide(user)
            ok_code, _ = RG.code_grader(d, item["expected_output"])
            examples.append({"inputs": {
                "decision": RG.render_decision(d), "expected_output": item["expected_output"],
                "gold_behavior": item["gold_behavior"], "code_verdict": ok_code,
                "item_id": f"{item['id']}-t{t+1}"}})
    print(f"  {len(examples)} rows")

    try:
        exists = client.has_dataset(dataset_name=DATASET)
    except Exception:
        exists = False
    if not exists:
        ds = client.create_dataset(dataset_name=DATASET)
        client.create_examples(dataset_id=ds.id, examples=examples)
        print(f"  created dataset '{DATASET}'")
    else:
        print(f"  dataset '{DATASET}' exists (reusing)")

    evaluators = [parse_ok, assertions_complete, agreement_with_code]
    for prefix, target in [("judge-prompt-parse", judge_unstructured),
                           ("judge-structured", judge_structured)]:
        print(f"running experiment {prefix} ...")
        client.evaluate(target, data=DATASET, evaluators=evaluators, experiment_prefix=prefix)
        print(f"  done -> LangSmith '{prefix}'")


if __name__ == "__main__":
    main()
