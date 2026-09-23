#!/usr/bin/env python3
"""Weekly learning recap - ONE-SHOT (v0, 2026-07-17, per stepback review).

Deliberately NOT a cron agent yet: no Telegram nudge, no reply-capture, no watchdog, no
idempotency marker - those were the untested, failure-prone parts. This is a single script
you run by hand. It DRY-RUNS to a .txt for you to read; it does NOT send. Promote to a real
agent (agents/weekly-recap/SKILL.md + crons) next week, with tonight's reviewed output as the
first fixture.

Deterministic tier: parse the week's CHANGELOG entries VERBATIM (the grounded source).
LLM composes a 3-section recap, GROUNDED: it may only teach a concept it can tie to a quoted
CHANGELOG line (closes the "concept it taught is ungrounded" hole the reviewer flagged).
Reflection is passed in by hand (--reflection / --reflection-file).

Usage:
  python3 recap.py --changelog-only                 # just the grounded block, no LLM
  python3 recap.py --reflection-file refl.txt        # full dry-run -> recap-<date>.txt
"""
import argparse, os, re, sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Luxembourg")          # box runs in Ireland; Daniel is in Luxembourg - pin it
MODEL = "eu.anthropic.claude-sonnet-4-6"
# .../agents/weekly-recap/tools/recap.py -> repo root is four dirs up
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CHANGELOG = os.path.join(REPO, "docs", "CHANGELOG.md")
CORPUS_DB = os.path.join(os.environ.get("TWIN_CORPUS", os.path.expanduser("~/twin-corpus")), "index", "corpus.db")


def changelog_week(days=7):
    """Verbatim CHANGELOG lines whose '## YYYY-MM-DD' header is within the last `days` days.
    Multiple entries per day and (later)/(evening) suffixes are handled; the bundled
    '## 2026-07-01 and earlier' header parses to its lead date and is correctly excluded."""
    today = datetime.now(TZ).date()
    cutoff = today - timedelta(days=days)
    keep, out = False, []
    for ln in open(CHANGELOG).read().splitlines():
        m = re.match(r"^##\s+(\d{4}-\d{2}-\d{2})", ln)
        if m:
            try:
                keep = datetime.strptime(m.group(1), "%Y-%m-%d").date() >= cutoff
            except ValueError:
                keep = False
            if keep:
                out.append(ln)
            continue
        if keep:
            out.append(ln)
    return "\n".join(out).strip()


def meetings_week(days=7, db_path=None):
    """This week's captured meetings, read from the corpus index (source 'meeting' = Wispr Flow,
    'meeting-summary' = older Granola). One block per meeting: summary first, then transcript
    chunks, truncated per meeting. Only what was actually captured - the recap cannot mirror a
    meeting that was never recorded. Missing index -> '' so the recap still composes."""
    import sqlite3
    path = db_path or CORPUS_DB
    if not os.path.exists(path):
        return ""
    cutoff = (datetime.now(TZ).date() - timedelta(days=days)).isoformat()
    db = sqlite3.connect(path)
    rows = db.execute(
        "SELECT chat, date, text FROM msgs WHERE source IN ('meeting', 'meeting-summary') "
        "AND substr(date, 1, 10) >= ? ORDER BY chat, who != 'summary', rowid", (cutoff,)).fetchall()
    db.close()
    meetings = {}
    for chat, date, text in rows:
        body = re.sub(r"^\[[^\]]*\]\n", "", text or "")  # drop the contextual-embedding header
        meetings.setdefault(chat, (date[:10], []))[1].append(body)
    out = []
    for chat, (day, parts) in sorted(meetings.items(), key=lambda kv: kv[1][0]):
        title = chat[11:].replace("-", " ") if chat[:10] == day else chat
        out.append(f"### MEETING {day} - {title}\n" + "\n".join(parts)[:8000])
    return "\n\n".join(out).strip()


SYS = """You write Daniel's WEEKLY LEARNING RECAP - a Friday email he sends himself. Plain words, short sentences, no em dash (use '-'), no AI vocab (delve, leverage, tapestry, journey, elevate, etc.).

You are given (1) the week's CHANGELOG entries VERBATIM - the record of what he built - and (2) his own reflection.

GROUNDING (hard rule): every claim about what Daniel did MUST trace to a specific CHANGELOG line, and you may ONLY teach a concept if you can tie it to a quoted line. If you cannot ground a concept in a line, leave it out. Do NOT invent work, wins, numbers, or concepts. Do NOT restate a specific count or number unless a CHANGELOG line contains that exact number - if unsure, describe it without the number. TODAY'S DATE is given in the input; use it for the header and never guess the date or weekday. The reflection is Daniel's own words - organize it, never fabricate or extend it.

Write three sections. Keep it a recap, not an essay - all three sections must fit:

1. WHAT YOU BUILT, AND WHAT IT TAUGHT YOU
   The week's arc from the CHANGELOG: what actually shipped, and the concept each thing taught - each tied to a real line. Keep each shipped item to 2-4 sentences. This is the heart; concrete and true, but tight.

WHO YOU MET (include ONLY if MEETINGS are provided in the input):
   For each meeting: who it was and the one or two things that actually came out of it, grounded strictly in the transcript - 2-3 sentences each, no invention. If NO meetings are provided, omit this block entirely and never invent a meeting.

2. MAKE IT STICK
   5-8 of the week's concepts as one-liners, then 3 short recall questions with their answers.

3. YOUR WEEK, IN YOUR WORDS
   Daniel's reflection, lightly organized into his own words. If the reflection is empty, say plainly that it is open and invite him to add it.
"""


def compose(changelog_block, reflection):
    import boto3
    sys.path.insert(0, REPO)
    from shared.bedrock_profiles import route_model
    brt = boto3.client("bedrock-runtime", region_name="eu-west-1")
    today = datetime.now(TZ).strftime("%A, %d %B %Y")  # code owns the date; the model never guesses it
    meetings = meetings_week()
    user = (f"TODAY: {today}. Use this exact date/weekday in the header; do not compute or guess it.\n\n"
            f"THIS WEEK'S CHANGELOG (verbatim - your only grounded source for what he built):\n"
            f"{changelog_block[:12000]}\n\n"
            f"THIS WEEK'S MEETINGS (verbatim transcripts - the ONLY meetings captured; do not invent others):\n"
            f"{meetings or '(no meetings captured this week)'}\n\n"
            f"DANIEL'S REFLECTION (his words - keep them, never invent or extend):\n"
            f"{(reflection or '').strip() or '(none provided)'}")
    r = brt.converse(modelId=route_model(MODEL), system=[{"text": SYS}],
                     messages=[{"role": "user", "content": [{"text": user}]}],
                     inferenceConfig={"maxTokens": 3500, "temperature": 0})
    return next(c["text"] for c in r["output"]["message"]["content"] if "text" in c)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reflection", default="")
    ap.add_argument("--reflection-file", default="")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default="")
    ap.add_argument("--changelog-only", action="store_true", help="print the grounded block, no LLM, no send")
    a = ap.parse_args()

    block = changelog_week(a.days)
    if a.changelog_only:
        print(block or "(no CHANGELOG entries in the window)")
        sys.exit(0)

    reflection = a.reflection or (open(a.reflection_file).read() if a.reflection_file else "")
    recap = compose(block, reflection)
    out = a.out or os.path.join(REPO, f"recap-{datetime.now(TZ).date()}.txt")
    open(out, "w").write(recap)
    print(f"DRY RUN - wrote recap to {out} (NOT sent).\n\n{recap}")
