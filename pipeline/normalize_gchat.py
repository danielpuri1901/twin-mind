#!/usr/bin/env python3
"""
normalize_gchat.py - convert Google Chat Takeout (Groups/*/messages.json)
into the corpus common format. One JSONL record per message.
Schema observed 2026-07-02: {creator:{name,email}, created_date, text, ...}
Date style: "Monday, November 20, 2017 at 3:56:59 PM UTC".
"""
import glob
import json
import os
import re
from datetime import datetime

HOME = os.path.expanduser("~")
SRC = os.path.join(HOME, "twin-corpus/raw/google/extracted/Takeout/Google Chat/Groups")
OUT = os.path.join(HOME, "twin-corpus/normalized/gchat.jsonl")
ME = "you@example.com"


def parse_date(s):
    s = re.sub(r"\s+(UTC|GMT[^ ]*)$", "", s.strip())
    for fmt in ("%A, %B %d, %Y at %I:%M:%S %p", "%A, %B %d, %Y at %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).isoformat()
        except ValueError:
            continue
    return None


def group_name(gdir):
    info = os.path.join(gdir, "group_info.json")
    try:
        d = json.load(open(info, encoding="utf-8"))
        members = [m.get("name", "") for m in d.get("members", [])]
        others = [m for m in members if ME not in m and m]
        return d.get("name") or ", ".join(others) or os.path.basename(gdir)
    except (OSError, json.JSONDecodeError):
        return os.path.basename(gdir)


def main():
    records = []
    for gdir in sorted(glob.glob(os.path.join(SRC, "*"))):
        mpath = os.path.join(gdir, "messages.json")
        if not os.path.isfile(mpath):
            continue
        chat = group_name(gdir)
        data = json.load(open(mpath, encoding="utf-8"))
        for m in data.get("messages", []):
            text = (m.get("text") or "").strip()
            date = parse_date(m.get("created_date", ""))
            if not text or not date:
                continue
            email = m.get("creator", {}).get("email", "")
            records.append({
                "source": "gchat",
                "chat": chat,
                "date": date,
                "who": "me" if email == ME else "them",
                "sender": m.get("creator", {}).get("name", email),
                "text": text,
            })
    records.sort(key=lambda r: r["date"])
    with open(OUT, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    me = sum(1 for r in records if r["who"] == "me")
    print(f"messages: {len(records)}  (me: {me}, them: {len(records) - me})")
    if records:
        print(f"range:    {records[0]['date'][:10]} -> {records[-1]['date'][:10]}")
    print(f"wrote:    {OUT}")


if __name__ == "__main__":
    main()
