#!/usr/bin/env python3
"""Regression suite: proves the twin still avoids every mistake it has made in production.
Current items are inbox decisions (does this message need action from Daniel?) (dataset: twin-triage-v1); more failure classes join as they occur.

Anatomy (Anthropic "Demystifying evals for agents", adopted 2026-07-08):
  task  = one brief-inbox-decisions.jsonl item (evidence bundle -> expected judgment)
  trial = one model attempt; TRIALS=3 because n=1 conflates variance with change
  graders per task:
    1. code-based   : output must carry an explicit "ACTIONABLE: yes|no" verdict
                      line, and it must match the gold verdict (deterministic)
    2. model-based  : temp-0 judge scores each gold_behavior assertion pass/fail
  tracked_metrics  : latency_s, output_tokens per trial
Scope note: this replays the JUDGMENT policy (rules + model), not the full Hermes
harness; outcome-grading applies to the live brief (inbox/heartbeat checks), not here.
Regression semantics: suite target is 100% - any failing item = alarm, fix before ship.

Run with Hermes venv python (has boto3 + langfuse): needs a live AWS session.
  ~/.hermes/hermes-agent/venv/bin/python tools/run_triage.py [--trials 3]
"""
import argparse, json, os, re, sys, time

import boto3
from pydantic import BaseModel

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from shared.structured import structured_call
GOLD = os.path.expanduser("~/twin-corpus/datasets/brief-inbox-decisions.jsonl")
REGION = "eu-west-1"
MODEL = os.environ.get("TWIN_TASK_MODEL", "eu.anthropic.claude-sonnet-4-6")
JUDGE_MODEL = "eu.anthropic.claude-sonnet-4-6"  # the ruler NEVER varies with the candidate
brt = boto3.client("bedrock-runtime", region_name=REGION)

def _load_production_rules():
    """Extract the decision rules FROM the deployed skill so the gate tests the
    PRODUCTION text, not a paraphrase (stepback #5: 'the gate evaluated a prompt
    that is not the one in production')."""
    skill = open(os.path.join(HERE, "agents/brief/SKILL.md")).read()
    # v3 anchor: the decision rules live inside section 1 (NEEDS YOU TODAY)
    start = skill.index("1. NEEDS YOU TODAY")
    end = skill.index("2. TODAY")
    block = "Rules (from the production skill, section 1):\n" + skill[start:end]
    return ("You are Twin Mind, deciding for each email: does Daniel need to act on this or not.\n"
            + block +
            "\nGiven the evidence, decide via the tool: actionable yes/no, plus 2-4 sentences of "
            "judgment on the current state and what (if anything) belongs in the brief.")

INBOX_DECISION_RULES = _load_production_rules()


# ---------- enforced shapes (structured-output rule 2026-07-24: never scrape an LLM output) ----------

class Decision(BaseModel):
    """An inbox-triage decision: does Daniel need to act on this?"""
    actionable: bool   # does this need action/a decision from Daniel today?
    reasoning: str     # 2-4 sentences: judgment of the current state, what belongs in the brief


class AssertionCheck(BaseModel):
    assertion: str   # the gold assertion, verbatim
    why: str         # reasoning FIRST - commit to the verdict only after
    passed: bool     # does the decision satisfy the assertion on substance?


class AssertionVerdicts(BaseModel):
    """Per-assertion verdicts on an inbox decision. No holistic verdict - assertions only
    (ruling 2026-07-14: specific and auditable beats vibes)."""
    assertions: list[AssertionCheck]


JUDGE_SYS = """You are a strict, fair evaluator. Given an inbox-decision DECISION and a list of GOLD
ASSERTIONS describing correct behavior, judge whether the decision satisfies each assertion on
SUBSTANCE, not wording. For each assertion, write your reasoning (why) BEFORE committing to passed
(reason first, then the verdict).
<example>
ASSERTION: "collapse each thread to its LATEST message before judging state"
DECISION notes the reply already confirmed the plan, so no nudge -> why: judged on the newest message, loop closed; passed: true.
DECISION reminds about the original ask, ignoring the later reply -> why: judged on a superseded message; passed: false.
</example>
Cover every gold assertion, each exactly once."""


