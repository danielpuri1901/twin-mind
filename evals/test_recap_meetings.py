#!/usr/bin/env python3
"""Fixtures for weekly-recap's meeting block (2026-09-23): meetings come from the corpus index,
not from a folder of files, so any ingester (Wispr Flow now, Granola before) feeds the recap.
Deterministic, free, no network: builds a throwaway corpus.db with the production msgs schema.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents", "weekly-recap", "tools"))
import recap as R

FAILS = []


def check(name, cond):
    if not cond:
        FAILS.append(name)
        print(f"  FAIL  {name}")


today = datetime.now(R.TZ).date()
recent, old = (today - timedelta(days=2)).isoformat(), (today - timedelta(days=20)).isoformat()
db_path = os.path.join(tempfile.mkdtemp(), "corpus.db")
db = sqlite3.connect(db_path)
db.execute("CREATE VIRTUAL TABLE msgs USING fts5(source, chat, date, who, sender, text)")
rows = [
    ("meeting", f"{recent}-vendor-onboarding", f"{recent}T14:59:18", "mixed", "", f"[{recent}-vendor-onboarding · {recent}]\nAlex: case starts"),
    ("meeting", f"{recent}-vendor-onboarding", f"{recent}T14:59:18", "summary", "", f"[{recent}-vendor-onboarding · {recent}]\nVendor onboarding\nMock onboarding case."),
    ("meeting-summary", f"{recent}-old-granola", f"{recent}T09:00:00", "summary", "", f"[{recent}-old-granola · {recent}]\nGranola summary text."),
    ("meeting", f"{old}-stale", f"{old}T10:00:00", "summary", "", "too old"),
    ("imessage", f"{recent}-chat", f"{recent}T10:00:00", "mixed", "", "not a meeting"),
]
db.executemany("INSERT INTO msgs VALUES (?,?,?,?,?,?)", rows)
db.commit(); db.close()

out = R.meetings_week(db_path=db_path)
check("recent Wispr meeting included", "Mock onboarding case." in out and "Alex: case starts" in out)
check("older Granola summaries still count", "Granola summary text." in out)
check("meetings older than 7 days excluded", "too old" not in out)
check("non-meeting sources excluded", "not a meeting" not in out)
check("summary comes before transcript", out.index("Mock onboarding case.") < out.index("Alex: case starts"))
check("context header lines stripped", f"[{recent}-vendor-onboarding" not in out)
check("one heading per meeting", out.count("### MEETING") == 2)
check("missing index -> empty, never a crash", R.meetings_week(db_path="/nonexistent/corpus.db") == "")

if FAILS:
    print(f"RECAP MEETINGS: {len(FAILS)} FAILED")
    sys.exit(1)
print("RECAP MEETINGS: all 8 fixtures pass")
