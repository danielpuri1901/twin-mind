#!/usr/bin/env python3
"""Granola-ingest fixtures for fetch_granola's poller (in the gate from birth).
Deterministic, free, no network, no Keychain: the decrypt+fetch boundary is
injected (fetch_transcript_fn), so a fixture never touches a real secret.
Every fixture is a way the ingester must behave: baseline scope, idempotence,
update re-fetch, finality gating, speaker mapping, parse-failure honesty.
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
import fetch_granola as fg

FAILS, PASSED = [], 0
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def check(name, cond):
    global PASSED
    if cond:
        PASSED += 1
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}")


def doc(did, title="Weekly Sync", updated="2026-07-14T10:00:00Z",
        created="2026-07-14T09:00:00Z"):
    return {"id": did, "title": title, "updated_at": updated, "created_at": created}


def seg(source, text, final=True):
    return {"source": source, "text": text, "is_final": final}


FINAL = [seg("system", "Hello Daniel."), seg("microphone", "Hi there.")]


def final_fetch(_did):
    return list(FINAL)


def never_called(_did):
    raise AssertionError("fetch_transcript_fn was called for a doc that should have been skipped")


def garbage_fetch(_did):
    return {"unexpected": "shape"}  # not a list, no transcript/segments key -> parse failure


def nonfinal_fetch(_did):
    return [seg("system", "still talking", final=True), seg("microphone", "interim", final=False)]


def fresh_inbox():
    d = tempfile.mkdtemp(prefix="granola-inbox-")
    return d


# --- speaker mapping: microphone -> Me, everything else -> Them (case-insensitive) ---
check("mic maps to Me", fg.map_speaker("microphone") == "Me")
check("MICROPHONE maps to Me (case-insensitive)", fg.map_speaker("MICROPHONE") == "Me")
check("system maps to Them", fg.map_speaker("system") == "Them")
check("empty source maps to Them", fg.map_speaker("") == "Them")

# --- body: consecutive same-source segments collapse into one turn ---
body = fg.segments_to_body([seg("system", "Hi."), seg("system", "How are you?"),
                            seg("microphone", "Good."), seg("microphone", "Thanks.")])
check("consecutive same-source collapse to two turns",
      body == "Them: Hi. How are you?\nMe: Good. Thanks.")
check("empty-text segments are dropped",
      fg.segments_to_body([seg("system", "  "), seg("microphone", "Real.")]) == "Me: Real.")

# --- finality gate: final only when segments exist AND tail is_final ---
check("final tail -> final", fg.is_final_transcript(FINAL))
check("empty transcript -> not final", not fg.is_final_transcript([]))
check("non-final tail -> not final", not fg.is_final_transcript(nonfinal_fetch(None)))

# --- baseline seeding: first run marks every current doc, writes NO file ---
inbox = fresh_inbox()
state = {}
c = fg.process([doc("a"), doc("b")], never_called, state, inbox, NOW, first_run=True)
check("baseline seeds all docs", c["baseline"] == 2 and c["saved"] == 0)
check("baseline writes no files", os.listdir(inbox) == [])
check("baseline records the run marker", "_baseline" in state)
check("baseline docs stored as baseline status", state["a"]["status"] == "baseline")

# --- after baseline: an unchanged pre-existing doc is never re-fetched (frozen scope) ---
c = fg.process([doc("a")], never_called, state, inbox, NOW, first_run=False)
check("baselined doc is skipped, never re-fetched", c["skipped"] == 1 and c["saved"] == 0)
check("baselined doc leaves no file", os.listdir(inbox) == [])

# --- baseline freeze holds even if the pre-existing doc's timestamp advances (no backfill) ---
c = fg.process([doc("a", updated="2026-07-20T10:00:00Z")], never_called, state, inbox, NOW, False)
check("advanced baseline doc still frozen (no backfill)", c["skipped"] == 1 and c["updated"] == 0)

# --- a genuinely NEW doc after baseline is saved (only-new-going-forward) ---
inbox = fresh_inbox()
state = {"_baseline": NOW.isoformat()}
c = fg.process([doc("new1", title="Postral Call", created="2026-07-14T09:00:00Z")],
               final_fetch, state, inbox, NOW, first_run=False)
check("new doc after baseline is saved", c["saved"] == 1)
files = os.listdir(inbox)
check("new doc writes exactly one file", len(files) == 1)
check("filename carries the created date (normalizer reads it)", files[0].startswith("2026-07-14-"))
check("new doc recorded as saved", state["new1"]["status"] == "saved")
written = open(os.path.join(inbox, files[0])).read()
check("saved file uses Me:/Them: turns", "Them: Hello Daniel." in written and "Me: Hi there." in written)
check("saved file has the metadata header", written.startswith("Meeting Title: Postral Call"))

# --- state idempotence: a seen, unchanged saved doc is never re-fetched ---
c = fg.process([doc("new1", title="Postral Call", updated="2026-07-14T10:00:00Z")],
               never_called, state, inbox, NOW, first_run=False)
check("unchanged saved doc is skipped, not re-fetched", c["skipped"] == 1 and c["saved"] == 0)

# --- update re-fetch: an advanced updated-timestamp IS re-fetched, same file reused ---
before = state["new1"]["file"]
c = fg.process([doc("new1", title="Postral Call", updated="2026-07-14T15:30:00Z")],
               final_fetch, state, inbox, NOW, first_run=False)
check("advanced updated-timestamp re-fetched", c["updated"] == 1)
check("update reuses the same file (no duplicate)",
      state["new1"]["file"] == before and len(os.listdir(inbox)) == 1)
check("update advances the stored timestamp", state["new1"]["updated"] == "2026-07-14T15:30:00Z")

# --- finality gating: a new but non-final doc stays pending, writes nothing ---
inbox = fresh_inbox()
state = {"_baseline": NOW.isoformat()}
c = fg.process([doc("live1")], nonfinal_fetch, state, inbox, NOW, first_run=False)
check("non-final new doc is pending, not saved", c["pending"] == 1 and c["saved"] == 0)
check("pending doc writes no file", os.listdir(inbox) == [])
check("pending doc left absent from state (re-checked next poll)", "live1" not in state)

# --- parse-failure honesty: an unparseable transcript is counted, printed, never hidden ---
inbox = fresh_inbox()
state = {"_baseline": NOW.isoformat()}
c = fg.process([doc("bad1")], garbage_fetch, state, inbox, NOW, first_run=False)
check("parse failure is counted", c["failed"] == 1 and c["saved"] == 0)
check("parse failure writes no file", os.listdir(inbox) == [])
check("parse failure marks the doc failed (retried next poll)", state["bad1"]["status"] == "failed")

# --- retry: a previously failed doc is attempted again and can succeed ---
c = fg.process([doc("bad1")], final_fetch, state, inbox, NOW, first_run=False)
check("failed doc is retried and saved on recovery", c["saved"] == 1 and state["bad1"]["status"] == "saved")

# --- build_markdown date handling: the 2026-07-15 failure. A manual Sam-transcript fetch
# passed an isoformat STRING for saved_on and build_markdown crashed on '.strftime'. The 33
# fixtures never caught it because process() only ever passes a datetime. Now hardened + tested. ---
from datetime import datetime as _dt
md_dt = fg.build_markdown(doc("x", title="T"), FINAL, _dt(2026, 7, 15))
check("build_markdown accepts a datetime (production path)", "auto-saved 2026-07-15" in md_dt)
md_str = fg.build_markdown(doc("x", title="T"), FINAL, "2026-07-15")  # the manual-fetch bug input
check("build_markdown accepts a string date without crashing", "auto-saved 2026-07-15" in md_str)

for d in [inbox]:
    shutil.rmtree(d, ignore_errors=True)

if FAILS:
    print(f"GRANOLA INGEST: {len(FAILS)} FAILED")
    sys.exit(1)
print(f"GRANOLA INGEST: all {PASSED} fixtures pass")
