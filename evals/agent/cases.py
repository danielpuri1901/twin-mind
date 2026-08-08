#!/usr/bin/env python3
"""Mine the Twin's real conversation history (box state.db) into replayable eval Cases.

A Case is one user turn made self-contained: what you asked, what the Twin replied, the tools it
called, whether it reached the corpus, and metadata. This is the AWS "offline task function"
source - we evaluate recorded history, not a live sample, which is the fit for sporadic usage.

Intent (capture / recall / reflect / learn / other) buckets each Case so we keep ONE clean dataset
per intent (never a blended set - the 0.37 lesson).

Run on the box (state.db + Bedrock live there):
  ~/.hermes/hermes-agent/venv/bin/python evals/agent/cases.py --limit 120 \
      --out ~/twin-corpus/datasets/agent-cases.jsonl
"""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # repo root
from pydantic import BaseModel

from shared.structured import structured_call

DB = os.path.expanduser("~/.hermes/state.db")
MODEL = "eu.anthropic.claude-sonnet-4-6"
INTENTS = ("capture", "recall", "reflect", "learn", "other")


class Intent(BaseModel):
    """One sentence of reasoning, then the bucket."""
    reason: str
    intent: str


INTENT_SYS = (
    "Classify ONE user turn sent to Daniel's personal AI 'Twin'. Write one sentence of reasoning, "
    "then the intent (exactly one of: capture, recall, reflect, learn, other).\n"
    "- capture: dumping a novel idea, a work learning, a link, or a note to remember or journal "
    "('just listened to X', 'add to this week's journal', an idea he wants saved for later).\n"
    "- recall: asking the Twin to retrieve a fact about his own life or corpus ('when did I...', "
    "a name or thing to look up in his own data).\n"
    "- reflect: thinking out loud about his life, career, or decisions, looking for perspective.\n"
    "- learn: asking it to explain or debate a concept or topic ('what is X', 'is AI a bubble', "
    "'what's the other side of the argument').\n"
    "- other: anything else - a quick practical ask, or meta/debugging the agent itself."
)


def classify(text):
    try:
        g = structured_call(MODEL, INTENT_SYS, f"USER TURN:\n{text[:1500]}", Intent, max_tokens=200)
        return g.intent if g.intent in INTENTS else "other"
    except Exception:
        return "other"


def _corpus_in_toolcalls(tool_calls_json):
    """True if an assistant tool_call ran corpus-search (it goes through terminal, so we read args)."""
    try:
        arr = json.loads(tool_calls_json) if isinstance(tool_calls_json, str) else (tool_calls_json or [])
        for tc in arr:
            fn = tc.get("function", tc) if isinstance(tc, dict) else {}
            if "corpus-search" in str(fn.get("arguments", "")):
                return True
    except Exception:
        pass
    return False


def mine(limit):
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        """SELECT m.session_id, m.role, m.content, m.tool_name, m.tool_calls, m.timestamp, m.finish_reason
           FROM messages m JOIN sessions s ON m.session_id = s.id
           WHERE s.source != 'cron'
           ORDER BY m.session_id, m.id"""
    ).fetchall()

    cases, cur_c = [], None
    for r in rows:
        role, content = r["role"], (r["content"] or "")
        if role == "user" and content.strip():
            if cur_c:
                cases.append(cur_c)
            cur_c = {"session_id": r["session_id"], "timestamp": r["timestamp"],
                     "input": content.strip(), "tools": [], "corpus_searched": False,
                     "final_response": "", "finish_reason": ""}
        elif cur_c is not None:
            if role == "assistant":
                if content.strip():
                    cur_c["final_response"] = content.strip()  # last assistant content = final reply
                if _corpus_in_toolcalls(r["tool_calls"]):
                    cur_c["corpus_searched"] = True
                if r["finish_reason"]:
                    cur_c["finish_reason"] = r["finish_reason"]
            elif role == "tool":
                if r["tool_name"]:
                    cur_c["tools"].append(r["tool_name"])
                if "corpus-search" in content[:300]:
                    cur_c["corpus_searched"] = True
    if cur_c:
        cases.append(cur_c)

    cases = [c for c in cases if len(c["input"]) > 2]
    return cases[-limit:]  # most recent `limit`


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--out", default=os.path.expanduser("~/twin-corpus/datasets/agent-cases.jsonl"))
    ap.add_argument("--no-classify", action="store_true")
    a = ap.parse_args()

    cases = mine(a.limit)
    if not a.no_classify:
        for i, c in enumerate(cases):
            c["intent"] = classify(c["input"])
            if (i + 1) % 20 == 0:
                print(f"  classified {i + 1}/{len(cases)}", file=sys.stderr)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # summary
    print(f"\n=== mined {len(cases)} Cases -> {a.out} ===")
    if not a.no_classify:
        from collections import Counter
        dist = Counter(c.get("intent", "?") for c in cases)
        print("intent distribution:", dict(dist))
    corpus_n = sum(1 for c in cases if c["corpus_searched"])
    tools_avg = sum(len(c["tools"]) for c in cases) / max(len(cases), 1)
    print(f"corpus-searched: {corpus_n}/{len(cases)} | avg tools/turn: {tools_avg:.1f}")
    print("\n=== 2 examples per intent ===")
    seen = {}
    for c in cases:
        it = c.get("intent", "?")
        if seen.get(it, 0) >= 2:
            continue
        seen[it] = seen.get(it, 0) + 1
        inp = " ".join(c["input"].split())[:90]
        resp = " ".join((c["final_response"] or "").split())[:80]
        print(f"  [{it}] in: {inp}")
        print(f"        tools={c['tools'][:6]} corpus={c['corpus_searched']} -> out: {resp}")


if __name__ == "__main__":
    main()
