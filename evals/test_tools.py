#!/usr/bin/env python3
"""Tool regression tests - deterministic, run by eval.sh on every ship.
Each test exists because a specific production failure occurred (date in comment)."""
import importlib.util, os, sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents/brief/tools")
fails = []

def load(name):
    spec = importlib.util.spec_from_file_location(name, f"{HERE}/{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

# 2026-07-13: ICS 'Z' stripped -> Sam meeting shown 2h early
os.environ.setdefault("TWIN_CALENDAR_ICS_URL", "http://unused.invalid")
cal = load("calendar_read")
got = cal.parse_dt("DTSTART:20260713T170000Z")
want = datetime(2026, 7, 13, 17, 0, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
if got != want:
    fails.append(f"ICS Z-suffix: got {got}, want {want}")
got = cal.parse_dt("DTSTART;TZID=America/New_York:20260713T170000")
want = datetime(2026, 7, 13, 17, 0, tzinfo=ZoneInfo("America/New_York")).astimezone().replace(tzinfo=None)
if got != want:
    fails.append(f"ICS TZID: got {got}, want {want}")
if cal.parse_dt("DTSTART:20260713T170000") != datetime(2026, 7, 13, 17, 0):
    fails.append("ICS floating time should pass through unchanged")

# 2026-07-13: send_email cursor NameError'd for 5 days (missing import) - twin's find
src = open(f"{HERE}/send_email.py").read()
if "from datetime import datetime" not in src:
    fails.append("send_email.py: datetime import missing (cursor will silently fail)")

# 2026-07-08: inbox_read --hours lied (IMAP SINCE is date-granular)
src = open(f"{HERE}/inbox_read.py").read()
if "CUTOFF" not in src or "since_last_brief" not in src:
    fails.append("inbox_read.py: hour-cutoff/cursor logic missing")

if fails:
    print("TOOL TESTS FAILED:")
    [print(" -", f) for f in fails]
    sys.exit(1)
print(f"tool tests: all pass")
