#!/usr/bin/env python3
"""Drafting benchmark: measures HOW GOOD replies are (voice, content) against 32 real pairs.
No pass bar - used to COMPARE recipes/models. 
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
# load .env ourselves - a keyless Langfuse constructs DISABLED (no .api) and
# crashes cryptically (learned 2026-07-14: the error says attribute, means credentials)
import os as _os
for _line in open(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), ".env")):
    if "=" in _line and not _line.strip().startswith("#"):
        _k, _v = _line.strip().split("=", 1)
        _os.environ.setdefault(_k, _v)
from langfuse import get_client

HOME = os.path.expanduser("~")
GOLD = os.path.join(HOME, "twin-corpus/datasets/drafting-gold.jsonl")
VOICE = os.path.join(HOME, "twin-corpus/wiki/voice-profile.md")
SEARCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus_search.py")
MODEL = os.environ.get("TWIN_TASK_MODEL", "eu.anthropic.claude-sonnet-4-6")
JUDGE_MODEL = "eu.anthropic.claude-sonnet-4-6"  # the ruler NEVER varies with the candidate
REGION = "eu-west-1"

from botocore.config import Config as _BotoCfg
brt = boto3.client("bedrock-runtime", region_name=REGION,
                   config=_BotoCfg(read_timeout=240, retries={"max_attempts": 3}))


def claude(system, user, max_tokens=700, temperature=0.4, model=None):
    r = brt.converse(modelId=model or MODEL,
                     system=[{"text": system}],
                     messages=[{"role": "user", "content": [{"text": user}]}],
                     inferenceConfig={"maxTokens": max_tokens, "temperature": temperature})
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


STOP = set("the and for with that this what when where your just like have has had "
           "you are was were will would could should about from they them then than "
           "there here been being some very much many more most also into over".split())


def topical_context(item, k=6):
    """Lexical topical retrieval: facts from Daniel's life relevant to the inbound,
    time-scoped to the pair's date, with answer-leakage guard."""
    text = item["inbound"] + " " + " ".join(item.get("context", [])[-2:])
    words = [w.strip(".,!?()\"'").lower() for w in text.split()]
    kw = sorted({w for w in words if len(w) >= 4 and w.isalpha() and w not in STOP},
                key=len, reverse=True)[:6]
    if not kw:
        return []
    mode = os.environ.get("TWIN_RETRIEVAL", "lexical")
    # lexical wants keywords; semantic/hybrid want the natural sentence (meaning)
    query = " ".join(kw) if mode == "lexical" else text[:300]
    try:
        out = subprocess.run([sys.executable, SEARCH, query, "--any",
                              "--mode", mode,
                              "--until", item["date"] + "T00:00:00", "--k", "12"],
                             capture_output=True, text=True, timeout=60).stdout
        hits = [json.loads(l) for l in out.splitlines() if l.strip()]
    except Exception:
        return []
    safe = []
    for h in hits:
        if h["chat"] == item["chat"] and abs(len(h["text"]) - len(item["reply"])) < 5:
            continue                                  # likely the gold reply itself
        if h["text"][:80] in item["reply"] or item["reply"][:80] in h["text"]:
            continue                                  # answer leakage
        if h["chat"] == item["chat"] and h["date"][:10] == item["date"]:
            continue                                  # same-thread same-day leakage
        safe.append(f'{h["date"][:10]} [{h["source"]}] {h["who"]}: {h["text"][:180]}')
        if len(safe) >= k:
            break
    return safe


