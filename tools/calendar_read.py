#!/usr/bin/env python3
"""
calendar_read.py - read-only view of Daniel's Google Calendar via its secret
ICS feed (no OAuth, no write capability by construction).

Usage: calendar_read.py [--days 2]
Output: JSON lines {start, end, summary, location} for events in the window.
"""
import argparse
import json
import os
import re
import urllib.request
from datetime import date, datetime, timedelta

ENV = os.path.expanduser("~/.hermes/.env")
if os.path.exists(ENV):
    for line in open(ENV):
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.strip().partition("=")
            os.environ.setdefault(k, v)

ICS_URL = os.environ["TWIN_CALENDAR_ICS_URL"]


def parse_dt(val):
    m = re.match(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2}))?", val)
    if not m:
        return None
    y, mo, d, h, mi, s = m.groups()
    return datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(s or 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2)
    args = ap.parse_args()

    raw = urllib.request.urlopen(ICS_URL, timeout=30).read().decode("utf-8", "replace")
    lines = re.sub(r"\r?\n[ \t]", "", raw).splitlines()   # unfold per RFC 5545

    lo = datetime.combine(date.today(), datetime.min.time())
    hi = lo + timedelta(days=args.days)
    ev, out = None, []
    for line in lines:
        if line.startswith("BEGIN:VEVENT"):
            ev = {}
        elif line.startswith("END:VEVENT") and ev is not None:
            st = ev.get("start")
            if st and lo <= st < hi:
                out.append(ev)
            ev = None
        elif ev is not None:
            if line.startswith("DTSTART"):
                ev["start"] = parse_dt(line.split(":", 1)[-1])
            elif line.startswith("DTEND"):
                ev["end"] = parse_dt(line.split(":", 1)[-1])
            elif line.startswith("SUMMARY"):
                ev["summary"] = line.split(":", 1)[-1].replace("\\,", ",").strip()
            elif line.startswith("LOCATION"):
                ev["location"] = line.split(":", 1)[-1].replace("\\,", ",").strip()

    out.sort(key=lambda e: e["start"])
    for e in out:
        print(json.dumps({
            "start": e["start"].isoformat(),
            "end": e["end"].isoformat() if e.get("end") else "",
            "summary": e.get("summary", ""),
            "location": e.get("location", ""),
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
