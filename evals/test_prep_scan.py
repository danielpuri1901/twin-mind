#!/usr/bin/env python3
"""Calendar-physics fixtures for background-prep's poller (in the gate from birth, spec fix #7).
Deterministic, free, no network: feeds hand-built ICS + state to scan_meetings functions.
Every fixture is a way calendars actually broke or could break: tz forms, all-day,
cancelled, circle filter, video-link rule, lease expiry, delivered idempotence.
"""
import json, os, sys, tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents", "background-prep", "tools"))
os.environ.setdefault("TWIN_SMTP_ADDRESS", "danielpuri1901@gmail.com")
import scan_meetings as sm

FAILS = []


def check(name, cond):
    if not cond:
        FAILS.append(name)
        print(f"  FAIL  {name}")


def ics_event(uid, dtstart, attendees=(), desc="", status="", summary="Test"):
    a = "".join(f"ATTENDEE;CN=x:mailto:{m}\n" for m in attendees)
    s = f"STATUS:{status}\n" if status else ""
    d = f"DESCRIPTION:{desc}\n" if desc else ""
    return (f"BEGIN:VEVENT\nUID:{uid}\nDTSTART{dtstart}\nSUMMARY:{summary}\n{a}{s}{d}END:VEVENT\n")


ME = "danielpuri1901@gmail.com"
now = sm.local_now().replace(minute=0, second=0, microsecond=0)
in1h_utc = (now + timedelta(hours=1)).astimezone(timezone.utc).strftime(":%Y%m%dT%H%M%SZ")
in1h_tzid = ";TZID=Europe/Luxembourg" + (now + timedelta(hours=1)).strftime(":%Y%m%dT%H%M%S")

# --- timezone forms: Z-suffix and TZID must land on the same wall clock (the Jul-13 Sam bug) ---
evs = sm.parse_events("BEGIN:VCALENDAR\n" + ics_event("z1", in1h_utc) + ics_event("t1", in1h_tzid) + "END:VCALENDAR")
check("tz: Z and TZID same instant", abs((evs[0]["start"] - evs[1]["start"]).total_seconds()) < 1)

# --- all-day excluded (VALUE=DATE) ---
evs = sm.parse_events(ics_event("ad", ";VALUE=DATE:20260715", attendees=["x@corp.com"]))
check("all-day never qualifies", not sm.qualifies(evs[0], set()))

# --- cancelled suppressed ---
evs = sm.parse_events(ics_event("c1", in1h_utc, attendees=["x@corp.com"], status="CANCELLED"))
check("cancelled never qualifies", not sm.qualifies(evs[0], set()))

# --- scope filter: circle member alone = personal; outsider = qualifies; Daniel never counts ---
circ = {"mom@family.com"}
only_circle = sm.parse_events(ics_event("p1", in1h_utc, attendees=[ME, "mom@family.com"]))[0]
outsider = sm.parse_events(ics_event("p2", in1h_utc, attendees=[ME, "recruiter@corp.com"]))[0]
solo = sm.parse_events(ics_event("p3", in1h_utc, attendees=[ME]))[0]
check("circle-only meeting is personal", not sm.qualifies(only_circle, circ))
check("outside-circle attendee qualifies", sm.qualifies(outsider, circ))
check("Daniel alone does not qualify", not sm.qualifies(solo, circ))

# --- video-link rule: no attendees but a Meet link still qualifies ---
link = sm.parse_events(ics_event("v1", in1h_utc, desc="join https://meet.google.com/abc-defg"))[0]
check("video link qualifies", sm.qualifies(link, circ))

# --- unfolding: folded ATTENDEE lines (RFC 5545 continuation) still parsed ---
folded = "BEGIN:VEVENT\nUID:f1\nDTSTART" + in1h_utc + "\nATTENDEE;CN=Long Person Name With A Very\n Long Parameter:mailto:folded@corp.com\nEND:VEVENT\n"
check("folded attendee parsed", sm.parse_events(folded)[0]["attendees"] == ["folded@corp.com"])

# --- due(): window, delivered idempotence, live lease, expired lease (the catch-up core) ---
ev = {"uid": "d1", "start": now + timedelta(minutes=60)}
k = sm.key_of(ev)
check("in window, no state -> due", sm.due(ev, {}, now))
check("delivered -> never again", not sm.due(ev, {k: {"status": "delivered", "ts": now.isoformat()}}, now))
check("live claim (5 min old) -> wait", not sm.due(ev, {k: {"status": "claimed", "ts": (now - timedelta(minutes=5)).isoformat()}}, now))
check("stale claim (25 min old) -> retry", sm.due(ev, {k: {"status": "claimed", "ts": (now - timedelta(minutes=25)).isoformat()}}, now))
check("failed -> retry", sm.due(ev, {k: {"status": "failed", "ts": now.isoformat()}}, now))
far = {"uid": "d2", "start": now + timedelta(hours=5)}
past = {"uid": "d3", "start": now - timedelta(minutes=30)}
check("outside 75 min -> not due", not sm.due(far, {}, now))
check("already started -> not due", not sm.due(past, {}, now))

