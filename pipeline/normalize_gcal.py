#!/usr/bin/env python3
"""
normalize_gcal.py - Google Calendar .ics -> common format.
One record per event: {source: gcal, date, who: me, chat: calendar, text: summary (+location)}.
Minimal .ics parsing (DTSTART/SUMMARY/LOCATION), no external deps.
"""
import json
import os
import re

SRC = os.path.expanduser(
    "~/twin-corpus/raw/google/extracted/Takeout/Calendar/you@example.com.ics")
OUT = os.path.expanduser("~/twin-corpus/normalized/gcal.jsonl")


def iso(dt):
    m = re.match(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2}))?", dt)
    if not m:
        return None
    y, mo, d, h, mi, s = m.groups()
    return f"{y}-{mo}-{d}T{h or '00'}:{mi or '00'}:{s or '00'}"


def main():
    records, ev = [], None
    # unfold continuation lines per RFC 5545
    raw = open(SRC, encoding="utf-8", errors="replace").read()
    lines = re.sub(r"\r?\n[ \t]", "", raw).splitlines()
    for line in lines:
        if line.startswith("BEGIN:VEVENT"):
            ev = {}
        elif line.startswith("END:VEVENT") and ev is not None:
            if ev.get("date") and ev.get("summary"):
                text = ev["summary"] + (f" @ {ev['loc']}" if ev.get("loc") else "")
                records.append({"source": "gcal", "chat": "calendar",
                                "date": ev["date"], "who": "me", "sender": "calendar",
                                "text": text})
            ev = None
        elif ev is not None:
            if line.startswith("DTSTART"):
                ev["date"] = iso(line.split(":", 1)[-1])
            elif line.startswith("SUMMARY"):
                ev["summary"] = line.split(":", 1)[-1].replace("\\,", ",").strip()
            elif line.startswith("LOCATION"):
                ev["loc"] = line.split(":", 1)[-1].replace("\\,", ",").strip()

    records.sort(key=lambda r: r["date"])
    with open(OUT, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"events: {len(records)}", end="  ")
    if records:
        print(f"range: {records[0]['date'][:10]} -> {records[-1]['date'][:10]}", end="  ")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
