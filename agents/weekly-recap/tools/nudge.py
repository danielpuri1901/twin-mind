#!/usr/bin/env python3
"""Weekly-recap NUDGE - Friday ~18:00, deterministic (NO LLM).

Sends Daniel a Telegram with the week's build headlines (from the CHANGELOG) + a reflection
prompt, and records the send time so the 19:30 compose step knows where the capture window
starts. The reflection Daniel types back over the next ~90 min is read from state.db by that
step (role=user, source=telegram, timestamp in [nudge, compose]).

Runs on the box (instance role, box CHANGELOG, TELEGRAM_BOT_TOKEN in ~/.twin-mind/.env).
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Luxembourg")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "shared"))
import telegram_send  # noqa: E402

CHANGELOG = os.path.join(REPO, "docs", "CHANGELOG.md")
STATE = os.path.expanduser("~/.twin-mind/state/weekly-recap-nudge.json")


def week_headlines(days=7, limit=120):
    """One headline per CHANGELOG entry from the last `days` days (deterministic, no LLM).
    `## YYYY-MM-DD - title` gives the title; a bare `## YYYY-MM-DD` gives the first non-empty line below it."""
    cutoff = datetime.now(TZ).date() - timedelta(days=days)
    heads, wait = [], False
    for line in open(CHANGELOG):
        m = re.match(r"^##\s+(\d{4}-\d{2}-\d{2})\s*(?:\([^)]*\))?\s*(?:-\s*(.+))?$", line.strip())
        if m:
            try:
                recent = datetime.strptime(m.group(1), "%Y-%m-%d").date() >= cutoff
            except ValueError:
                recent = False
            wait = recent and not m.group(2)
            if recent and m.group(2):
                heads.append(m.group(2).strip())
        elif wait and line.strip() and not line.startswith("#"):
            heads.append(line.strip())
            wait = False
    return [h if len(h) <= limit else h[:limit - 3].rstrip() + "..." for h in heads]


def build_message():
    heads = week_headlines()
    lines = "\n".join(f"- {h}" for h in heads[:8]) if heads else "- (a quiet build week)"
    return (f"Your week - {datetime.now(TZ).strftime('%b %d')}\n\n"
            f"{lines}\n\n"
            "What shifted for you outside the build this week - work, life, whatever's on your mind? "
            "Reply here with as many messages as you like, and type \"done\" when you're finished. "
            "Then I'll email you the recap.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the message, do NOT send, do NOT record")
    a = ap.parse_args()
    msg = build_message()
    if a.dry_run:
        print("[DRY RUN - not sent]\n" + msg)
    else:
        r = telegram_send.send(msg)
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump({"nudge_ts": time.time(), "sent_ok": r.get("ok")}, open(STATE, "w"))
        try:  # clear last cycle's sent-marker so this nudge's recap can send
            os.remove(os.path.expanduser("~/.twin-mind/state/weekly-recap-sent.txt"))
        except FileNotFoundError:
            pass
        print(f"nudge sent: ok={r.get('ok')} | 'done'-gated window open ({datetime.now(TZ).strftime('%H:%M %Z')})")
