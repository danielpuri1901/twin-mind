#!/usr/bin/env python3
"""Per-JOB calibration: one judge per brief section, one agreement number each.

Replaces the single blended judge (evals/calibrate_judges.py) whose 76% average hid that
teacher was 33%. Each section is now its own evaluator: its slice of the labels, its own
judge (evals/compare/eval_task.SECTION_JUDGES), its own agreement vs Daniel's labels, its
own target. Doctrine unchanged: where a section's judge disagrees, fix THAT section's
rubric, never the human's label.

Run on the box (datasets + instance-role Bedrock live there):
  ~/.hermes/hermes-agent/venv/bin/python evals/calibrate_sections.py
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "compare"))
import eval_task as E  # noqa: E402

# Per-section agreement target. teacher is intentionally the known-weak one - its low
# number is the point of the split (it was hidden inside the blended average before).
TARGETS = {"triage": 0.80, "ai_news": 0.80, "teacher": 0.80, "coach": 0.85, "overall": 0.70}

print("PER-SECTION JUDGE CALIBRATION - each section is its own evaluator")
print("(Sonnet, temp 0, vs Daniel's endorsed labels)\n")

grand = [0, 0]
for section in E.SECTIONS:
    rows = [r for r in E.section_rows(section) if r["label"] in ("good", "bad")]
    if not rows:
        print(f"  {section:9} no good/bad labels")
        continue
    ok, disagree = 0, []
    for r in rows:
        v, why = E.judge_one(section, r["brief_text"], r.get("date", ""), r.get("subject", ""))
        if v == r["label"]:
            ok += 1
        else:
            disagree.append(f"      [{r['id']}] Daniel={r['label']} judge={v}  ({why[:80]})")
    n = len(rows)
    grand[0] += ok
    grand[1] += n
    tgt = TARGETS.get(section, 0.80)
    flag = "OK " if ok / n >= tgt else "LOW"
    print(f"  {section:9} {ok}/{n}  ({ok / n * 100:.0f}%)  target {tgt * 100:.0f}%  [{flag}]")
    for d in disagree:
        print(d)

if grand[1]:
    print(f"\n  {'BLENDED':9} {grand[0]}/{grand[1]}  ({grand[0] / grand[1] * 100:.0f}%)"
          "  <- the old single number, shown for reference only; the per-section rows above are the truth")
