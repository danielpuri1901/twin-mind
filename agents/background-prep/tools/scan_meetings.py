#!/usr/bin/env python3
"""background-prep poller (spec 2026-07-14 + stepback fixes).
Runs every 15 min from a systemd timer. Deterministic tier:
  scan ICS 24h ahead -> scope filter (any ATTENDEE outside personal circle, excluding
  Daniel, OR a video link in DESCRIPTION) -> idempotent catch-up trigger:
  any qualifying meeting starting within 75 min with no delivered prep and no live
  claim gets its dossier composed and sent here (claim = 20-min lease, not a tombstone).
stdout IS a Telegram message (telegram_send.py --run): print only failures. The 21:00 goal
question and the "prep scheduled" line were removed 2026-09-23 - they read as a second, early prep.
State: ~/.twin-mind/state/prep-state.json  {key: {status, ts, start}}  key = UID|occurrence-start.
Heartbeat: PrepPollerRan metric (its own dead-man watches the watcher).
Silent when healthy; prints only problems (watchdog pattern).
"""
import json, os, re, subprocess, sys, urllib.request
from datetime import datetime, timedelta, timezone

STATE = os.path.expanduser("~/.twin-mind/state/prep-state.json")
CIRCLE = os.path.expanduser("~/.twin-mind/state/personal_circle.txt")
for line in open(os.path.expanduser("~/.twin-mind/.env")):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)
ME = os.environ.get("TWIN_SMTP_ADDRESS", "").lower()


def local_now():
    return datetime.now().astimezone()


def parse_dt(prop_line):
    """Same three RFC 5545 forms as calendar_read (the Jul-13 tz lesson lives here too)."""
    params, _, val = prop_line.partition(":")
    if "VALUE=DATE" in params and "T" not in val:
        return None  # all-day event: excluded by spec (fixture: allday)
    m = re.match(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})", val)
    if not m:
        return None
    dt = datetime(*map(int, m.groups()))
    if val.rstrip().endswith("Z"):
        return dt.replace(tzinfo=timezone.utc).astimezone()
    tzid = re.search(r"TZID=([^;:]+)", params)
    if tzid:
        try:
            from zoneinfo import ZoneInfo
            return dt.replace(tzinfo=ZoneInfo(tzid.group(1))).astimezone()
        except Exception:
            pass
    return dt.replace(tzinfo=local_now().tzinfo)


def remember_name(ev, line, address):
    """Keep the CN display name of a party; the composer uses it to name who Daniel is meeting."""
    m = re.search(r'CN="?([^";:]+)', line)
    if m:
        ev.setdefault("names", {})[address] = m.group(1).strip()


def parse_events(ics):
    """Unfold and extract what the scope filter needs. Returns list of dicts."""
    lines = re.sub(r"\r?\n[ \t]", "", ics).splitlines()
    evs, ev = [], None
    for line in lines:
        if line.startswith("BEGIN:VEVENT"):
            ev = {"attendees": []}
        elif line.startswith("END:VEVENT") and ev is not None:
            evs.append(ev); ev = None
        elif ev is not None:
            if line.startswith("DTSTART"):
                ev["start"] = parse_dt(line)
            elif line.startswith("UID"):
                ev["uid"] = line.split(":", 1)[-1].strip()
            elif line.startswith("SUMMARY"):
                ev["summary"] = line.split(":", 1)[-1].strip()
            elif line.startswith("STATUS"):
                ev["status"] = line.split(":", 1)[-1].strip()
            elif line.startswith("ORGANIZER"):
                m = re.search(r"mailto:([^\s>]+)", line, re.I)
                if m:
                    ev["organizer"] = m.group(1).lower()
                    remember_name(ev, line, ev["organizer"])
            elif line.startswith("ATTENDEE"):
                m = re.search(r"mailto:([^\s>]+)", line, re.I)
                if m:
                    ev["attendees"].append(m.group(1).lower())
                    remember_name(ev, line, m.group(1).lower())
            elif line.startswith("DESCRIPTION"):
                ev["description"] = line.split(":", 1)[-1][:500]
            elif line.startswith(("LOCATION", "X-GOOGLE-CONFERENCE")):
                ev["links"] = ev.get("links", "") + " " + line.split(":", 1)[-1][:200]
    return evs


def circle():
    try:
        return {l.strip().lower() for l in open(CIRCLE) if l.strip() and not l.startswith("#")}
    except FileNotFoundError:
        return set()


