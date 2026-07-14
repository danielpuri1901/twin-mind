# agents/background-prep - design (brainstormed with Daniel, 2026-07-14)

## Job
Before every professional call, Daniel gets a half-page dossier on Telegram ~1h ahead:
who / their background / company + news / HIS history with them / his inferred goal / 2-3 questions.

## Daniel's rulings
- Delivery: Telegram, ~60 min before the meeting (Q1: B).
- Scope: professional only, detected MECHANICALLY: has a video link OR organizer email outside the
  personal circle (Q2: A+B). Personal events never prepped.
- Goal: infer from context; ASK the evening before only when thin - first call / unknown organizer
  (Q3: B). Daniel's one-line answer leads the dossier.
- Size: half page (Q4: B).
- Name: agents/background-prep.

## Architecture
TRIGGER: 15-min no-LLM poller (hermes cron --no-agent --script scan_meetings.py):
scans ICS 24h ahead, applies the scope filter, checks prepped-state; when a qualifying meeting
enters the 60-75min window it self-schedules a ONE-SHOT prep agent (hermes cron create "1m" with
the meeting context as prompt + background-prep skill). 21:00 pass: detect tomorrow's thin-context
calls -> send the goal question. Idle cost: zero (watchdog pattern - silent unless work exists).

TOOLS (Daniel's inventory):
- scan_meetings.py (new, deterministic): ICS scan + filter + windows + self-schedule + state.
- corpus-search (shared, exists): Daniel's history with the person.
- Granola MCP (exists): all prior meeting notes with them - call #2 knows call #1.
- web search: Tavily (search) + Firecrawl (page extraction) - company news, funding, background.
- LinkedIn: HONEST LIMIT - no API, scraping blocked; covered via public search results
  ("name company site:linkedin.com" through Tavily/Exa snippets). Stated plainly in dossiers.

MODEL: Sonnet 4.6 at launch - this is a tool-heavy multi-step research agent; the regression
bake-off qualified cheap models for single-shot JUDGMENT only, not tool orchestration. Once prep
has its own labels + checks -> its own bake-off later. (~$0.15/prep, a few/week - cost is a
non-factor; reliability of tool-calling is.)
Brief's model, decided separately: Haiku 4.5 three-day TRIAL after v3's first Sonnet morning
(regression 9/9; prose refereed by daily verdicts + shadow judge; rollback = one config line).

## State + checks (born with the learnings)
- ~/.hermes/state/prepped.txt - one line per prepped meeting (id + timestamp); no double-preps.
- Coverage check rides the 07:50 watchdog: every qualifying meeting YESTERDAY had a prep >=30min
  before its start; misses ping Telegram and become regression items.
- Verdicts: post-call "prep: good|bad + note" -> feedback.jsonl -> dataset; same flywheel.
- Format contract: fixed dossier section order, machine-checkable; cite-or-refuse (thin public
  info = said plainly, never padded).

## Folder
agents/background-prep/{SKILL.md, JOB.md, tools/scan_meetings.py}. Everything else is shared
machinery already in production (watchdog, feedback capture, gate, corpus contract).

## Stepback review fixes (adopted 2026-07-14, pre-build)
1. TRIGGER REDESIGN (the reviewer's headline): NO exact window, NO one-shot self-scheduling.
   Idempotent catch-up: every poll, prep any qualifying meeting starting within 75 min that has
   no delivered prep and no in-flight claim; late detection ships with a "LATE" tag down to T-5.
   State = JSON, three states per meeting-occurrence: claimed / delivered (on confirmed send) /
   failed. Key = UID + occurrence-start (recurring events!). Poller writes a heartbeat file;
   staleness >30 min alerts SAME-DAY via the existing alarm path - not at tomorrow's 07:50.
2. SCOPE FILTER (gate zero PASSED - feed carries ATTENDEE/ORGANIZER/DESCRIPTION/UID/STATUS):
   heuristic = any ATTENDEE outside the personal circle, excluding Daniel (NOT organizer - Daniel
   organizes his own calls). Video-link detection from DESCRIPTION. Personal circle lives at
   ~/.hermes/state/personal_circle.txt, seeded from contacts.jsonl, maintained by a one-tap
   "never prep <person>" verdict reply - exists DAY ONE (the doctor-call false positive is not
   acceptable even once).
3. PRIVACY RULING adopted: name/company from the invite MAY be web-searched (equivalent to Daniel
   googling before a call). HARD RULE: outbound queries may contain ONLY name/company - never
   calendar description text, never corpus or Granola content. Every outbound query is logged;
   the format check audits the log.
4. CALENDAR PHYSICS as named rules + day-one fixtures in the gate: recurring (UID+occurrence),
   all-day events excluded, rescheduled-after-prep -> one-line correction ping, cancelled ->
   suppression, created-inside-window -> caught by the catch-up rule.
5. GOAL-ASK never blocks: unanswered 21:00 ping -> dossier ships with "Goal (inferred,
   unconfirmed):"; answers stored per-meeting; post-21:00 bookings skip to inference.
6. EVAL BOOTSTRAP (low volume honesty): no judge in the near plan (20 labels = months at this
   frequency). Day one: format contract at send, poller dead-man, did-it-look invariants
   (corpus-search called; Granola called when prior meetings exist), outbound-query log audit,
   and ONE SHADOW WEEK (dossiers to log only) before live delivery.
7. LINKEDIN EXPECTATION: snippets only (no API); fallback chain = Exa people-search, company team
   page, personal site, GitHub, conference bios, Crunchbase via Firecrawl. Dossier labels the
   limit explicitly ("LinkedIn: headline only").
8. MODEL: Sonnet at launch (tool-orchestration untested on cheap models - the bake-off qualified
   single-shot judgment only). Prep gets its OWN bake-off once shadow-week checks + verdicts
   exist. (Daniel's ruling: every agent gets tested on ITS OWN job before model swaps.)
