#!/usr/bin/env python3
"""
run_baseline.py - draft replies for every gold pair and judge them.
Creates a Langfuse dataset run ("experiment") with per-slice scores.

Usage:  run with Hermes's venv python (has langfuse + boto3):
  ~/.hermes/hermes-agent/venv/bin/python tools/run_baseline.py --run baseline-v1

Draft recipe (deterministic, comparable across runs):
  voice profile + contact exemplars (corpus-search --chat) + context -> Sonnet draft
Judge: slice-conditioned rubric -> fidelity, aspiration (professional), content.
"""
import argparse
import json
import os
import subprocess
import sys

import boto3
from langfuse import get_client

HOME = os.path.expanduser("~")
GOLD = os.path.join(HOME, "twin-corpus/index/gold-set.jsonl")
VOICE = os.path.join(HOME, "twin-corpus/wiki/voice-profile.md")
SEARCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus_search.py")
MODEL = "eu.anthropic.claude-sonnet-4-6"
REGION = "eu-west-1"

brt = boto3.client("bedrock-runtime", region_name=REGION)


def claude(system, user, max_tokens=700):
    r = brt.converse(modelId=MODEL,
                     system=[{"text": system}],
                     messages=[{"role": "user", "content": [{"text": user}]}],
                     inferenceConfig={"maxTokens": max_tokens, "temperature": 0.4})
    return r["output"]["message"]["content"][0]["text"]


def exemplars(chat, k=8):
    """Recent messages Daniel sent in this conversation (contact-conditioned)."""
    try:
        out = subprocess.run([sys.executable, SEARCH, chat.split(",")[0][:20] or "hey",
                              "--chat", chat.split(",")[0], "--who", "me", "--k", str(k)],
                             capture_output=True, text=True, timeout=30).stdout
        return [json.loads(l)["text"] for l in out.splitlines() if l.strip()][:k]
    except Exception:
        return []


def draft(item, voice):
    ex = exemplars(item["chat"])
    ex_block = "\n".join(f"- {e[:200]}" for e in ex) or "(no exemplars found)"
    system = (
        "You are Daniel Puri's twin. Draft his reply to the inbound message. "
        "Match his real voice for THIS audience. Output ONLY the reply text.\n\n"
        f"AUDIENCE: {item['audience']} ({item['kind']})\n\n"
        f"HOW DANIEL ACTUALLY WRITES TO THIS PERSON (recent real examples):\n{ex_block}\n\n"
        f"VOICE PROFILE (excerpt):\n{voice[:3500]}\n\n"
        "If professional: Daniel-at-his-clearest - short sentences, one idea each, no filler."
    )
    ctx = "\n".join(item.get("context", []))
    user = (f"Subject: {item['subject']}\n" if item.get("subject") else "") + \
           (f"Conversation so far:\n{ctx}\n\n" if ctx else "") + \
           f"Inbound message:\n{item['inbound']}\n\nDraft Daniel's reply:"
    return claude(system, user)


JUDGE_SYS = (
    "You are a strict evaluator of a digital twin's drafted reply. Compare DRAFT to "
    "GOLD (what Daniel actually sent). Return ONLY JSON: "
    '{"content": 0-1, "fidelity": 0-1, "aspiration": 0-1, "why": "<=25 words"}\n'
    "content: does DRAFT convey the same essential decision/information as GOLD?\n"
    "fidelity: does DRAFT match Daniel's register for this audience (length, warmth, "
    "vocabulary) as evidenced by GOLD and the exemplars quoted in the task?\n"
    "aspiration: is DRAFT clear and concise - short sentences, one idea each, zero "
    "rambling? (Judge this on the draft's own quality, not similarity.)"
)


def judge(item, draft_text):
    user = (f"AUDIENCE: {item['audience']}\nINBOUND:\n{item['inbound'][:600]}\n\n"
            f"GOLD (Daniel's real reply):\n{item['reply'][:800]}\n\n"
            f"DRAFT (twin):\n{draft_text[:800]}")
    raw = claude(JUDGE_SYS, user, max_tokens=200)
    try:
        return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except Exception:
        return {"content": 0, "fidelity": 0, "aspiration": 0, "why": "judge parse fail"}


def main():
    from langfuse.experiment import Evaluation

    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    lf = get_client()
    dataset = lf.get_dataset("twin-gold-v1")
    voice = open(VOICE, encoding="utf-8").read() if os.path.exists(VOICE) else ""
    gold = {json.loads(l)["id"]: json.loads(l) for l in open(GOLD, encoding="utf-8")}
    items = dataset.items[:args.limit] if args.limit else dataset.items

    def task(*, item, **kw):
        return draft(gold[item.id], voice)

    def judge_evaluator(*, input, output, expected_output, metadata=None, **kw):
        gold_item = {"audience": (metadata or {}).get("audience", "unknown"),
                     "inbound": (input or {}).get("inbound", ""),
                     "reply": expected_output or ""}
        s = judge(gold_item, output or "")
        return [Evaluation(name=n, value=float(s.get(n, 0)),
                           comment=s.get("why", "")[:200])
                for n in ("content", "fidelity", "aspiration")]

    result = lf.run_experiment(
        name="twin-draft-eval",
        run_name=args.run,
        description="Draft recipe: voice profile + contact exemplars + Sonnet (EU)",
        data=items,
        task=task,
        evaluators=[judge_evaluator],
        max_concurrency=4,
    )
    lf.flush()

    # per-slice summary from the returned item results
    from collections import defaultdict
    agg = defaultdict(lambda: defaultdict(list))
    for ir in result.item_results:
        aud = (ir.item.metadata or {}).get("audience", "?") if hasattr(ir.item, "metadata") else "?"
        for ev in ir.evaluations:
            agg[aud][ev.name].append(float(ev.value))
    print(f"\n=== {args.run}: per-slice means ===")
    for aud, m in sorted(agg.items()):
        line = "  ".join(f"{k}={sum(v)/len(v):.2f}" for k, v in sorted(m.items()) if v)
        print(f"{aud:>14}: n={len(next(iter(m.values())))}  {line}")


if __name__ == "__main__":
    main()