def draft(item, voice):
    ex = exemplars(item["chat"])
    ex_block = "\n".join(f"- {e[:200]}" for e in ex) or "(no exemplars found)"
    # Audience-conditional retrieval - the bake-off verdict (2026-07-03), finally
    # deployed 2026-07-12 after Daniel's where-is-this-in-code question exposed the
    # drift: family drafts scored WORSE with retrieved facts (noise injection), so
    # code, not the model, decides. Professional/friends keep retrieval.
    facts = [] if item["audience"] == "family" else topical_context(item)
    facts_block = ("\n\nPOSSIBLY RELEVANT FACTS FROM DANIEL'S LIFE (retrieved from his "
                   "corpus as of this date; may be irrelevant - use ONLY if pertinent, "
                   "never force them in):\n" + "\n".join(f"- {f}" for f in facts)) if facts else ""
    system = (
        "You are Daniel Puri's twin. Draft his reply to the inbound message. "
        "Match his real voice for THIS audience. Output ONLY the reply text.\n\n"
        f"AUDIENCE: {item['audience']} ({item['kind']})\n\n"
        f"HOW DANIEL ACTUALLY WRITES TO THIS PERSON (recent real examples):\n{ex_block}\n\n"
        f"VOICE PROFILE (excerpt):\n{voice[:3500]}{facts_block}\n\n"
        "If professional: Daniel-at-his-clearest - short sentences, one idea each, no filler."
    )
    ctx = "\n".join(item.get("context", []))
    user = (f"Subject: {item['subject']}\n" if item.get("subject") else "") + \
           (f"Conversation so far:\n{ctx}\n\n" if ctx else "") + \
           f"Inbound message:\n{item['inbound']}\n\nDraft Daniel's reply:"
    return claude(system, user)



# Testability tags (audit 2026-07-13): 24/32 gold replies contain facts not derivable
# from context - those items test STYLE ONLY; scoring content on them measures data
# availability, not model quality. Tags: ~/twin-corpus/datasets/gold-audit.json
import json as _json, os as _os
_AUDIT = {t["id"]: t["verdict"] for t in _json.load(open(_os.path.expanduser(
    "~/twin-corpus/datasets/gold-audit.json")))} if _os.path.exists(_os.path.expanduser(
    "~/twin-corpus/datasets/gold-audit.json")) else {}

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


# --- Reference-overlap metrics (BLEU-2 precision, ROUGE-L recall) ---------
# Deterministic, free, computed alongside the judge. Their JOB here is not to
# replace the judge but to disagree with it instructively: high judge + low
# ROUGE = same meaning, different words (fine); low judge + high ROUGE =
# parroted surface, wrong substance (bad). Watch the disagreements.

def _ngrams(tokens, n):
    return [tuple(tokens[i:i+n]) for i in range(len(tokens)-n+1)]

def bleu2(draft, gold):
    """Modified 2-gram precision: of the draft's word-pairs, how many appear in gold."""
    d, g = draft.lower().split(), gold.lower().split()
    if len(d) < 2 or len(g) < 2:
        return 0.0
    dg, gg = _ngrams(d, 2), _ngrams(g, 2)
    from collections import Counter
    gc = Counter(gg)
    hits = sum(min(c, gc[t]) for t, c in Counter(dg).items())
    return hits / len(dg)

def rouge_l(draft, gold):
    """ROUGE-L recall: longest common subsequence / gold length - how much of
    the reference's word SEQUENCE the draft recovers."""
    d, g = draft.lower().split(), gold.lower().split()
    if not d or not g:
        return 0.0
    dp = [[0]*(len(g)+1) for _ in range(len(d)+1)]
    for i in range(1, len(d)+1):
        for j in range(1, len(g)+1):
            dp[i][j] = dp[i-1][j-1]+1 if d[i-1] == g[j-1] else max(dp[i-1][j], dp[i][j-1])
    return dp[-1][-1] / len(g)


def judge(item, draft_text):
    user = (f"AUDIENCE: {item['audience']}\nINBOUND:\n{item['inbound'][:600]}\n\n"
            f"GOLD (Daniel's real reply):\n{item['reply'][:800]}\n\n"
            f"DRAFT (twin):\n{draft_text[:800]}")
    raw = claude(JUDGE_SYS, user, max_tokens=200, temperature=0, model=JUDGE_MODEL)  # judge must be deterministic
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
