#!/usr/bin/env python3
"""Regression suite: proves the twin still avoids every mistake it has made in production.
Current items are inbox-triage judgments (dataset: twin-triage-v1); more failure classes join as they occur.

Anatomy (Anthropic "Demystifying evals for agents", adopted 2026-07-08):
  task  = one triage-gold.jsonl item (evidence bundle -> expected judgment)
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

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD = os.path.expanduser("~/twin-corpus/index/triage-gold.jsonl")
REGION = "eu-west-1"
MODEL = os.environ.get("TWIN_TASK_MODEL", "eu.anthropic.claude-sonnet-4-6")
JUDGE_MODEL = "eu.anthropic.claude-sonnet-4-6"  # the ruler NEVER varies with the candidate
brt = boto3.client("bedrock-runtime", region_name=REGION)

INBOX_DECISION_RULES = """You are Twin Mind, deciding for each email: does Daniel need to act on this or not.
Rules (from the morning-brief skill):
- Latest-state check: before marking ANY item actionable, verify it is still live. The newest
  evidence wins. A reply that confirms a plan closes a loop. If state is ambiguous, present it
  as a question, never as an action.
- Source-coverage: for any person in a pending call/meeting/reschedule thread, consult meeting
  notes (Granola) and the corpus wiki before judging state.
- Never propose nudging or replying to someone whose latest message already answered the question.
Given the evidence, produce:
1. First line exactly: "ACTIONABLE: yes" or "ACTIONABLE: no"
2. Then 2-4 sentences: your judgment of the current state and what (if anything) belongs in the brief."""

JUDGE_SYS = """You are a strict evaluator. Given a triage DECISION and a list of GOLD ASSERTIONS
describing correct behavior, return JSON only:
{"assertions": [{"assertion": "...", "pass": true|false, "why": "..."}], "overall": true|false}
"overall" is true only if the decision's substance would lead to the same brief content as the
EXPECTED OUTPUT. Judge substance, not wording."""


def claude(system, user, max_tokens=500, temperature=0.4, model=None):
    t0 = time.time()
    r = brt.converse(modelId=model or MODEL,
                     system=[{"text": system}],
                     messages=[{"role": "user", "content": [{"text": user}]}],
                     inferenceConfig={"maxTokens": max_tokens, "temperature": temperature})
    text = r["output"]["message"]["content"][0]["text"]
    usage = r.get("usage", {})
    return text, time.time() - t0, usage.get("outputTokens", 0)


def code_grader(decision, expected_output):
    m = re.match(r"\s*ACTIONABLE:\s*(yes|no)", decision, re.I)
    if not m:
        return False, "missing verdict line"
    got = m.group(1).lower()
    gold = "no" if re.search(r"NOT actionable|no nudge|no action", expected_output, re.I) else "yes"
    return got == gold, f"verdict={got} gold={gold}"


def model_grader(item, decision):
    user = (f"DECISION:\n{decision}\n\nEXPECTED OUTPUT:\n{item['expected_output']}\n\n"
            f"GOLD ASSERTIONS:\n" + "\n".join(f"- {a}" for a in item["gold_behavior"]))
    raw, _, _ = claude(JUDGE_SYS, user, max_tokens=400, temperature=0, model=JUDGE_MODEL)
    try:
        return json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
    except Exception:
        return {"assertions": [], "overall": False, "error": raw[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3)
    args = ap.parse_args()
    items = [json.loads(l) for l in open(GOLD)]
    print(f"twin-triage regression: {len(items)} tasks x {args.trials} trials\n")
    suite_pass = True
    for item in items:
        user = (f"SCENARIO:\n{item['input']['scenario']}\n\nAVAILABLE SOURCES:\n"
                + "\n".join(f"- {s}" for s in item["input"]["available_sources"]))
        passes = 0
        for t in range(args.trials):
            decision, lat, toks = claude(INBOX_DECISION_RULES, user)
            ok_code, code_why = code_grader(decision, item["expected_output"])
            verdict = model_grader(item, decision)
            ok = ok_code and verdict.get("overall", False)
            passes += ok
            failed = [a["assertion"] for a in verdict.get("assertions", []) if not a["pass"]]
            print(f"  {item['id']} trial {t+1}: {'PASS' if ok else 'FAIL'} "
                  f"(code: {code_why}; judge: {verdict.get('overall')}"
                  f"{'; failed: ' + '; '.join(failed) if failed else ''}) "
                  f"[{lat:.1f}s, {toks} out-toks]")
        rate = passes / args.trials
        print(f"  {item['id']}: pass rate {passes}/{args.trials}\n")
        if rate < 1.0:
            suite_pass = False
    print("SUITE:", "PASS (regression bar held)" if suite_pass else
          "FAIL - regression suite must be 100%; fix before shipping changes")
    sys.exit(0 if suite_pass else 1)


if __name__ == "__main__":
    main()
