"""Turn a relative date in a question into a real date range for the retrieval filter.

`corpus-search` has had `--since` and `--until` since it was written, and
nothing ever set them. So "what happened one year ago" went into BM25 as the
literal tokens "year" and "ago", and into the vector lane as a sentence with
no notion of when. Measured on Daniel's real corpus 2026-09-28, that question
returned a 2018 group chat and an unrelated iMessage.

It is also the largest gap in the benchmark. On LongMemEval_S,
temporal-reasoning is the biggest bucket at 127 of 470 questions, and 10 of
Daniel's own 17 corpus-retrieval questions are date-anchored. The LongMemEval
authors measured this exact fix at +6.8% to +11.3% recall, and warned that it
needs a capable model: "Llama 8B struggles to generate accurate time ranges,
often hallucinating or missing temporal cues even with numerous in-context
examples."

TWO STAGES, AND THE ORDER MATTERS FOR COST

A regex decides WHETHER a question is time-anchored. A model decides WHAT the
range is. The regex is there because `corpus-rag` runs on every turn, so an
unconditional model call would add a Bedrock round trip to every message
Daniel sends. Most questions have no temporal cue at all and skip the call
entirely.

The regex deliberately over-matches. A false positive costs one model call
that returns `has_time_reference: false`; a false negative silently loses the
whole feature for that question.

THE PROJECT RULE THIS RESPECTS

CLAUDE.md says the model never computes dates, because the 2026-07-24 brief
guessed "Friday 25 July" for a date that had not been injected, and got it
wrong. That rule is honoured here: the reference date is COMPUTED IN CODE and
injected into the prompt. The model resolves "one year ago" against a date it
was given, it never recalls what today is. The output shape is enforced
through `structured_call` (forced tool use plus a Pydantic schema), so a
malformed answer raises rather than silently degrading to no filter.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, field_validator

# Over-matches on purpose: a false positive costs one model call, a false
# negative loses the feature. Covers English and the Dutch that shows up in
# Daniel's corpus.
TEMPORAL_CUE = re.compile(
    r"\b("
    r"ago|last (?:week|month|year|time|night|summer|winter)|"
    r"yesterday|today|tonight|this (?:morning|week|month|year|afternoon|evening)|"
    r"recently|lately|back (?:in|then|when)|earlier|since|until|before|after|"
    r"when did|what happened|that (?:day|week|time)|"
    r"\d{4}|\d+ (?:days?|weeks?|months?|years?)|"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"mon(?:day)?|tues(?:day)?|wednes(?:day)?|thurs(?:day)?|fri(?:day)?|"
    r"satur(?:day)?|sun(?:day)?|"
    r"vorige|gisteren|vandaag|geleden|vorig jaar"
    r")\b", re.I)

SYSTEM = """You convert a time reference in a question into an absolute date range.

You are given today's date. Resolve every relative reference against it. Never
use any other notion of the current date.

Set has_time_reference to false when the question implies no particular period.
"When did I get banned?" asks for a date as the ANSWER but constrains no search
range, so it is false. "What happened last March?" is true.

Be generous with the range. It filters a search, so a range that is slightly
too wide still finds the record, and one that is slightly too narrow loses it.
For a vague reference like "recently" or "a while back", prefer several months
over several days."""


class TimeRange(BaseModel):
    """The shape the model is forced to return."""

    has_time_reference: bool
    since: Optional[str] = None
    until: Optional[str] = None
    reasoning: str = ""

    @field_validator("since", "until")
    @classmethod
    def _iso_date(cls, v):
        if v in (None, ""):
            return None
        datetime.strptime(v, "%Y-%m-%d")  # raises, and structured_call retries
        return v


def has_cue(question: str) -> bool:
    """Cheap gate. True means a model call is worth making."""
    return bool(TEMPORAL_CUE.search(question or ""))


def extract_range(question: str, today: Optional[date] = None, model: Optional[str] = None):
    """(since, until) as ISO strings, or (None, None).

    Fails open. A date filter is an optimisation, so a model error must leave
    retrieval exactly as it was rather than break the turn.
    """
    if not has_cue(question):
        return None, None
    today = today or date.today()
    try:
        from shared.bedrock_profiles import MODEL
        from shared.structured import structured_call
        user = (f"Today is {today.isoformat()} ({today.strftime('%A')}).\n\n"
                f"Question: {question}")
        result = structured_call(model or MODEL, SYSTEM, user, TimeRange, max_tokens=400)
    except Exception:  # fail open: no filter is always safe, a broken turn is not
        return None, None
    if not result.has_time_reference:
        return None, None
    return result.since, result.until


def main() -> int:
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("question")
    ap.add_argument("--today", default="")
    args = ap.parse_args()
    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else date.today()
    since, until = extract_range(args.question, today)
    print(json.dumps({"question": args.question, "today": today.isoformat(),
                      "cue": has_cue(args.question), "since": since, "until": until}))
    return 0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.exit(main())
