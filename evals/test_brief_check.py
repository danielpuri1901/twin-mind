#!/usr/bin/env python3
"""Anti-drift test for the brief watchdog. format_fails() must PASS a known-good brief
(the format the brief actually produces) and CATCH real defects. This is the test whose
absence let the watchdog drift from the brief and cry wolf every morning (2026-07-15)."""
import os, sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents", "brief", "tools"))
from brief_check import format_fails

D = "━" * 29
TODAY = datetime(2026, 7, 15)  # a Wednesday
SUBJECT = "Morning brief - Wednesday 15 July"  # unnumbered/full names = what the brief emits
GOOD = "\n".join([
    D, "NEEDS YOU TODAY", D, "- AWS budget alert (costalerts, 2026-07-14): review", "",
    D, "TODAY", D, "Weather: Luxembourg: 16-28°C, rain chance 10%", "- 15:00 Sam call", "",
    D, "AI ADVANCEMENTS", D, "- MoE routing: sparse experts cut compute", "",
    D, "ONE TECHNICAL THING", D, "RRF ranking, agents/brief. Answer: reciprocal rank fusion", "",
    D, "COACH", D, "- You shipped the weather fix today - keep the momentum", "",
    "Reviewed 20 messages since 2026-07-14 07:30",
])
GOOD_NO_TECHNICAL = "\n".join([
    D, "NEEDS YOU TODAY", D, "- AWS budget alert (costalerts, 2026-07-14): review", "",
    D, "TODAY", D, "Weather: Luxembourg: 16-28°C, rain chance 10%", "- 15:00 Sam call", "",
    D, "AI ADVANCEMENTS", D, "- MoE routing: sparse experts cut compute", "",
    D, "COACH", D, "- You shipped the weather fix today - keep the momentum", "",
    "Reviewed 20 messages since 2026-07-14 07:30",
])

FAILS = []


def check(name, cond):
    if not cond:
        FAILS.append(name); print("  FAIL", name)


# 1. the real brief format passes clean (the drift bug)
gf = format_fails(SUBJECT, GOOD, TODAY)
check(f"good brief passes clean (got {gf})", gf == [])
gf = format_fails(SUBJECT, GOOD_NO_TECHNICAL, TODAY)
check(f"good quiet brief passes without technical section (got {gf})", gf == [])

# 2. real defects are still caught
check("missing section caught",
      any("missing sections" in f for f in format_fails(SUBJECT, GOOD.replace("COACH", "ZZZZZ"), TODAY)))
check("em dash caught",
      any("em dash" in f for f in format_fails(SUBJECT, GOOD + " — nope", TODAY)))
check("wrong date caught",
      any("date wrong" in f for f in format_fails("Morning brief - Monday 13 July", GOOD, TODAY)))
check("missing weather caught",
      any("weather" in f for f in format_fails(
          SUBJECT, GOOD.replace("Weather: Luxembourg: 16-28°C, rain chance 10%", "- nothing"), TODAY)))
check("no-answer quiz caught",
      any("Answer" in f for f in format_fails(SUBJECT, GOOD.replace("Answer: reciprocal rank fusion", ""), TODAY)))
check("missing coverage line caught",
      any("coverage" in f for f in format_fails(SUBJECT, GOOD.replace("Reviewed 20 messages since 2026-07-14 07:30", ""), TODAY)))

if FAILS:
    print(f"BRIEF-CHECK TEST: {len(FAILS)} FAILED")
    sys.exit(1)
print("BRIEF-CHECK TEST: all pass (watchdog matches the brief format)")
