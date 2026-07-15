#!/usr/bin/env python3
"""THE BRIEF'S OWN BENCHMARK (born 2026-07-14 after Daniel: "the evals are fucked -
test the real job"). Each candidate model composes a FULL brief from a real captured
prefetch fixture + the real production skill. Scored by:
  1. the format contract (deterministic - same checks as the 07:50 watchdog)
  2. the calibrated section judges (80% agreement vs Daniel, judge pinned to Sonnet)
Usage: TWIN_TASK_MODEL=<model> python evals/run_brief_bench.py [--fixture YYYY-MM-DD]
"""
import argparse, glob, json, os, re, sys
import boto3
from botocore.config import Config as BotoCfg

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for line in open(os.path.join(HERE, ".env")):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)

MODEL = os.environ.get("TWIN_TASK_MODEL", "eu.anthropic.claude-sonnet-4-6")
JUDGE = "eu.anthropic.claude-sonnet-4-6"  # the ruler never varies
brt = boto3.client("bedrock-runtime", region_name="eu-west-1",
                   config=BotoCfg(read_timeout=240, retries={"max_attempts": 3}))

def call(model, system, user, max_tokens=3000, temperature=0.4):
    r = brt.converse(modelId=model, system=[{"text": system}],
                     messages=[{"role": "user", "content": [{"text": user}]}],
                     inferenceConfig={"maxTokens": max_tokens, "temperature": temperature})
    return next(c["text"] for c in r["output"]["message"]["content"] if "text" in c)

def format_score(brief):
    """Deterministic: the same contract the watchdog enforces. Returns (score, fails)."""
    fails = []
    if brief.count("━" * 10) < 8: fails.append("dividers")
    for h in ("1. NEEDS YOU TODAY", "2. TODAY", "3. AI ADVANCEMENTS", "4. ONE TECHNICAL THING", "5. COACH"):
        if h not in brief: fails.append(f"missing {h[:12]}")
    if "—" in brief: fails.append("em dash")
    if "4. ONE TECHNICAL THING" in brief and "Answer:" not in brief: fails.append("no Answer line")
    if not re.search(r"Reviewed \d+ messages since", brief): fails.append("no coverage line")
    if not re.search(r"°C|rain", brief): fails.append("no weather")
    checks = 6
    return (checks - min(len(fails), checks)) / checks, fails

JUDGE_SYS = """You are a strict, fair judge of a morning-brief draft. Judge it section by section, "good"/"bad" each, per the calibrated standards. Reason FIRST from the evidence, THEN give the verdict.
- triage: judge ONLY the document: clear one-liners (who/what/why-now), NO ready-to-send drafts (drafts = automatic bad), no contradictions.
- ai_news: 2-3 genuine insights not headlines; must not repeat topics listed as already-covered in the INPUT DATA.
- teacher: plain-words concept + real code path quoted + quiz. Judge teaching quality.
- coach: concrete personal fact, no platitudes.
- overall: readable fast, consistent, trustworthy.
<calibration_examples>
triage GOOD: clear who/what/why-now one-liners, no drafts. | triage BAD: includes a ready-to-send reply draft (automatic bad).
ai_news GOOD: fresh insights absent from the already-covered list. | ai_news BAD: repeats a topic the INPUT DATA marks already-covered.
teacher GOOD: plain concept anchored to a real code path + quiz. | teacher BAD: vague or an invented code path.
coach GOOD: a concrete personal fact tied to Daniel. | coach BAD: a generic platitude.
</calibration_examples>
Return JSON only, reason BEFORE verdict on each: {"triage":{"reason":"<=8w>","v":"good|bad"},"ai_news":{...},"teacher":{...},"coach":{...},"overall":{...}}"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", default=None)
    args = ap.parse_args()
    fx = sorted(glob.glob(os.path.expanduser("~/twin-corpus/datasets/brief-inputs/*.txt")))
    path = [f for f in fx if args.fixture and args.fixture in f] or fx[-1:]
    fixture = open(path[0]).read()
    skill = open(os.path.join(HERE, "agents/brief/SKILL.md")).read()
    brief = call(MODEL, skill + "\n\nCompose the brief now from the pre-fetched data. Output ONLY the email body.",
                 fixture, max_tokens=3000)
    fscore, fails = format_score(brief)
    raw = call(JUDGE, JUDGE_SYS, f"INPUT DATA (what the composer saw):\n{fixture[:3000]}\n\nBRIEF DRAFT:\n{brief[:7000]}",
               max_tokens=400, temperature=0)
    try:
        j = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
    except Exception:
        j = {}
    goods = sum(1 for v in j.values() if isinstance(v, dict) and v.get("v") == "good")
    print(f"MODEL: {MODEL}")
    print(f"  format (deterministic): {fscore:.2f}" + (f"  FAILS: {fails}" if fails else "  clean"))
    print(f"  judge sections good: {goods}/{len(j)}")
    for k, v in j.items():
        if isinstance(v, dict): print(f"    {k:9} {v.get('v','?'):5} {v.get('why','')}")
    print(f"  fixture: {os.path.basename(path[0])} | brief length: {len(brief)} chars")
if __name__ == "__main__":
    main()
