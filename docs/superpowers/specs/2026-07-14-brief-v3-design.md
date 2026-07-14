# Morning Brief v3 - design (brainstormed with Daniel, 2026-07-14)

## Job (Daniel's ruling)
Act-fast briefing: core = "what needs me + what's today" in 90 seconds. Learning/coach = bus-depth
bonus, same email, below the fold.

## The email
Subject: `Morning brief - {Weekday} {D} {Month}` - and the DATE MUST BE CORRECT (watchdog checks
subject date == actual date; added after Daniel caught a wrong date in the design mockup).
Sections framed by heavy dividers (U+2501 x29):
1. NEEDS YOU TODAY - one line per item: who / what / why now. NO ready-to-send drafts (Daniel's
   ruling: email volume doesn't justify them; killed 2026-07-14).
2. TODAY - weather line (Luxembourg, Open-Meteo API, code-fetched) + calendar events with
   feed-verified local times.
3. AI ADVANCEMENTS - 2-3 items; breadth across the AI landscape welcome (a Cohere release counts);
   tie to Daniel's work when natural, never forced; dedupe ENFORCED against digest-covered state.
4. ONE TECHNICAL THING - conversation-driven: teach the concept under what Daniel+Claude actually
   worked on in the last 48h (mine changelog + recent chat + incidents); the static queue fills
   quiet days only. Quiz question + "Answer:" line, always.
5. COACH - unchanged (consistently rated good).
Removed: OPEN LOOPS (existed for job search; paused). Final line: coverage ("Reviewed N messages
since <cursor>"). Verdict-ask lives in the Telegram delivery summary, not the email.

## The pipeline (deterministic vs agentic - the load-bearing split)
PRE-FETCH SCRIPT (code, runs before the agent):
- inbox since cursor, each email annotated with STATE FLAGS: unread?, already-replied-by-Daniel?,
  known contact?, thread-live?
- hard skip-tier: noise domains/senders (the OPERATIONS.md skip-list) filtered IN CODE - the model
  never sees them
- calendar (tz-verified), weather, state files (digest-covered, cursor), yesterday's headlines
AGENT (model, judgment + prose only):
- decides substance ("does this email matter?") on the pre-filtered, state-annotated remainder
- writes the one-liners, AI items, lesson, coach nudge; fills the fixed template
SEND + VERIFY (code): send_email (heartbeat + cursor), watchdog 07:50 v3 contract:
dividers, subject-date correctness, Answer-line, weather present, calendar payload cross-check
vs live feed, dedupe check vs covered-file, coverage line, no em dash, skill-guard.

## How "which emails matter" is decided (Daniel's question)
Three tiers:
1. CODE skip-tier (deterministic): known-noise senders/domains never reach the model.
2. CODE state flags (deterministic): unread / replied / known-contact / thread-live annotations.
3. MODEL substance judgment on the remainder - no numeric threshold exists; the decision boundary
   is defined by (a) the rules in the skill (latest-state, never-nudge-answered, always-surface
   list), (b) the state flags, and (c) the accumulated regression items that pin every boundary
   case Daniel has ever corrected. The boundary sharpens as labels accumulate - that IS the
   threshold, expressed as examples rather than a number.

## Eval updates
- Watchdog: + subject-date check, + dedupe check, + weather-present.
- Regression suite: unchanged (rules still read live from the skill).
- Judge prefill rubrics: reflect no-drafts and conversation-driven teacher.

## Simplification rider (Daniel: "dead simple")
Box skills dir carries ~18 UNUSED Hermes-bundled skills (apple, smart-home, yuanbao, social-media,
mlops...). Archive them off the active path; keep only our 4 + computer-use off. Watchdog
skill-guard allowlist shrinks accordingly.