def qualifies(ev, circ):
    """Daniel's A+B rule: any counterpart outside the personal circle (excluding Daniel),
    OR a video link anywhere in the invite. Cancelled and all-day events never qualify.
    2026-07-14 scope replay on the REAL feed caught two gaps hand fixtures missed:
    recruiters often appear as ORGANIZER only (never ATTENDEE), and Google puts the
    Meet link in X-GOOGLE-CONFERENCE/LOCATION, not DESCRIPTION. Both count now."""
    if ev.get("status") == "CANCELLED" or not ev.get("start"):
        return False
    others = [a for a in ev.get("attendees", []) if a and a != ME]
    if ev.get("organizer") and ev["organizer"] != ME:
        others.append(ev["organizer"])
    external = [a for a in others if a not in circ]
    haystack = (ev.get("description", "") or "") + " " + (ev.get("links", "") or "")
    has_link = bool(re.search(r"(meet\.google|teams\.microsoft|zoom\.us)", haystack))
    return bool(external) or has_link


def dedupe(evs):
    """Same start + same video link = one meeting mirrored across invites (seen in the real
    feed 2026-07-14: 'Interview with Growth Protocol' + 'First Round Interview', one call).
    Keep the first; never send two dossiers for one meeting."""
    seen, out = set(), []
    for ev in evs:
        m = re.search(r"https?://\S+", (ev.get("links", "") or "") + " " + (ev.get("description", "") or ""))
        sig = (ev.get("start"), m.group(0).rstrip("\\n .,")) if m else None
        if sig and sig in seen:
            continue
        if sig:
            seen.add(sig)
        out.append(ev)
    return out


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, "w"), indent=1)


def key_of(ev):
    return f"{ev.get('uid','?')}|{ev['start'].isoformat()}"


def due(ev, st, now):
    """Idempotent catch-up: within 75 min, not delivered, no LIVE claim (20-min lease)."""
    delta = (ev["start"] - now).total_seconds() / 60
    if not (-1 <= delta <= 75):
        return False
    rec = st.get(key_of(ev), {})
    if rec.get("status") == "delivered":
        return False
    if rec.get("status") == "claimed":
        claimed_at = datetime.fromisoformat(rec["ts"])
        if (now - claimed_at).total_seconds() < 20 * 60:
            return False  # live lease
    return True


# interview signals: recruiters/ATS domains + title words. Deterministic so the CANDIDATE frame
# holds even with zero corpus history (Daniel: goal is "impossible to infer" for cold interviews).
INTERVIEW_DOMAINS = ("greenhouse.io", "lever.co", "ashbyhq.com", "gem.com", "hire.lever.co",
                     "us.greenhouse-mail.io", "myworkday.com", "smartrecruiters.com")
INTERVIEW_WORDS = re.compile(r"\b(interview|take[\s-]?home|phone screen|onsite|on-site|"
                             r"peer interview|final round|hiring|recruiter screen|loop)\b", re.I)


def is_interview(ev):
    if INTERVIEW_WORDS.search(ev.get("summary", "") or ""):
        return True
    parties = ev.get("attendees", []) + [ev.get("organizer", "")]
    return any(any(d in (p or "") for d in INTERVIEW_DOMAINS) for p in parties)


def run_prep(ev, st, now):
    """Claim, compose and send one dossier. Only a dossier that reached Daniel counts as delivered;
    any failure is reported and the next poll retries. The composer is imported here so the poller's
    scope logic stays stdlib-only."""
    key = key_of(ev)
    goal = st.get(key, {}).get("goal", "")
    st[key] = {"status": "claimed", "ts": now.isoformat(), "start": ev["start"].isoformat()}
    save_state(st)
    prep_event = dict(ev, counterparts=sorted({a for a in ev.get("attendees", []) + [ev.get("organizer", "")]
                                               if a and a != ME}))
    try:
        import compose_prep
        compose_prep.deliver(prep_event, goal, is_interview(ev))
    except Exception as exc:
        st[key] = {"status": "failed", "ts": now.isoformat(), "start": ev["start"].isoformat(),
                   "err": f"{type(exc).__name__}: {exc}"[:200]}
        save_state(st)
        print(f"PREP FAILED for {ev.get('summary')}: {type(exc).__name__}: {str(exc)[:150]}")
        return
    st[key] = {"status": "delivered", "ts": now.isoformat(), "start": ev["start"].isoformat()}
    save_state(st)


def heartbeat():
    try:
        subprocess.run(["aws", "cloudwatch", "put-metric-data", "--namespace", "TwinMind",
                        "--metric-name", "PrepPollerRan", "--value", "1", "--region", "eu-west-1"],
                       capture_output=True, timeout=30)
    except Exception:
        pass


def main():
    now = local_now()
    ics = urllib.request.urlopen(os.environ["TWIN_CALENDAR_ICS_URL"], timeout=30).read().decode("utf-8", "replace")
    evs = dedupe([e for e in parse_events(ics)
                  if e.get("start") and now - timedelta(hours=1) < e["start"] < now + timedelta(hours=26)])
    circ = circle()
    st = load_state()
    for ev in evs:
        if qualifies(ev, circ) and due(ev, st, now):
            run_prep(ev, st, now)
    heartbeat()


if __name__ == "__main__":
    main()
