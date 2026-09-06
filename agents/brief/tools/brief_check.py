#!/usr/bin/env python3
"""Daily brief watchdog (07:50). Deterministic checks on today's brief.
Watchdog pattern: prints NOTHING when all is well; any output = a failure
report (scheduled via hermes cron --no-agent --deliver telegram, so output
lands on Daniel's phone and silence stays silent).

2026-07-15: the checks had DRIFTED from the brief (demanded numbered headers +
abbreviated month while the brief renders unnumbered headers + full names), so it
cried wolf every morning. Fixed to match reality, and the pure format checks are
now `format_fails()` - tested by evals/test_brief_check.py against a known-good
brief so the watchdog and the brief can never silently drift apart again.
Checks: brief arrived, subject+date, required sections, weather, dividers, coverage,
no em dash, optional quiz answer, calendar payload cross-check, heartbeat, skill-guard."""
import email, imaplib, os, re, subprocess, sys
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header

# The technical section is optional when no fresh project lesson survives its novelty gate.
REQUIRED_SECTIONS = ["NEEDS YOU TODAY", "TODAY", "AI ADVANCEMENTS", "COACH"]


def format_fails(subj, body, today):
    """Pure format checks on a brief. Robust to cosmetic variation (numbered or
    unnumbered headers, abbreviated or full weekday/month) - flags only real defects.
    Tested by evals/test_brief_check.py; that test is why this stays a pure function."""
    body = body or ""
    subj = (subj or "").strip()
    fails = []
    # subject: 'Morning brief - <Weekday> <D> <Month>', abbreviated OR full names
    if not re.match(r"^Morning brief - [A-Za-z]{3,9} \d{1,2} [A-Za-z]{3,9}$", subj):
        fails.append(f"subject breaks contract: '{subj}'")
    # the date must be TODAY: day-of-month + month + weekday, each abbreviated OR full
    day = str(today.day)
    ok_date = (re.search(rf"\b{day}\b", subj)
               and (today.strftime("%B") in subj or today.strftime("%b") in subj)
               and (today.strftime("%A") in subj or today.strftime("%a") in subj))
    if not ok_date:
        fails.append(f"subject date wrong: '{subj}', expected {today.strftime('%A %-d %B')}")
    # required sections present as header lines (with or without a leading number)
    missing = [s for s in REQUIRED_SECTIONS
               if not re.search(rf"^(\d+\.\s*)?{re.escape(s)}\s*$", body, re.M)]
    if missing:
        fails.append(f"missing sections: {', '.join(missing)}")
    # weather line present. 'unavailable' is acceptable (external API, brief handled it) -
    # only a truly absent weather line fails.
    if not re.search(r"°C|rain chance|Weather:|Luxembourg", body, re.I):
        fails.append("weather line missing")
    if body.count("━" * 10) < 8:
        fails.append("section divider lines (━) missing")
    if not re.search(r"(Triaged|Reviewed) \d+ messages since", body):
        fails.append("coverage line missing")
    if "—" in body + subj:
        fails.append("em dash found (Daniel's canon)")
    if re.search(r"^(\d+\.\s*)?ONE TECHNICAL THING\s*$", body, re.M) and "Answer:" not in body:
        fails.append("quiz has no Answer: line")
    return fails


def main():
    for line in open(os.path.expanduser("~/.hermes/.env")):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.strip().split("=", 1)
            os.environ.setdefault(k, v)

    fails = []
    today = datetime.now().astimezone()
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
                fails += format_fails(subj, body, today)
                # covered-topic repeat (reads the state file, so it lives here not in format_fails)
                try:
                    cov = open(os.path.expanduser("~/.hermes/state/digest-covered.txt")).read()
                    first_words = [l.split("(")[0].strip()[:25] for l in cov.splitlines() if len(l) > 15]
                    hits = [t for t in first_words if t and t.lower() in (body or "").lower()]
                    if hits:
                        fails.append(f"covered topic repeated: {hits[:2]}")
                except Exception:
                    pass
                # PAYLOAD cross-check (stepback #5): every calendar event time must appear in the body
                try:
                    import json as _json
                    cal = subprocess.run(["python3", os.path.expanduser(
                        "~/super-project/agents/brief/tools/calendar_read.py"), "--days", "1"],
                        capture_output=True, text=True, timeout=60)
                    for ev in (_json.loads(l) for l in cal.stdout.splitlines() if l.strip()):
                        hhmm = ev["start"][11:16]
                        if ev.get("summary") and hhmm and hhmm not in (body or ""):
                            fails.append(f"calendar payload mismatch: event '{ev['summary'][:30]}' "
                                         f"starts {hhmm}, brief does not contain that time")
                except Exception as e:
                    fails.append(f"calendar cross-check errored: {e}")
    except Exception as e:
        fails.append(f"inbox check errored: {e}")

    # heartbeat: BriefSent metric emitted in the last 12h
    try:
        r = subprocess.run(
            ["aws", "cloudwatch", "get-metric-statistics", "--namespace", "TwinMind",
             "--metric-name", "BriefSent", "--region", "eu-west-1",
             "--start-time", (datetime.now(timezone.utc) - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "--end-time", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "--period", "43200", "--statistics", "Sum",
             "--query", "Datapoints[0].Sum", "--output", "text"],
            capture_output=True, text=True, timeout=30)
        try:
            hb = float(r.stdout.strip())
        except ValueError:
            hb = 0.0
        if hb < 1:
            fails.append(f"no heartbeat in last 12h (metric said: {r.stdout.strip()!r})")
    except Exception as e:
        fails.append(f"heartbeat check errored: {e}")

    # skill-guard: catch the twin self-authoring a skill (the 2026-07-13 incident).
    # Our governed skills are symlinks. The gateway's bundled skills are category dirs
    # holding a DESCRIPTION.md (no SKILL.md). A twin-authored skill has a top-level
    # SKILL.md - that is the rogue signal (robust to the bundled set changing).
    try:
        skills_dir = os.path.expanduser("~/.hermes/skills")
        if os.path.isdir(skills_dir):
            rogue = [d for d in os.listdir(skills_dir)
                     if not os.path.islink(os.path.join(skills_dir, d))
                     and not d.startswith(".")
                     and os.path.exists(os.path.join(skills_dir, d, "SKILL.md"))]
            if rogue:
                fails.append(f"UNAUTHORIZED twin-authored skill(s) appeared: {rogue}")
    except Exception as e:
        fails.append(f"skill-guard errored: {e}")

    # watch the watchdog: emit WatchdogRan so a dead-man alarm covers checker death
    try:
        subprocess.run(["aws", "cloudwatch", "put-metric-data", "--namespace", "TwinMind",
                        "--metric-name", "WatchdogRan", "--value", "1", "--region", "eu-west-1"],
                       capture_output=True, timeout=30)
    except Exception:
        pass

    if fails:
        print("BRIEF WATCHDOG - problems this morning:")
        for f in fails:
            print(f"- {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
