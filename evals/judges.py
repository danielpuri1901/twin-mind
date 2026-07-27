#!/usr/bin/env python3
"""The brief's content judges - ONE source of truth.

Each judge grades a single ambiguous dimension code cannot check: a binary verdict plus a
one-sentence critique, on Bedrock (EU) at temp 0. The LangSmith online evaluators must mirror
these prompts verbatim, so the UI judge and the code judge stay the SAME judge - edit the prompt
here, then paste it into the online evaluator. align.py measures whichever judge lives here.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root -> shared.structured
from pydantic import BaseModel

from shared.structured import structured_call

MODEL = "eu.anthropic.claude-sonnet-4-6"


class InsightGrade(BaseModel):
    """Reason first, then the boolean - the reason forces the model to justify before it commits."""
    reason: str
    insight_is_real: bool


INSIGHT_SYS = (
    "You grade the AI-advancements section of Daniel's morning brief. Be strict. Write one sentence "
    "of reasoning, then the boolean.\n"
    "- insight_is_real: true only if the items are genuine insight (a non-obvious mechanism, tradeoff, "
    "or implication a sharp practitioner would NOT already know from the headline) that is useful to "
    "Daniel - not headlines, generic restatement, or vague trend-talk."
)


def judge_insight(ai_advancements):
    """Grade the AI-advancements section. Self-contained: the verdict is a property of the text alone."""
    items = ai_advancements if isinstance(ai_advancements, list) else [str(ai_advancements)]
    user = "=== AI ADVANCEMENTS ===\n" + "\n".join(str(x) for x in items)
    return structured_call(MODEL, INSIGHT_SYS, user, InsightGrade, max_tokens=400)


class FaithfulnessGrade(BaseModel):
    """Reason first, then the boolean."""
    reason: str
    coach_faithfulness: bool


FAITHFULNESS_SYS = (
    "You grade the COACH section of Daniel's morning brief for FAITHFULNESS (RAGAS faithfulness): is "
    "every factual claim the coach makes supported by the SOURCE facts it was given? Write one sentence "
    "of reasoning, then the boolean.\n"
    "- coach_faithfulness: true only if every claim about Daniel or his system is grounded in the SOURCE "
    "below (no fabrication, no unsupported specifics) AND the nudge is concrete, not a platitude."
)


def judge_coach_faithfulness(coach_output, source):
    """Grade the coach for faithfulness. RELATIONAL: needs both the coach text AND its source."""
    src = source if isinstance(source, str) else "\n".join(
        f"{k}: {str(v)[:700]}" for k, v in (source or {}).items())
    user = ("=== COACH ===\n" + str(coach_output) +
            "\n\n=== SOURCE (the only ground truth for faithfulness) ===\n" + src[:6000])
    return structured_call(MODEL, FAITHFULNESS_SYS, user, FaithfulnessGrade, max_tokens=400)
