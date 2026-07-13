#!/usr/bin/env python3
"""Daily brief watchdog (07:50). Deterministic checks on today's brief.
Watchdog pattern: prints NOTHING when all is well; any output = a failure
report (scheduled via hermes cron --no-agent --deliver telegram, so output
lands on Daniel's phone and silence stays silent).
Checks: (1) brief arrived today, (2) subject matches contract, (3) all six
section headers present, (4) coverage line present, (5) no em dash,
(6) heartbeat metric emitted today."""
import email, imaplib, os, re, subprocess, sys
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header

for line in open(os.path.expanduser("~/.hermes/.env")):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)

fails = []
today = datetime.now().astimezone()
HEADERS = ["1. NEEDS YOU TODAY", "2. TODAY", "3. AI ADVANCEMENTS",
           "4. ONE TECHNICAL THING", "5. COACH", "6. OPEN LOOPS"]

try:
    with imaplib.IMAP4_SSL("imap.gmail.com") as im:
        im.login(os.environ["TWIN_SMTP_ADDRESS"], os.environ["TWIN_SMTP_APP_PASSWORD"])
        im.select('"[Gmail]/All Mail"', readonly=True)
        since = (today - timedelta(days=1)).strftime("%d-%b-%Y")
        ok, d = im.search(None, f'(SINCE "{since}" SUBJECT "Morning brief")')
        msg = body = None
        for i in reversed(d[0].split()):
            ok, raw = im.fetch(i, "(BODY.PEEK[])")
            m = email.message_from_bytes(raw[0][1])
            dt = email.utils.parsedate_to_datetime(m.get("Date"))
            if dt.astimezone(today.tzinfo).date() == today.date():
                msg = m
                for part in m.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", "replace")
                        break
                break
        if msg is None:
            fails.append("NO BRIEF ARRIVED today (checked All Mail)")
        else:
            subj = str(make_header(decode_header(msg.get("Subject", ""))))
            if not re.match(r"^Morning brief - [A-Z][a-z]{2} \d{1,2} [A-Z][a-z]{2}$", subj):
                fails.append(f"subject breaks contract: '{subj}'")
            missing = [h for h in HEADERS if h not in (body or "")]
            if missing:
                fails.append(f"missing sections: {', '.join(missing)}")
            if not re.search(r"Triaged \d+ messages since", body or ""):
                fails.append("coverage line missing")
            if "—" in (body or "") + subj:
                fails.append("em dash found (Daniel's canon)")
except Exception as e:
    fails.append(f"inbox check errored: {e}")

try:
    r = subprocess.run(
        ["aws", "cloudwatch", "get-metric-statistics", "--namespace", "TwinMind",
         "--metric-name", "BriefSent", "--region", "eu-west-1",
         "--start-time", (datetime.now(timezone.utc) - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "--end-time", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "--period", "43200", "--statistics", "Sum",
         "--query", "Datapoints[0].Sum", "--output", "text"],
        capture_output=True, text=True, timeout=30)
    if "1" not in r.stdout:
        fails.append(f"no heartbeat in last 12h (metric said: {r.stdout.strip()!r})")
except Exception as e:
    fails.append(f"heartbeat check errored: {e}")

# 2026-07-13: the twin once self-authored a skill. Governed skills are symlinks into
# super-project; anything else (except Hermes bundled dirs) is unauthorized.
try:
    skills_dir = os.path.expanduser("~/.hermes/skills")
    if os.path.isdir(skills_dir):
        rogue = [d for d in os.listdir(skills_dir)
                 if not os.path.islink(os.path.join(skills_dir, d)) and not d.startswith(".")]
        governed_or_bundled = {"apple","autonomous-ai-agents","computer-use","creative","data-science",
            "dogfood","email","github","media","mlops","note-taking","productivity","research",
            "smart-home","social-media","software-development","yuanbao"}
        rogue = [d for d in rogue if d not in governed_or_bundled]
        if rogue:
            fails.append(f"UNAUTHORIZED twin-authored skill(s) appeared: {rogue}")
except Exception as e:
    fails.append(f"skill-guard errored: {e}")

if fails:
    print("BRIEF WATCHDOG - problems this morning:")
    for f in fails:
        print(f"- {f}")
    sys.exit(1)
