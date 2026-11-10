#!/usr/bin/env python3
"""The no-reply alarm (2026-11-10). Deterministic, free, no network.

On 2026-11-10 chat left three answers unsent and no alarm fired, because the only chat check
looked at the process and never at the answers."""
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "agents", "chat", "tools"))
import reply_check as R

NOW = 10_000.0
user = lambda age: {"role": "user", "ts": NOW - age, "text": "q"}
answer = lambda age: {"role": "assistant", "ts": NOW - age, "text": "a"}

# an answered message is quiet, however old
assert R.unanswered([user(400), answer(390)], NOW) == []
# a message still inside its five minutes is quiet
assert R.unanswered([user(299)], NOW) == []
# an unanswered message is reported in the one run where it crosses the line
late = R.unanswered([user(900), answer(880), user(301)], NOW)
assert [m["ts"] for m in late] == [NOW - 301]
# and never again: one run later it is outside the window
assert R.unanswered([user(301 + R.EVERY)], NOW) == []
# two messages with one late answer after both count as answered
assert R.unanswered([user(500), user(450), answer(10)], NOW) == []
# the window is as wide as the timer period, so consecutive runs leave no gap and no overlap
assert len(R.unanswered([user(R.WAIT)], NOW)) == 1 and R.unanswered([user(R.WAIT + R.EVERY)], NOW) == []
# the alert names the time of the oldest waiting message and stays one line
text = R.alert([user(320), user(310)])
assert "5 minutes" in text and "\n" not in text
# rows the mod relayed carry `via`; they are ordinary answers here
assert R.unanswered([user(400), {**answer(390), "via": "relay"}], NOW) == []
print("reply check: ok")
