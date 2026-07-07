#!/usr/bin/env python3
"""
inbox_read.py - read-only view of Daniel's Gmail inbox for triage.
IMAP with BODY.PEEK: never marks messages seen, never modifies anything.
Uses the same app password as send_email.py (from ~/.hermes/.env).

Usage: inbox_read.py [--hours 24] [--limit 30]
Output: JSON lines {date, from, subject, snippet, unread}
"""
import argparse
import email
import imaplib
import json
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

ENV = os.path.expanduser("~/.hermes/.env")
if os.path.exists(ENV):
    for line in open(ENV):
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.strip().partition("=")
            os.environ.setdefault(k, v)

ME = os.environ["TWIN_SMTP_ADDRESS"]
PW = os.environ["TWIN_SMTP_APP_PASSWORD"]


def hdr(msg, name):
    try:
        return str(make_header(decode_header(msg.get(name, ""))))
    except Exception:
        return msg.get(name, "")


def snippet(msg, maxlen=200):
    part = msg
    if msg.is_multipart():
        part = next((p for p in msg.walk()
                     if p.get_content_type() == "text/plain"), None)
    if part is None:
        return ""
    try:
        text = (part.get_payload(decode=True) or b"").decode(
            part.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return ""
    return re.sub(r"\s+", " ", text).strip()[:maxlen]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--since-last-brief", action="store_true")
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args()
    CUTOFF = datetime.now().astimezone() - timedelta(hours=args.hours)
    if args.since_last_brief:
        try:
            CUTOFF = datetime.fromisoformat(open(os.path.expanduser("~/.hermes/state/last_brief_sent")).read().strip())
        except Exception:
            pass

    # server-side coarse filter must be at least as wide as the client cutoff,
    # else IMAP censors mail before the precise filter sees it (2026-07-07 review)
    since = min(CUTOFF, datetime.now().astimezone() - timedelta(hours=args.hours)).strftime("%d-%b-%Y")
    with imaplib.IMAP4_SSL("imap.gmail.com") as im:
        im.login(ME, PW)
        im.select("INBOX", readonly=True)          # readonly: belt
        _, data = im.search(None, f'(SINCE "{since}")')
        ids = data[0].split()[-args.limit:]
        for mid in reversed(ids):
            _, msgdata = im.fetch(mid, "(BODY.PEEK[] FLAGS)")  # PEEK: suspenders
            raw = next((p[1] for p in msgdata if isinstance(p, tuple)), None)
            if raw is None:
                continue
            msg = email.message_from_bytes(raw)
            flags = " ".join(str(p) for p in msgdata if isinstance(p, bytes))
            try:
                dt = parsedate_to_datetime(msg.get("Date"))
                date = dt.isoformat()
                # IMAP SINCE is date-granular; enforce the real hour cutoff here
                if dt.timestamp() < CUTOFF.timestamp():
                    continue
            except Exception:
                date = ""
            print(json.dumps({
                "date": date,
                "from": parseaddr(hdr(msg, "From"))[1],
                "from_name": parseaddr(hdr(msg, "From"))[0],
                "subject": hdr(msg, "Subject"),
                "snippet": snippet(msg),
                "unread": "\\Seen" not in flags,
            }, ensure_ascii=False))


if __name__ == "__main__":
    main()