def claude(system, user, max_tokens=500, temperature=0.4, model=None):
    t0 = time.time()
    r = brt.converse(modelId=model or MODEL,
                     system=[{"text": system}],
                     messages=[{"role": "user", "content": [{"text": user}]}],
                     inferenceConfig={"maxTokens": max_tokens, "temperature": temperature})
    # gpt-oss returns a reasoning block before the text block - find the text
    text = next(c["text"] for c in r["output"]["message"]["content"] if "text" in c)
    usage = r.get("usage", {})
    return text, time.time() - t0, usage.get("outputTokens", 0)


def decide(user):
    """The candidate decision as an ENFORCED shape (was: free text + a regex for the ACTIONABLE
    line). temperature stays 0.4 - trials exist to expose the candidate's real variance."""
    t0 = time.time()
    d = structured_call(MODEL, INBOX_DECISION_RULES, user, Decision,
                        max_tokens=500, temperature=0.4)
    return d, time.time() - t0


def render_decision(d):
    """Deterministic text form of a Decision (for the judge + logs)."""
    return f"ACTIONABLE: {'yes' if d.actionable else 'no'}\n{d.reasoning}"


def code_grader(decision, expected_output):
    # accepts a Decision, or the deterministic render_decision() text (platform adapters pass
    # text outputs around) - parsing OUR OWN render is code-parsing-code, not LLM scraping.
    if isinstance(decision, Decision):
        got = "yes" if decision.actionable else "no"
    else:
        m = re.match(r"\s*ACTIONABLE:\s*(yes|no)", str(decision), re.I)
        if not m:
            return False, "missing verdict line"
        got = m.group(1).lower()
    # gold side stays a regex - that reads the DATASET text, not an LLM output
    gold = "no" if re.search(r"NOT actionable|no nudge|no action", expected_output, re.I) else "yes"
    return got == gold, f"verdict={got} gold={gold}"


def model_grader(item, decision_text):
    """The judge as an ENFORCED shape (was: prompt-for-JSON + re.search + a silent
    empty-assertions default that corrupted the gate). Raises loudly if it cannot validate."""
    user = (f"DECISION:\n{decision_text}\n\nEXPECTED OUTPUT:\n{item['expected_output']}\n\n"
            f"GOLD ASSERTIONS:\n" + "\n".join(f"- {a}" for a in item["gold_behavior"]))
    return structured_call(JUDGE_MODEL, JUDGE_SYS, user, AssertionVerdicts, max_tokens=1500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3)
    args = ap.parse_args()
    items = [json.loads(l) for l in open(GOLD)]
    print(f"inbox-decisions regression: {len(items)} tasks x {args.trials} trials\n")
    suite_pass = True
    for item in items:
        user = (f"SCENARIO:\n{item['input']['scenario']}\n\nAVAILABLE SOURCES:\n"
                + "\n".join(f"- {s}" for s in item["input"]["available_sources"]))
        passes = 0
        for t in range(args.trials):
            decision, lat = decide(user)
            ok_code, code_why = code_grader(decision, item["expected_output"])
            verdict = model_grader(item, render_decision(decision))   # raises on invalid - never silent
            asserts = verdict.assertions
            ok = ok_code and bool(asserts) and all(a.passed for a in asserts)
            passes += ok
            failed = [a.assertion for a in asserts if not a.passed]
            print(f"  {item['id']} trial {t+1}: {'PASS' if ok else 'FAIL'} "
                  f"(code: {code_why}; assertions: {sum(a.passed for a in asserts)}/{len(asserts)}"
                  f"{'; failed: ' + '; '.join(failed) if failed else ''}) "
                  f"[{lat:.1f}s]")
        rate = passes / args.trials
        print(f"  {item['id']}: pass rate {passes}/{args.trials}\n")
        if rate < 1.0:
            suite_pass = False
    print("SUITE:", "PASS (regression bar held)" if suite_pass else
          "FAIL - regression suite must be 100%; fix before shipping changes")
    sys.exit(0 if suite_pass else 1)


if __name__ == "__main__":
    main()
