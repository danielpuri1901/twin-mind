#!/usr/bin/env python3
"""The ONE eval every platform runs, so the four-way comparison is apples-to-apples.

Task: the inbox-decision policy (does Daniel need to act on this message?) - our real
regression eval. Dataset: brief-inbox-decisions. Scorer: deterministic verdict match
against the gold answer. Platform adapters (langfuse/langsmith/braintrust/arize) wrap
THIS module; none of the eval logic lives in an adapter.
"""
import json, os, sys

EVALS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # compare/ -> evals/
sys.path.insert(0, EVALS)
from run_regression import (INBOX_DECISION_RULES, claude, code_grader,  # reuse production logic
                            decide, render_decision)

DATA = os.path.expanduser("~/twin-corpus/datasets")


def dataset():
    """List of {id, input:{scenario, available_sources}, expected_output, gold_behavior}."""
    return [json.loads(l) for l in open(os.path.join(DATA, "brief-inbox-decisions.jsonl"))]


def run_task(inp):
    """inp = the item's `input` dict. Returns the model's decision as its deterministic text
    render (enforced Decision underneath - structured-output rule 2026-07-24)."""
    user = (f"SCENARIO:\n{inp['scenario']}\n\nAVAILABLE SOURCES:\n"
            + "\n".join(f"- {s}" for s in inp["available_sources"]))
    d, _ = decide(user)
    return render_decision(d)


def score(decision, expected_output):
    """Deterministic: 1.0 if the ACTIONABLE verdict matches gold, else 0.0."""
    ok, _ = code_grader(decision, expected_output)
    return 1.0 if ok else 0.0


# ---------------------------------------------------------------------------
# The richer eval to play with: an LLM-AS-JUDGE evaluator over real labeled briefs.
# Dataset = each brief section Daniel labeled good/bad. The judge scores it; we
# measure whether the judge AGREES with Daniel. This is the evaluator to clone and
# tweak inside each platform's UI - the whole point of the bake-off.
# ---------------------------------------------------------------------------
import re


def brief_sections(limit=None):
    """Join brief-archive (text) with brief-section-verdicts (Daniel's good/bad). One row per
    labeled section: {id, section, label, brief_text, subject}."""
    briefs = [json.loads(l) for l in open(os.path.join(DATA, "brief-archive.jsonl"))]
    rows = []
    for l in open(os.path.join(DATA, "brief-section-verdicts.jsonl")):
        r = json.loads(l)
        if r.get("verdict") not in ("good", "bad"):
            continue
        try:
            idx = int(str(r["brief"]).split("|")[0].strip())
        except ValueError:
            continue
        if idx >= len(briefs):
            continue
        rows.append({"id": f'{idx}:{r["section"]}', "section": r["section"], "label": r["verdict"],
                     "brief_text": briefs[idx]["body"], "subject": briefs[idx].get("subject", ""),
                     "date": briefs[idx].get("date", "")})
    return rows[:limit] if limit else rows


SECTION_JUDGE = """You are a strict, fair judge of ONE section of Daniel's morning-brief email.
Judge only the named section, verdict "good" or "bad".
- triage (1. NEEDS YOU TODAY): clear one-liners, no contradictions, plausible priorities (judge the document; staleness is checked elsewhere).
- ai_news: 2-3 genuine insights not headlines; a lead item repeating a recent brief = bad.
- teacher (4. ONE TECHNICAL THING): plain-words concept + a real code path + a quiz. Judge teaching quality.
- coach (5. COACH): a concrete fact from Daniel's real life, no platitudes.
- overall: consistent, trustworthy, fast to scan.
Reason first, then verdict. Return JSON only: {"reasoning":"<1-2 sentences>","verdict":"good|bad"}"""


def judge_section(brief_text, section):
    """LLM-as-judge -> ('good'|'bad', reasoning). THIS is the evaluator to play with."""
    user = f"SECTION TO JUDGE: {section}\n\nFULL BRIEF:\n{brief_text[:7000]}"
    raw, _, _ = claude(SECTION_JUDGE, user, max_tokens=300, temperature=0)
    try:
        v = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        return v.get("verdict", "?"), v.get("reasoning", "")
    except Exception:
        return "?", raw[:120]


def judge_agrees(judge_verdict, daniel_label):
    """Meta-score: did the LLM judge match Daniel's label? (the calibration number)."""
    return 1.0 if judge_verdict == daniel_label else 0.0


