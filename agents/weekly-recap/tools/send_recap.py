#!/usr/bin/env python3
"""Weekly-recap COMPOSE + SEND - fires on Daniel's "done" signal (HITL gate), not a fixed timer.

The nudge asks Daniel to reply with his reflection and say "done" when finished. This script is
polled (every couple of minutes): it reads his Telegram messages since the nudge; when it sees a
"done" message it takes everything BEFORE it as the reflection, composes the recap, and emails it
- once. If no "done" arrives within the cutoff it sends with whatever he wrote (fallback). A
sent-marker makes it idempotent so the poll never double-sends.

Runs on the box: instance role for Bedrock, local state.db, the brief's recipient-locked send_email.
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import recap as R  # reuse changelog_week, meetings_week, compose

TZ = ZoneInfo("Europe/Luxembourg")
STATEDB = os.path.expanduser("~/.hermes/state.db")
NUDGE_STATE = os.path.expanduser("~/.hermes/state/weekly-recap-nudge.json")
SENT_MARKER = os.path.expanduser("~/.hermes/state/weekly-recap-sent.txt")
SEND_EMAIL = os.path.normpath(os.path.join(HERE, "..", "..", "brief", "tools", "send_email.py"))
CUTOFF_MIN = 90
DONE = {"done", "/done", "send", "send it", "sent", "finished", "im done", "i'm done", "im finished",
        "thats it", "that's it", "that is it", "end", "go", "ok done", "okay done"}


def is_done(m):
    """A done-signal: an exact synonym, or a SHORT message that says done/finished (so a natural
    'alright i'm done w the reflection' counts, but a long paragraph that mentions 'done' does not)."""
    s = m.strip().lower()
    if s in DONE:
        return True
    return len(s) <= 60 and re.search(r"\b(done|finished)\b", s) is not None


def messages_since(nudge_ts):
    if not os.path.exists(STATEDB) or not nudge_ts:
        return []
    db = sqlite3.connect(STATEDB)
    return [r[0] for r in db.execute(
        "SELECT m.content FROM messages m JOIN sessions s ON m.session_id = s.id "
        "WHERE s.source = 'telegram' AND m.role = 'user' AND m.timestamp >= ? "
        "AND COALESCE(m.content, '') != '' ORDER BY m.timestamp", (float(nudge_ts),)).fetchall()]


def week_key():
    return datetime.now(TZ).strftime("%Y-W%V")


def already_sent():
    try:
        return open(SENT_MARKER).read().strip() == week_key()
    except Exception:
        return False


def build_recap():
    """(recap_text|None, reflection, ready, reason). Ready only when Daniel says 'done' or the cutoff passes."""
    try:
        nudge_ts = json.load(open(NUDGE_STATE)).get("nudge_ts", 0)
    except Exception:
        return None, "", False, "no nudge sent yet"
    if (time.time() - nudge_ts) > 12 * 3600:
        # stale nudge from a PREVIOUS week (e.g. the poll fired before this week's nudge wrote
        # its timestamp) - without this guard the 90-min cutoff would "pass" instantly and send
        # a week of Telegram messages as the reflection. Never compose off an old nudge.
        return None, "", False, "nudge_ts is stale (>12h) - waiting for this week's nudge"
    msgs = messages_since(nudge_ts)
    done_i = next((i for i, m in enumerate(msgs) if is_done(m)), None)
    if done_i is not None:
        reflection = "\n".join(msgs[:done_i]).strip()
        ready, reason = True, "you said 'done'"
    elif nudge_ts and (time.time() - nudge_ts) > CUTOFF_MIN * 60:
        reflection = "\n".join(msgs).strip()
        ready, reason = True, f"{CUTOFF_MIN}-min cutoff (no 'done')"
    else:
        return None, "\n".join(msgs), False, "waiting for you to say 'done'"
    return R.compose(R.changelog_week(), reflection), reflection, ready, reason


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="compose + print if ready, do NOT send")
    a = ap.parse_args()

    if already_sent() and not a.dry_run:
        print(f"already sent this week ({week_key()}); poll no-ops")
        sys.exit(0)

    recap, reflection, ready, reason = build_recap()
    if not ready:
        print(f"NOT sending - {reason} ({len(reflection)} chars captured so far)")
        sys.exit(0)

    subject = "Weekly recap - " + datetime.now(TZ).strftime("week of %b %d")
    print(f"READY: {reason} | reflection = {len(reflection)} chars")
    if a.dry_run:
        print(f"[DRY RUN - not sent]\nSubject: {subject}\n\n{recap}")
    else:
        r = subprocess.run(["python3", SEND_EMAIL, subject], input=recap, capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
        os.makedirs(os.path.dirname(SENT_MARKER), exist_ok=True)
        open(SENT_MARKER, "w").write(week_key())
        print("sent-marker written; poll will now no-op")
