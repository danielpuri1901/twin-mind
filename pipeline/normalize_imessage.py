#!/usr/bin/env python3
"""
normalize_imessage.py - convert imessage-exporter .txt exports into the corpus
common format: one JSONL record per message.

    {"source", "chat", "date", "who", "sender", "text"}

who = "me" | "them". Reads  ~/twin-corpus/raw/comms/imessage/*.txt
       writes ~/twin-corpus/normalized/imessage.jsonl
Read-only on the source. This is the template every other source's normalizer
will follow - same output shape, different parser.
"""
import os
import re
import json
from datetime import datetime

HOME = os.path.expanduser("~")
SRC = os.path.join(HOME, "twin-corpus", "raw", "comms", "imessage")
OUTDIR = os.path.join(HOME, "twin-corpus", "normalized")
OUT = os.path.join(OUTDIR, "imessage.jsonl")

# A timestamp line: e.g. "Jul 19, 2024  8:53:48 AM", possibly indented,
# possibly trailed by " (Read by you after ...)". Capture just the timestamp.
TS = re.compile(r"^\s*([A-Z][a-z]{2} \d{1,2}, \d{4}\s+\d{1,2}:\d{2}:\d{2}\s[AP]M)")

# Lines the exporter adds that are not message content.
ANNOTATION = re.compile(
    r"^\s*(This message responded to an earlier message\.|Edited \d|"
    r"(Loved|Liked|Disliked|Laughed|Emphasized|Questioned) by )"
)


def parse_ts(s):
    return datetime.strptime(re.sub(r"\s+", " ", s.strip()),
                             "%b %d, %Y %I:%M:%S %p").isoformat()


def parse_file(path, chat):
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    i, out = 0, []
    while i < len(lines):
        m = TS.match(lines[i])
        if not m:
            i += 1
            continue
        date = parse_ts(m.group(1))
        i += 1
        if i >= len(lines):
            break
        sender = lines[i].strip()
        i += 1
        body = []
        while i < len(lines) and not TS.match(lines[i]):
            if lines[i].strip() and not ANNOTATION.match(lines[i]):
                body.append(lines[i].strip())
            i += 1
        text = "\n".join(body).strip()
        if text:
            out.append({
                "source": "imessage",
                "chat": chat,
                "date": date,
                "who": "me" if sender == "Me" else "them",
                "sender": sender,
                "text": text,
            })
    return out


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    records, seen = [], set()
    for name in sorted(os.listdir(SRC)):
        if not name.endswith(".txt"):
            continue
        for r in parse_file(os.path.join(SRC, name), name[:-4]):
            key = (r["chat"], r["date"], r["who"], r["text"])
            if key not in seen:
                seen.add(key)
                records.append(r)
    records.sort(key=lambda r: r["date"])
    with open(OUT, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # verification summary - counts only, no private content
    me = sum(1 for r in records if r["who"] == "me")
    print(f"messages: {len(records)}  (me: {me}, them: {len(records) - me})")
    print(f"chats:    {len({r['chat'] for r in records})}")
    if records:
        print(f"range:    {records[0]['date'][:10]} -> {records[-1]['date'][:10]}")
    print(f"wrote:    {OUT}")


if __name__ == "__main__":
    main()
