#!/usr/bin/env python3
"""Scores one morning brief on its own Langfuse trace, inside the brief's run on the box.

Two layers, both from their single source of truth:
  - the calibrated judges in evals/judges.py (Anthropic API, Sonnet 4.6 at temperature 0),
  - the trace-only code checks in evals/brief_checks.py.

compose_brief.py calls score_brief() inside the "brief" trace, so every real morning carries its
scores. No judge credential lives in a third-party evaluator: the judges use the box's own key, and
Langfuse receives only the scores and critiques. Replaced the LangSmith online evaluators on
2026-10-28.

Fail-open: a judge or Langfuse error is reported on stderr and never stops the brief.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root

from evals.brief_checks import run_trace_only
from evals.judges import judge_coach_faithfulness, judge_insight
from shared.structured import get_client


def score_brief(brief, facts):
    """Judge `brief` (a plain dict) against its `facts` and score the current Langfuse trace."""
    if get_client is None:  # no Langfuse SDK: nowhere to put the scores, so skip the judge calls
        return
    try:
        ins = judge_insight(brief.get("ai_advancements") or [])
        coach = judge_coach_faithfulness(brief.get("coach") or "", facts)
        scores = [("insight_is_real", ins.insight_is_real, ins.reason),
                  ("coach_faithfulness", coach.coach_faithfulness, coach.reason)]
        scores += [(c.name, c.passed, c.detail) for c in run_trace_only(brief)]
        for name, ok, why in scores:
            get_client().score_current_trace(name=name, value=int(ok), data_type="BOOLEAN", comment=why)
    except Exception as e:
        print(f"brief scoring failed: {type(e).__name__}: {e}", file=sys.stderr)