# ---------------------------------------------------------------------------
# PER-JOB decomposition (2026-07-16): one judge per section instead of one blended
# judge. Each section is a different job with its own criteria; a single good/bad
# blended across them hides per-section miscalibration (teacher sat at 33% inside a
# 76% average). Criteria + few-shot are lifted VERBATIM from evals/calibrate_judges.py
# so the split is behavior-preserving. overall stays holistic (a gestalt, never a rollup).
# ---------------------------------------------------------------------------
SECTIONS = ("triage", "ai_news", "teacher", "coach", "overall")


def section_rows(section, limit=None):
    """brief_sections() filtered to ONE section - the dataset for that section's evaluator."""
    rows = [r for r in brief_sections() if r["section"] == section]
    return rows[:limit] if limit else rows


# Named datasets the platform adapters mirror. The 5 section slices share one source file
# (brief-section-verdicts), filtered by section - no duplicate files to drift.
SECTION_DATASETS = {f"brief-{s}-verdicts": s for s in SECTIONS}


def dataset_rows(name):
    """Raw rows for any named dataset (for the platform mirrors). Section-slice names
    (brief-<section>-verdicts) filter the brief-section-verdicts source; every other name
    reads its own {name}.jsonl. Returns None if the source is missing."""
    if name in SECTION_DATASETS:
        sec = SECTION_DATASETS[name]
        src = os.path.join(DATA, "brief-section-verdicts.jsonl")
        return [r for r in (json.loads(l) for l in open(src)) if r.get("section") == sec]
    p = os.path.join(DATA, name + ".jsonl")
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else None


# (display label, standard, few-shot) per section - verbatim from calibrate_judges.py SYS.
SECTION_CRITERIA = {
    "triage": ("triage (1. NEEDS YOU TODAY)",
               "Judge ONLY what the document shows: clear one-liners, no contradictions, plausible "
               "prioritization. Do NOT guess staleness - external facts are checked elsewhere.",
               "GOOD: latest-message state applied, watch-don't-nudge correct for the date. | "
               "BAD: an item is stale - the call it references already happened."),
    "ai_news": ("ai_news (AI ADVANCEMENTS)",
                "2-3 insights not headlines; BAD if a topic repeats a recent brief. You judge ONE "
                "brief in isolation and cannot see prior briefs, so use this known repeat-history: "
                "Claude Sonnet 5 led from Jul 5 onward (repeat if it leads again on/after Jul 5); the "
                "Dan Luu fabrication story after Jul 6 = repeat; GPT-5.6 Sol/Terra after Jul 5 = "
                "repeat. Genuinely first mentions are fine.",
                "GOOD: fresh insights well-tied to why they matter. | "
                "BAD: same lead item as a recent brief (repetition)."),
    "teacher": ("teacher (4. ONE TECHNICAL THING)",
                "Judge TEACHING QUALITY only - plain words, real depth, real code with a path. "
                "(Answer-line presence is checked by code elsewhere - ignore it.)",
                "GOOD: concept in plain words anchored to a real file path. | "
                "BAD: taught well but built on a stale or ungrounded number."),
    "coach": ("coach (5. COACH)",
              "Cites a concrete fact from Daniel's real life, no platitudes.",
              "GOOD: anchored to a real thing Daniel did. | "
              "BAD: pushes action on a premise that is no longer true."),
    "overall": ("overall",
                "Judge the WHOLE brief holistically: consistent structure, trustworthy, readable "
                "fast. This is a gestalt - a brief can be good overall even if one section is weak; "
                "do NOT mechanically fail it for a single soft section.",
                "GOOD: coheres, trustworthy, scans fast. | "
                "BAD: internally inconsistent or hard to trust."),
}


def _section_judge_prompt(section):
    label, criteria, fewshot = SECTION_CRITERIA[section]
    return (f'You are a strict, fair judge of the "{label}" section of Daniel\'s morning-brief '
            f"email. Reason FIRST from the evidence, THEN give the verdict.\n"
            f"Standard: {criteria}\n"
            f"<calibration_examples>\n{fewshot}\n</calibration_examples>\n"
            'Return JSON only: {"reasoning":"<=2 sentences>","verdict":"good|bad"}')


SECTION_JUDGES = {s: _section_judge_prompt(s) for s in SECTIONS}


def judge_one(section, brief_text, date="", subject=""):
    """Per-section LLM judge -> ('good'|'bad', reasoning). Same model + temp as the blended
    judge (Sonnet, temp 0) so the decomposition is behavior-preserving."""
    user = (f"DATE SENT: {date}\nSUBJECT: {subject}\n\nSECTION TO JUDGE: {section}\n\n"
            f"FULL BRIEF:\n{brief_text[:7000]}")
    raw, _, _ = claude(SECTION_JUDGES[section], user, max_tokens=300, temperature=0)
    try:
        v = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        return v.get("verdict", "?"), v.get("reasoning", "")
    except Exception:
        return "?", raw[:120]
