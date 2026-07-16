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
from run_regression import INBOX_DECISION_RULES, claude, code_grader  # reuse production logic

DATA = os.path.expanduser("~/twin-corpus/datasets")


def dataset():
    """List of {id, input:{scenario, available_sources}, expected_output, gold_behavior}."""
    return [json.loads(l) for l in open(os.path.join(DATA, "brief-inbox-decisions.jsonl"))]


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
                     "brief_text": briefs[idx]["body"], "subject": briefs[idx].get("subject", "")})
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
