#!/usr/bin/env python3
"""
make_gold_candidates.py - build the human curation sheet for the scorecard.
Merges stratified iMessage pairs (25) + threaded email pairs (15) into one
markdown file Daniel skims, marking [x] to keep. Output is local-only.
"""
import json
import os

IDX = os.path.expanduser("~/twin-corpus/index")
IM_PAIRS = os.path.join(IDX, "scorecard-pairs.jsonl")
GMAIL = os.path.expanduser("~/twin-corpus/normalized/gmail.jsonl")
OUT = os.path.join(IDX, "gold-curation.md")

NOISE = ("no-reply", "noreply", "notification", "mailer", "newsletter", "info@",
         "support@", "hello@", "team@", "billing")


def email_pairs(limit=15):
    recs = [json.loads(l) for l in open(GMAIL, encoding="utf-8")]
    by_id = {r["message_id"]: r for r in recs if r.get("message_id")}
    out = []
    for r in recs:
        if r["who"] != "me" or not r.get("in_reply_to"):
            continue
        parent = by_id.get(r["in_reply_to"])
        if not parent or parent["who"] != "them":
            continue
        if any(n in parent["sender"] for n in NOISE):
            continue
        if len(r["text"]) < 40:
            continue
        out.append({"kind": "email", "chat": parent["sender"],
                    "subject": r.get("subject", ""), "inbound": parent["text"][:600],
                    "reply": r["text"][:800], "date": r["date"]})
    out.sort(key=lambda p: p["date"], reverse=True)
    # one per correspondent, most recent first
    seen, uniq = set(), []
    for p in out:
        if p["chat"] not in seen:
            seen.add(p["chat"])
            uniq.append(p)
    return uniq[:limit]


def imessage_pairs(limit=25):
    pairs = [json.loads(l) for l in open(IM_PAIRS, encoding="utf-8")]
    uniq = []
    for p in pairs:  # already stratified by extract_pairs.py
        if sum(1 for u in uniq if u["chat"] == p["chat"]) < 2:  # max 2 per contact
            p["kind"] = "text"
            uniq.append(p)
        if len(uniq) >= limit:
            break
    return uniq


def main():
    cands = imessage_pairs() + email_pairs()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("# Gold pair curation\n\n")
        f.write("Mark `[x]` on ~20 pairs where the reply is authentically, recognizably you.\n")
        f.write("Kill anything you would not send today. Edit nothing else.\n\n")
        for i, p in enumerate(cands, 1):
            f.write(f"## [ ] {i}. ({p['kind']}) {p['chat']}  ·  {p['date'][:10]}\n\n")
            if p.get("subject"):
                f.write(f"Subject: {p['subject']}\n\n")
            f.write(f"**Inbound:** {p['inbound']}\n\n")
            f.write(f"**Your reply:** {p['reply']}\n\n---\n\n")
    print(f"{len(cands)} candidates -> {OUT}")


if __name__ == "__main__":
    main()
