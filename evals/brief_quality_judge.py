#!/usr/bin/env python3
"""Box-side quality judge for the brief - the reference-free LLM-judge, run on OUR Bedrock (EU),
pushing only the SCORES to LangSmith as feedback.

Why box-side and not a LangSmith server-side evaluator: the server-side judge would need an AWS key
(or an OpenAI key) stored in LangSmith and would send the brief content to a third model provider.
Running it here keeps the brief content and the AWS credentials in our own infra - the box already
has Bedrock via its instance role - and LangSmith receives only the two numbers + the critique.

Judges the two AMBIGUOUS dimensions code cannot: is the AI section real insight, is the coach faithful
(every claim grounded in the day's facts - RAGAS faithfulness).
Binary + critique (the canonical method). This is a v0 rubric, to be aligned to Daniel's labels later.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # shared.structured
for _l in open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8"):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k, _v)

from langsmith import Client
from pydantic import BaseModel
from shared.structured import structured_call

MODEL = "eu.anthropic.claude-sonnet-4-6"


class Grade(BaseModel):
    """Quality verdict for a brief's two ambiguous sections. Reason first, then the boolean."""
    insight_reason: str     # one sentence: are the AI items genuine insight or headlines/filler
    insight_is_real: bool
    coach_reason: str       # one sentence: is every coach claim supported by the facts + concrete
    coach_faithfulness: bool


SYS = (
    "You grade the CONTENT quality of Daniel's morning brief. Be strict. For each item write one "
    "sentence of reasoning, then the boolean. Judge ONLY what is asked - ignore formatting, dates, "
    "and structure, which are checked by code.\n"
    "- insight_is_real: true only if the AI advancements are genuine insight (a non-obvious mechanism, "
    "tradeoff, or implication a sharp practitioner would not already know from the headline), not "
    "headlines, generic restatement, or vague trend-talk.\n"
    "- coach_faithfulness: true only if every factual claim the coach makes about Daniel or his system is "
    "supported by the FACTS given (faithful to the source, no fabrication), and it is a concrete, "
    "specific nudge, not a platitude."
)


def _facts_text(facts):
    if isinstance(facts, str):
        return facts[:6000]
    return "\n".join(f"{k}: {str(v)[:700]}" for k, v in (facts or {}).items())[:6000]


def judge(brief, facts):
    user = (
        "=== AI ADVANCEMENTS ===\n" + "\n".join(brief.get("ai_advancements", []) or [])
        + "\n\n=== COACH ===\n" + (brief.get("coach") or "")
        + "\n\n=== THE FACTS THE BRIEF WAS BUILT FROM (the only ground truth for grounding) ===\n"
        + _facts_text(facts)
    )
    return structured_call(MODEL, SYS, user, Grade, max_tokens=800)


def main():
    c = Client()
    runs = [r for r in c.list_runs(project_name="twin-mind", limit=25) if r.name == "brief.compose"]
    if not runs:
        print("no brief.compose runs found")
        return
    r = runs[0]
    brief = r.outputs or {}
    facts = (r.inputs or {}).get("facts")
    g = judge(brief, facts)
    # push ONLY the scores + critiques to LangSmith (reference-free feedback on the live run)
    c.create_feedback(r.id, key="insight_is_real", score=int(g.insight_is_real), comment=g.insight_reason)
    c.create_feedback(r.id, key="coach_faithfulness", score=int(g.coach_faithfulness), comment=g.coach_reason)
    print(f"judged brief.compose run {r.id}")
    print(f"  insight_is_real={g.insight_is_real} :: {g.insight_reason}")
    print(f"  coach_faithfulness={g.coach_faithfulness} :: {g.coach_reason}")


if __name__ == "__main__":
    main()
