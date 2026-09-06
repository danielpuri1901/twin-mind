#!/usr/bin/env python3
"""Deterministic, reference-free checks for the morning brief - defined ONCE, used everywhere.

These are the "code check" layer from the eval design: intrinsic properties that need no golden
answer (sections present, format, date, source-bound technical fields, and no em dash).
The SAME functions run in three places:
  - the offline gate (evals/brief_eval.py),
  - the LangSmith online code evaluators (the trace-only ones), and
  - the box-side liveness heartbeat (the ones that need the repo on disk).

Each check is a pure function taking the brief as a plain dict and returning a CheckResult.
`TRACE_ONLY` lists the checks that can run inside LangSmith's server-side sandbox.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


SECTION_HEADERS = ["NEEDS YOU TODAY", "TODAY", "AI ADVANCEMENTS", "ONE TECHNICAL THING", "COACH"]
REQUIRED_SECTION_HEADERS = ["NEEDS YOU TODAY", "TODAY", "AI ADVANCEMENTS", "COACH"]
EM_DASH = "—"  # the character the format contract forbids; a detector must name it


def _line_pos(text: str, header: str) -> int:
    """Position of `header` as a full line, so 'TODAY' does not match inside 'NEEDS YOU TODAY'."""
    m = re.search(rf"(?m)^{re.escape(header)}$", text or "")
    return m.start() if m else -1


def sections_present(brief: dict) -> CheckResult:
    """Every content section the schema promises is non-empty (needs_you_today may be empty)."""
    t = brief.get("technical_thing")
    missing = []
    if not brief.get("ai_advancements"):
        missing.append("ai_advancements")
    if not (brief.get("coach") or "").strip():
        missing.append("coach")
    if t is not None:
        for k in ("source_id", "project", "topic", "concept", "quiz", "answer"):
            if not (str(t.get(k) or "")).strip():
                missing.append(f"technical_thing.{k}")
    return CheckResult("sections_present", not missing,
                       "all present" if not missing else f"empty: {', '.join(missing)}")


def format_ok(rendered: str) -> CheckResult:
    """Required headers exist and the optional technical header is ordered when present."""
    positions = {header: _line_pos(rendered, header) for header in SECTION_HEADERS}
    missing = [header for header in REQUIRED_SECTION_HEADERS if positions[header] < 0]
    present = [positions[header] for header in SECTION_HEADERS if positions[header] >= 0]
    in_order = present == sorted(present)
    ok = not missing and in_order
    detail = "ok" if ok else (f"missing {missing}" if missing else "headers out of order")
    return CheckResult("format_ok", ok, detail)


def date_matches(subject: str, expected_date_subject: str) -> CheckResult:
    """The email subject carries the authoritative date (catches the 'Friday 25 July' bug)."""
    ok = bool(expected_date_subject) and expected_date_subject in (subject or "")
    return CheckResult("date_matches", ok,
                       "ok" if ok else f"subject '{subject}' lacks '{expected_date_subject}'")


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


# Checks that need only the brief itself - safe to run inside LangSmith's server-side sandbox.
TRACE_ONLY = [sections_present, no_em_dash]


def run_trace_only(brief: dict) -> list[CheckResult]:
    """The trace-only checks (no repo, no external context) - for the LangSmith online evaluator."""
    return [c(brief) for c in TRACE_ONLY]


def run_all(brief: dict, *, rendered: str = None, subject: str = None,
            expected_date_subject: str = None) -> list[CheckResult]:
    """Every check whose inputs are available."""
    results = list(run_trace_only(brief))
    if rendered is not None:
        results.append(format_ok(rendered))
    if subject is not None and expected_date_subject is not None:
        results.append(date_matches(subject, expected_date_subject))
    return results