# --- 2026-07-14 scope-replay catches (real prod bugs found pre-prod, Growth Protocol) ---
# recruiter as ORGANIZER only, Daniel the sole attendee
org_only = ("BEGIN:VEVENT\nUID:o1\nDTSTART" + in1h_utc + "\nSUMMARY:Interview\n"
            "ORGANIZER;CN=r:mailto:recruiter@growthprotocol.ai\n"
            f"ATTENDEE;CN=d:mailto:{ME}\nEND:VEVENT\n")
check("external organizer-only qualifies", sm.qualifies(sm.parse_events(org_only)[0], circ))
# Meet link only in LOCATION / X-GOOGLE-CONFERENCE, DESCRIPTION is boilerplate HTML
loc_link = ("BEGIN:VEVENT\nUID:o2\nDTSTART" + in1h_utc + "\nSUMMARY:First Round\n"
            "DESCRIPTION:<p>AI notetaker notice</p>\n"
            "LOCATION:https://meet.google.com/sea-yqgb-cbw\nEND:VEVENT\n")
conf_link = ("BEGIN:VEVENT\nUID:o3\nDTSTART" + in1h_utc + "\nSUMMARY:Chat\n"
             "X-GOOGLE-CONFERENCE:https://meet.google.com/axw-cgsu-skb\nEND:VEVENT\n")
check("link in LOCATION qualifies", sm.qualifies(sm.parse_events(loc_link)[0], circ))
check("link in X-GOOGLE-CONFERENCE qualifies", sm.qualifies(sm.parse_events(conf_link)[0], circ))
# Daniel as organizer of a circle-only event must NOT qualify (organizer rule excludes ME)
own_org = ("BEGIN:VEVENT\nUID:o4\nDTSTART" + in1h_utc + "\nSUMMARY:Family\n"
           f"ORGANIZER;CN=d:mailto:{ME}\nATTENDEE;CN=m:mailto:mom@family.com\nEND:VEVENT\n")
check("own-organized circle event stays personal", not sm.qualifies(sm.parse_events(own_org)[0], circ))

# --- dedupe: mirrored invites (same start + same link) = ONE meeting, one dossier ---
twin_a = sm.parse_events("BEGIN:VEVENT\nUID:m1\nDTSTART" + in1h_utc +
                         "\nSUMMARY:Interview with X\nLOCATION:https://meet.google.com/sea-yqgb-cbw\nEND:VEVENT\n")[0]
twin_b = sm.parse_events("BEGIN:VEVENT\nUID:m2\nDTSTART" + in1h_utc +
                         "\nSUMMARY:First Round - X\nLOCATION:https://meet.google.com/sea-yqgb-cbw\nEND:VEVENT\n")[0]
other = sm.parse_events("BEGIN:VEVENT\nUID:m3\nDTSTART" + in1h_utc +
                        "\nSUMMARY:Different call\nLOCATION:https://meet.google.com/zzz-other\nEND:VEVENT\n")[0]
check("mirrored invites deduped to one", len(sm.dedupe([twin_a, twin_b, other])) == 2)
check("no-link events never deduped", len(sm.dedupe([sm.parse_events(ics_event('n1', in1h_utc))[0],
                                                     sm.parse_events(ics_event('n2', in1h_utc))[0]])) == 2)

# --- interview detection (2026-07-14: cold interviews need the CANDIDATE frame deterministically) ---
check("title 'Interview' detected", sm.is_interview({"summary": "First Round Interview - Growth Protocol"}))
check("title 'Take-Home' detected", sm.is_interview({"summary": "Take-Home (LangGraph) + Review"}))
check("peer interview detected", sm.is_interview({"summary": "Peer Interview - Daniel Puri"}))
check("ATS organizer detected", sm.is_interview({"summary": "Chat", "organizer": "no-reply@greenhouse.io", "attendees": []}))
check("plain catch-up NOT an interview", not sm.is_interview({"summary": "Daniel / Sam Catch-up", "attendees": ["sam@postral.org"]}))

# --- recurring: two occurrences of one UID are independent preps (UID+start key) ---
occ1 = {"uid": "r1", "start": now + timedelta(minutes=60)}
occ2 = {"uid": "r1", "start": now + timedelta(days=7, minutes=60)}
check("recurring occurrences keyed apart", sm.key_of(occ1) != sm.key_of(occ2))

if FAILS:
    print(f"PREP PHYSICS: {len(FAILS)} FAILED")
    sys.exit(1)
print("PREP PHYSICS: all 26 fixtures pass")
