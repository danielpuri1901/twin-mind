#!/usr/bin/env python3
"""Judge calibration: Sonnet judges all archived briefs section-by-section;
agreement vs Daniel's endorsed labels computes per section. Disagreements listed
- doctrine: fix the RUBRIC where they disagree, never the human."""
import boto3, json, os, re
from collections import defaultdict

brt = boto3.client("bedrock-runtime", region_name="eu-west-1")
SYS = """You are a strict, fair judge of Daniel's morning-brief email. Judge it section by section, verdict "good" or "bad" ("n/a" if the section is absent), per these standards. Reason FIRST from the evidence, THEN give the verdict.
- triage (1. NEEDS YOU TODAY): judge ONLY what the document shows: clear one-liners, no contradictions, plausible prioritization. Do NOT guess staleness - external facts are checked elsewhere.
- ai_news: 2-3 insights not headlines; BAD if a topic repeats a recent brief. You judge ONE brief in isolation and cannot see prior briefs, so use this known repeat-history: Claude Sonnet 5 led from Jul 5 onward (repeat if it leads again on/after Jul 5); the Dan Luu fabrication story after Jul 6 = repeat; GPT-5.6 Sol/Terra after Jul 5 = repeat. Genuinely first mentions are fine. (Durable fix later: inject the covered-topics list as data instead of hardcoding.)
- teacher (4. ONE TECHNICAL THING): judge TEACHING QUALITY only - plain words, real depth, real code with a path. (Answer-line presence is checked by code elsewhere - ignore it.) Section absent = "n/a".
- coach: cites a concrete fact from Daniel's real life, no platitudes. Absent = "n/a".
- overall: consistent structure, trustworthy, readable fast.
<calibration_examples>
triage GOOD: latest-message state applied, watch-don't-nudge correct for the date. | triage BAD: an item is stale - the call it references already happened.
ai_news GOOD: fresh insights well-tied to why they matter. | ai_news BAD: same lead item as a recent brief (repetition).
teacher GOOD: concept in plain words anchored to a real file path. | teacher BAD: taught well but built on a stale or ungrounded number.
coach GOOD: anchored to a real thing Daniel did. | coach BAD: pushes action on a premise that is no longer true.
</calibration_examples>
Return JSON only, each section an object with reason BEFORE verdict: {"triage":{"reason":"<=8 words>","v":"good|bad|n/a"}, "ai_news":{...}, "teacher":{...}, "coach":{...}, "overall":{...}}"""

briefs = [json.loads(l) for l in open(os.path.expanduser("~/twin-corpus/datasets/brief-archive.jsonl"))]
labels = defaultdict(dict)
for l in open(os.path.expanduser("~/twin-corpus/datasets/brief-section-verdicts.jsonl")):
    r = json.loads(l)
    labels[r["brief"].split("|")[0].strip()][r["section"]] = r["verdict"]

agree = defaultdict(lambda: [0, 0])
disagreements = []
for idx, b in enumerate(briefs):
    key = str(idx)
    gold = labels.get(key, {})
    if not gold or gold.get("overall") == "skip":
        continue
    resp = brt.converse(modelId="eu.anthropic.claude-sonnet-4-6", system=[{"text": SYS}],
        messages=[{"role": "user", "content": [{"text": f"DATE SENT: {b['date']}\nSUBJECT: {b['subject']}\n\n{b['body'][:7000]}"}]}],
        inferenceConfig={"maxTokens": 400, "temperature": 0})
    txt = resp["output"]["message"]["content"][0]["text"]
    try:
        v = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
    except Exception as e:
        print(f"  [PARSE FAIL {idx}]: {e} | raw: {txt[:120]}")
        continue
    for sec in ("triage", "ai_news", "teacher", "coach", "overall"):
        jv = v.get(sec) or {}
        g, j = gold.get(sec), (jv.get("v") if isinstance(jv, dict) else jv)
        if g in ("good", "bad") and j in ("good", "bad"):
            agree[sec][1] += 1
            if g == j:
                agree[sec][0] += 1
            else:
                why = (jv.get("reason", jv.get("why", "")) if isinstance(jv, dict) else "")
                disagreements.append(f"[{idx}] {b['subject'][:30]} {sec}: Daniel={g} judge={j} ({why})")

print("JUDGE CALIBRATION - Sonnet vs Daniel's endorsed labels")
tot = [0, 0]
for sec, (a, n) in agree.items():
    print(f"  {sec:10} {a}/{n}  ({a/n*100:.0f}%)" if n else f"  {sec:10} no comparable labels")
    tot[0] += a; tot[1] += n
print(f"  {'OVERALL':10} {tot[0]}/{tot[1]}  ({tot[0]/tot[1]*100:.0f}%)")
print("\nDISAGREEMENTS (rubric-fix candidates):")
for d in disagreements: print("  " + d)
