#!/usr/bin/env python3
"""
extract_pairs.py - inbound -> Daniel's actual reply pairs for the scorecard.
Stratified across contacts AND reply-length buckets so the gold set reflects
texting-Daniel and essay-Daniel alike (cold-review fix: no longest-first bias).
Output: ~/twin-corpus/index/scorecard-pairs.jsonl (never committed).
"""
import json
import os
from datetime import datetime, timedelta

SRC = os.path.expanduser("~/twin-corpus/normalized/imessage.jsonl")
OUT = os.path.expanduser("~/twin-corpus/index/scorecard-pairs.jsonl")


def bucket(p):
    n = len(p["reply"])
    return "short" if n < 80 else "medium" if n < 200 else "long"


def main():
    recs = [json.loads(l) for l in open(SRC, encoding="utf-8")]
    by_chat = {}
    for r in recs:
        by_chat.setdefault(r["chat"], []).append(r)

    pairs = []
    for chat, msgs in by_chat.items():
        msgs.sort(key=lambda r: r["date"])
        for i, m in enumerate(msgs):
            if m["who"] != "me" or i == 0 or msgs[i - 1]["who"] != "them":
                continue
            gap = (datetime.fromisoformat(m["date"])
                   - datetime.fromisoformat(msgs[i - 1]["date"]))
            if gap > timedelta(hours=12) or len(m["text"]) < 25:
                continue
            pairs.append({"chat": chat,
                          "context": [f'{x["who"]}: {x["text"]}'
                                      for x in msgs[max(0, i - 6):i - 1]],
                          "inbound": msgs[i - 1]["text"],
                          "reply": m["text"],
                          "date": m["date"]})

    groups = {}
    for p in pairs:
        groups.setdefault((p["chat"], bucket(p)), []).append(p)
    for g in groups.values():
        g.sort(key=lambda p: p["date"], reverse=True)  # prefer recent

    sample, keys = [], sorted(groups)
    while len(sample) < 200 and any(groups[k] for k in keys):
        for k in keys:
            if groups[k] and len(sample) < 200:
                sample.append(groups[k].pop(0))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for p in sample:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    n_chats = len({p["chat"] for p in sample})
    n_buckets = {b: sum(1 for p in sample if bucket(p) == b)
                 for b in ("short", "medium", "long")}
    print(f"{len(pairs)} pairs found; {len(sample)} stratified "
          f"across {n_chats} chats, buckets {n_buckets} -> {OUT}")


if __name__ == "__main__":
    main()
