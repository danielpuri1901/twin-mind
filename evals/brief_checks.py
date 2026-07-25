#!/usr/bin/env python3
"""Deterministic, reference-free checks for the morning brief - defined ONCE, used everywhere.

These are the "code check" layer from the eval design: intrinsic properties that need no golden
answer (sections present, format, date, topic dedup, no em dash, and the anti-fabrication
code-symbol-real check). The SAME functions run in three places:
  - the offline gate (evals/brief_eval.py),
  - the LangSmith online code evaluators (the trace-only ones), and
  - the box-side liveness heartbeat (the ones that need the repo on disk).

Each check is a pure function taking the brief as a plain dict (Brief.model_dump(), or a trace's
output JSON) and returning a CheckResult. `TRACE_ONLY` lists the checks that need nothing but the
brief itself, so they can run inside LangSmith's server-side sandbox. `code_symbol_real` needs the
repo on disk, so it runs on the box, not in the sandbox.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


SECTION_HEADERS = ["NEEDS YOU TODAY", "TODAY", "AI ADVANCEMENTS", "ONE TECHNICAL THING", "COACH"]
EM_DASH = "—"  # the character the format contract forbids; a detector must name it


def _norm(s: str) -> str:
    """Collapse whitespace and lowercase - for fuzzy text/topic matching."""
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _line_pos(text: str, header: str) -> int:
    """Position of `header` as a full line, so 'TODAY' does not match inside 'NEEDS YOU TODAY'."""
    m = re.search(rf"(?m)^{re.escape(header)}$", text or "")
    return m.start() if m else -1


def sections_present(brief: dict) -> CheckResult:
    """Every content section the schema promises is non-empty (needs_you_today may be empty)."""
    t = brief.get("technical_thing") or {}
    missing = []
    if not brief.get("ai_advancements"):
        missing.append("ai_advancements")
    if not (brief.get("coach") or "").strip():
        missing.append("coach")
    for k in ("topic", "concept", "code_path", "code_symbol", "quiz", "answer"):
        if not (str(t.get(k) or "")).strip():
            missing.append(f"technical_thing.{k}")
    return CheckResult("sections_present", not missing,
                       "all present" if not missing else f"empty: {', '.join(missing)}")


def format_ok(rendered: str) -> CheckResult:
    """The rendered brief has all five section headers, each on its own line, in order."""
    idx = [_line_pos(rendered, h) for h in SECTION_HEADERS]
    missing = [h for h, i in zip(SECTION_HEADERS, idx) if i < 0]
    present = [i for i in idx if i >= 0]
    in_order = present == sorted(present)
    ok = not missing and in_order
    detail = "ok" if ok else (f"missing {missing}" if missing else "headers out of order")
    return CheckResult("format_ok", ok, detail)


def date_matches(subject: str, expected_date_subject: str) -> CheckResult:
    """The email subject carries the authoritative date (catches the 'Friday 25 July' bug)."""
    ok = bool(expected_date_subject) and expected_date_subject in (subject or "")
    return CheckResult("date_matches", ok,
                       "ok" if ok else f"subject '{subject}' lacks '{expected_date_subject}'")


def technical_topic_fresh(brief: dict, taught_text: str) -> CheckResult:
    """The technical topic was not already taught (dedup against the taught list)."""
    topic = _norm((brief.get("technical_thing") or {}).get("topic", ""))
    ok = bool(topic) and topic not in _norm(taught_text)
    return CheckResult("technical_topic_fresh", ok,
                       "fresh" if ok else f"topic '{topic}' already taught")


def no_em_dash(brief: dict) -> CheckResult:
    """No em dash anywhere in the content (the format contract requires plain hyphens)."""
    t = brief.get("technical_thing") or {}
    blob = " ".join([
        brief.get("coach", "") or "",
        " ".join(brief.get("ai_advancements", []) or []),
        " ".join(str(v) for v in t.values()),
        " ".join(f"{i.get('who', '')} {i.get('what', '')} {i.get('why_now', '')}"
                 for i in (brief.get("needs_you_today") or [])),
    ])
    ok = EM_DASH not in blob
    return CheckResult("no_em_dash", ok, "ok" if ok else "contains em dash")


def code_symbol_real(brief: dict, repo_root: str) -> CheckResult:
    """ANTI-FABRICATION: the named technical code_symbol must be DEFINED in the file at code_path.

    The quote shown in the brief is injected from the file by the pipeline, so verifying the symbol
    resolves is what proves the shown code is real. Needs the repo on disk, so this runs in the box
    heartbeat / offline gate, NOT in LangSmith's server-side sandbox. code_path may carry a line suffix.
    """
    t = brief.get("technical_thing") or {}
    raw_path = (t.get("code_path") or "").strip()
    symbol = (t.get("code_symbol") or "").strip()
    if not raw_path or not symbol:
        return CheckResult("code_symbol_real", False, "missing code_path or code_symbol")
    path = re.sub(r":\d+(-\d+)?\s*$", "", raw_path).strip()
    full = path if os.path.isabs(path) else os.path.join(repo_root, path)
    if not os.path.isfile(full):
        return CheckResult("code_symbol_real", False, f"file not found: {path}")
    try:
        text = open(full, encoding="utf-8", errors="replace").read()
    except Exception as e:  # unreadable file is a check failure, surfaced - never swallowed
        return CheckResult("code_symbol_real", False, f"unreadable: {e}")
    ok = bool(re.search(rf"(?m)^\s*(?:async\s+def|def|class)\s+{re.escape(symbol)}\b"
                        rf"|^{re.escape(symbol)}\s*=(?!=)", text))
    return CheckResult("code_symbol_real", ok,
                       "symbol defined" if ok else f"symbol '{symbol}' not defined in file (fabrication?)")


# Checks that need only the brief itself - safe to run inside LangSmith's server-side sandbox.
TRACE_ONLY = [sections_present, no_em_dash]


def run_trace_only(brief: dict) -> list[CheckResult]:
    """The trace-only checks (no repo, no external context) - for the LangSmith online evaluator."""
    return [c(brief) for c in TRACE_ONLY]


def run_all(brief: dict, *, rendered: str = None, subject: str = None,
            expected_date_subject: str = None, taught_text: str = None,
            repo_root: str = None) -> list[CheckResult]:
    """Every check whose inputs are available - for the box heartbeat and the offline gate."""
    results = list(run_trace_only(brief))
    if rendered is not None:
        results.append(format_ok(rendered))
    if subject is not None and expected_date_subject is not None:
        results.append(date_matches(subject, expected_date_subject))
    if taught_text is not None:
        results.append(technical_topic_fresh(brief, taught_text))
    if repo_root is not None:
        results.append(code_symbol_real(brief, repo_root))
    return results
