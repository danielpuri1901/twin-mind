#!/usr/bin/env python3
"""
make_gold_candidates.py - build the human curation sheet for the scorecard.
v2: quality-scored. Kills link/reel/attachment junk, requires conversational
substance, prefers inbound questions/requests (pairs with a clear right
answer). Merges best iMessage pairs (25) + threaded email pairs (15).
"""
import json
import os
import re

IDX = os.path.expanduser("~/twin-corpus/index")
IM_PAIRS = os.path.join(IDX, "scorecard-pairs.jsonl")
GMAIL = os.path.expanduser("~/twin-corpus/normalized/gmail.jsonl")
OUT = os.path.join(IDX, "gold-curation.md")

URL = re.compile(r"https?://|www\.|instagram\.com|tiktok\.com|youtu\.?be", re.I)
JUNK = re.compile(r"Tapbacks:|￼|GamePigeon|/Users/.+/Attachments/", re.I)
NOISE_SENDERS = ("no-reply", "noreply", "notification", "mailer", "newsletter",
                 "info@", "support@", "hello@", "team@", "billing",
                 "danielpuri1901@gmail.com")  # self-mail = agent briefs, excluded
QUESTION = re.compile(r"\?|^(can|could|would|will|do|did|does|are|is|when|where|"
                      r"what|why|how|who)\b", re.I)


def clean(text):
    return not URL.search(text) and not JUNK.search(text)


def quality(inbound, reply, context):
    if not (clean(inbound) and clean(reply)):
        return -1
    words = len(reply.split())
    if words < 6:
        return -1
    s = 0.0
    if QUESTION.search(inbound):
        s += 3            # a clear ask -> a verifiable right answer
    s += min(words / 40, 2)               # substance, capped
    s += min(len(context), 3) * 0.5       # real back-and-forth
    if len(inbound.split()) >= 5:
        s += 1            # inbound itself is substantive
    return s


def imessage_pairs(limit=25):
    pairs = [json.loads(l) for l in open(IM_PAIRS, encoding="utf-8")]
    scored = []
    for p in pairs:
        q = quality(p["inbound"], p["reply"], p.get("context", []))
        if q > 2:
            p["kind"], p["_q"] = "text", q
            scored.append(p)
    scored.sort(key=lambda p: p["_q"], reverse=True)
    uniq = []
    for p in scored:  # max 2 per contact for diversity
        if sum(1 for u in uniq if u["chat"] == p["chat"]) < 2:
            uniq.append(p)
        if len(uniq) >= limit:
            break
    return uniq


def email_pairs(limit=15):
    recs = [json.loads(l) for l in open(GMAIL, encoding="utf-8")]
    by_id = {r["message_id"]: r for r in recs if r.get("message_id")}
    scored, seen_reply = [], set()
    for r in recs:
        if r["who"] != "me" or not r.get("in_reply_to"):
            continue
        parent = by_id.get(r["in_reply_to"])
        if not parent or parent["who"] != "them":
            continue
        if any(n in parent["sender"] for n in NOISE_SENDERS):
            continue
        key = r["text"][:80]
        if key in seen_reply:               # kills template blasts
            continue
        q = quality(parent["text"][:600], r["text"][:800], ["email-thread"])
        if q <= 2:
            continue
        seen_reply.add(key)
        scored.append({"kind": "email", "chat": parent["sender"], "_q": q,
                       "subject": r.get("subject", ""),
                       "inbound": parent["text"][:600],
                       "reply": r["text"][:800], "date": r["date"],
                       "context": []})
    scored.sort(key=lambda p: (p["_q"], p["date"]), reverse=True)
    seen, uniq = set(), []
    for p in scored:  # one per correspondent
        if p["chat"] not in seen:
            seen.add(p["chat"])
            uniq.append(p)
        if len(uniq) >= limit:
            break
    return uniq


def main():
    cands = imessage_pairs() + email_pairs()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("# Gold pair curation (v2 - junk filtered, question-weighted)\n\n")
        f.write("Mark `[x]` on ~20 pairs where the reply is authentically, recognizably you\n")
        f.write("AND there is a clear right answer. Tag each keeper:\n")
        f.write("`F` family · `C` close friend · `P` professional · `O` other. Example: `## [x P] 12. ...`\n")
        f.write("Or just tell the agent: 'keep 2C, 5F, 12P, ...'\n\n")
        for i, p in enumerate(cands, 1):
            f.write(f"## [ ] {i}. ({p['kind']}) {p['chat']}  ·  {p['date'][:10]}\n\n")
            if p.get("subject"):
                f.write(f"Subject: {p['subject']}\n\n")
            for c in p.get("context", [])[-3:]:
                if c != "email-thread" and clean(c):
                    f.write(f"> {c}\n")
            f.write(f"\n**Inbound:** {p['inbound']}\n\n")
            f.write(f"**Your reply:** {p['reply']}\n\n---\n\n")
    n_txt = sum(1 for c in cands if c["kind"] == "text")
    print(f"{len(cands)} candidates ({n_txt} text, {len(cands)-n_txt} email) -> {OUT}")


if __name__ == "__main__":
    main()
