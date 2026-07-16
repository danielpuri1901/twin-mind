---
name: morning-brief
description: Daniel's daily 07:30 brief - act-fast decisions on top, bus-depth learning below, sent as one real email
---
Compose Daniel's morning brief and SEND it as ONE real email to danielpuri1901@gmail.com
(send-only, pre-approved). v3 per the 2026-07-14 spec: the pre-fetch script already gathered
ALL facts (weather, calendar, state-annotated inbox, covered topics) - they are in your prompt.
Your only jobs: judge substance and write prose. Do NOT re-fetch what the script provided.

FORMAT CONTRACT (machine-checked at 07:50 - the rendering is not a creative choice):
- Subject: exactly `Morning brief - {Weekday} {D} {Month}` - and the date MUST be today's real
  date (run `date` if unsure; the watchdog compares).
- Every section header framed by divider lines: ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ (U+2501 x29).
- Plain hyphens only. NEVER an em dash. No emoji in headers.
- Final line: `Reviewed N messages since <cursor>` - N is EXACTLY the count the pre-fetch stated.

Sections, in order:
1. NEEDS YOU TODAY - one line per item: who / what / why now. NO ready-to-send drafts (Daniel's
   ruling 2026-07-14: volume doesn't justify them; he asks on Telegram when he wants one).
   Deciding what matters: the state flags are facts - trust them. REPLIED-ALREADY means the ball
   left Daniel's court; UNREAD + KNOWN + a question usually matters; deadlines and money always
   surface. Latest-state check still applies: newest evidence wins; a reply that confirms a plan
   closes the loop; never nudge someone who already answered. Ambiguity = pose a question, never
   an action.
2. TODAY - the weather line first (as provided), then calendar events with their provided times.
   Nothing else.
3. AI ADVANCEMENTS (2-3 items) - insights, not headlines; breadth across the AI world welcome
   (a Cohere release counts even without a project tie); tie to Daniel's work when natural, never
   forced. HARD RULE: nothing on the covered-topics list may appear again. After sending, append
   today's topics to ~/.hermes/state/digest-covered.txt (one line each, with date).
4. ONE TECHNICAL THING - conversation-driven: read the TOP entry of
   ~/super-project/docs/CHANGELOG.md and teach the concept underneath what Daniel and Claude just
   built or broke (yesterday's incident beats any queue item). Only on a quiet day fall back to
   ~/twin-corpus/wiki/learning/digest-queue.md (day-of-year mod item-count - RECOUNT the list).
   Format: concept in 3-4 sentences, the EXACT code in this system (read the real file, quote
   path + lines), ONE quiz question, then its answer on the next line as `Answer: ...`. Never
   skip the answer.
5. COACH (1 item) - one nudge, spaced-repetition style: resurface if unacknowledged, else one new
   observation grounded in concrete corpus evidence. No platitudes.
   GROUNDING (hard rule, 2026-07-16 after a hallucination): every claim about Daniel's CURRENT
   situation must be a dated, verifiable fact. The corpus holds PLANS, proposals and experiments
   that were later changed or cancelled - NEVER present one as if it is happening now (the brief
   once claimed "day one of the Haiku trial" - there was no trial; it was proposed then cancelled).
   Do NOT state what the system "is doing today" (which model it runs, what experiment is live)
   unless that fact is in your prefetched inputs. When you have no verifiable current fact, coach
   from a stable value or a dated past behavior - cite the date. If unsure it is current, leave it out.
(There is NO open-loops section - removed 2026-07-14 with the job-search pause.)

After sending: deliver a 3-line summary on Telegram ENDING with exactly:
"Verdicts? (brief/coach/teacher: good|bad + notes)" - Daniel's daily labels are the calibration
dataset; positive labels matter as much as complaints.
Feedback handling: parse any verdict reply into ~/twin-corpus/datasets/feedback.jsonl
({date, section, verdict, note}); a "bad + why" also gets a drafted regression item proposed to
Daniel. Acknowledge in one line; never argue with a verdict.
WEEKLY REVIEW (Sundays): one extra Telegram message listing unrated briefs, watchdog flags, any
workaround you used that is not in the governed skills - Daniel labels inline.

You never edit skill files or create new skills; propose diffs instead. Report tool bugs the same
day you find them - never silently work around them.
