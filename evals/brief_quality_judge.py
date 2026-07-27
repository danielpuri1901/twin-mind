#!/usr/bin/env python3
"""Box-side feedback pusher for the brief - runs the calibrated judges on OUR Bedrock (EU) and
pushes ONLY the scores + critiques to LangSmith as feedback on the live run.

Why box-side, not a LangSmith server-side evaluator: server-side would need an AWS/OpenAI key
stored in LangSmith and would send the brief content to a third provider. Running here keeps the
content and the credentials in our own infra (the box has Bedrock via its instance role); LangSmith
receives only the numbers + critique. This is the reference example of the box-side
"judge -> push feedback" pattern the agent eval reuses.

The judges themselves are the single source of truth in evals/judges.py - this file only wires
them to a run and pushes feedback.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
for _l in open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8"):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k, _v)

from langsmith import Client

from evals.judges import judge_coach_faithfulness, judge_insight


def main():
    c = Client()
    runs = [r for r in c.list_runs(project_name="twin-mind", limit=25) if r.name == "brief.compose"]
    if not runs:
        print("no brief.compose runs found")
        return
    r = runs[0]
    brief = r.outputs or {}
    facts = (r.inputs or {}).get("facts")
    ins = judge_insight(brief.get("ai_advancements") or [])
    coach = judge_coach_faithfulness(brief.get("coach") or "", facts)
    c.create_feedback(r.id, key="insight_is_real", score=int(ins.insight_is_real), comment=ins.reason)
    c.create_feedback(r.id, key="coach_faithfulness", score=int(coach.coach_faithfulness), comment=coach.reason)
    print(f"judged brief.compose run {r.id}")
    print(f"  insight_is_real={ins.insight_is_real} :: {ins.reason}")
    print(f"  coach_faithfulness={coach.coach_faithfulness} :: {coach.reason}")


if __name__ == "__main__":
    main()
