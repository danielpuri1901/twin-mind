#!/usr/bin/env python3
"""Pre-prod eval for background-prep. Two instruments, per the own-job rule:

  --scope            replay the scope filter over the REAL calendar (past 30d + next 7d),
                     print the would-have-prepped decision table. Free, deterministic.
                     Daniel corrects it; corrections become circle entries or gate fixtures.
  --pick N           choose N past qualifying meetings for the dossier bench (mix of repeat
                     contacts and first contacts) and print the exact prompts scan_meetings
                     would have built. Feed these through the real gateway as [BENCH] one-shots;
                     Daniel's verdicts seed prep-verdicts.jsonl BEFORE the agent goes live.

Bench dossiers must go through the real harness (skill + corpus + Exa tools) - research is
the job; a tool-less Bedrock call would be a proxy, and proxies are banned (2026-07-14 rule).
"""
import argparse, os, sys, urllib.request
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents", "background-prep", "tools"))
import scan_meetings as sm


def fetch_events(now):
    ics = urllib.request.urlopen(os.environ["TWIN_CALENDAR_ICS_URL"], timeout=30).read().decode("utf-8", "replace")
    evs = [e for e in sm.parse_events(ics) if e.get("start")
           and now - timedelta(days=30) < e["start"] < now + timedelta(days=7)]
    return sorted(evs, key=lambda e: e["start"])


def scope_table(evs, circ, now):
    print(f"{len(evs)} events in window (past 30d + next 7d) | circle: {len(circ)} addresses\n")
    prep = skip = 0
    for e in evs:
        q = sm.qualifies(e, circ)
        prep += q; skip += not q
        others = [a for a in e.get("attendees", []) if a and a != sm.ME]
        why = ("outsider: " + ", ".join(a for a in others if a not in circ)[:60]) if q and others else \
              ("video link, no attendees" if q else
               ("all-day" if e.get("start") is None else
                "cancelled" if e.get("status") == "CANCELLED" else
                "circle/solo" if others is not None else "?"))
        tag = "PREP" if q else "skip"
        print(f"  {tag}  {e['start'].strftime('%a %d %b %H:%M')}  {e.get('summary','?')[:44]:44}  {why}")
    print(f"\nwould prep: {prep}  |  skipped: {skip}")
    print("CHECK THIS LIST. Wrong PREP -> add address to personal_circle.txt."
          " Wrong skip -> tell me; it becomes a gate fixture.")


def pick(evs, circ, now, n):
    past_q = [e for e in evs if e["start"] < now and sm.qualifies(e, circ)]
    seen = {}
    for e in past_q:  # prefer variety: one per counterpart, newest first
        k = tuple(sorted(a for a in e.get("attendees", []) if a != sm.ME)) or e.get("summary")
        seen.setdefault(k, e)
    sample = sorted(seen.values(), key=lambda e: e["start"], reverse=True)[:n]
    print(f"{len(sample)} bench meetings selected from {len(past_q)} past qualifying:\n")
    for i, e in enumerate(sample, 1):
        att = ", ".join(e.get("attendees", [])) or "none (video link)"
        print(f"--- BENCH {i}/{len(sample)} ---")
        print(f"[BENCH {i}/{len(sample)} - PAST MEETING, do not update prep state, prefix reply with [BENCH]] "
              f"MEETING PREP: '{e.get('summary','?')}' held {e['start'].strftime('%a %d %b %H:%M')}. "
              f"Attendees: {att}. Execute the background-prep skill as if this meeting were in 60 minutes: "
              f"research + compose the half-page dossier.\n")


if __name__ == "__main__":
    for line in open(os.path.expanduser("~/.hermes/.env")):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.strip().split("=", 1)
            os.environ.setdefault(k, v)
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", action="store_true")
    ap.add_argument("--pick", type=int, default=0)
    a = ap.parse_args()
    now = sm.local_now()
    circ_path = os.path.join(os.path.dirname(__file__), "..", "agents", "background-prep", "personal_circle.txt")
    circ = {l.strip().lower() for l in open(circ_path) if l.strip() and not l.startswith("#")}
    evs = fetch_events(now)
    if a.scope:
        scope_table(evs, circ, now)
    if a.pick:
        pick(evs, circ, now, a.pick)
