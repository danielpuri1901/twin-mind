# background-prep - the job, one page

**Job**: before any professional meeting, Daniel has a half-page dossier on his phone: who he's meeting, what the company does, what happened last time, what he wants out of it, and 1-2 opening questions.

**Success** = dossier delivered 75-15 min before the meeting, every fact checkable, goal line present (stated or clearly-marked inferred).
**Scope ruling (Daniel, 2026-07-14):** err INCLUSIVE - "anything with a calendar meet is important, any meeting is important." Everything Granola recorded mattered in retrospect. Circle starts empty; an unwanted dossier is cheap, a missed one is not.
**Failure** = no dossier for a qualifying meeting, a hallucinated fact, or a privacy leak in a search query.

## Deterministic versus model

Meeting prep is not an agent since 2026-11-06.
Code does the research and the delivery.
The model makes two calls and holds no tools in either call.

| Code (`scan_meetings.py`, `compose_prep.py`) | Model (two calls, no tools) |
|---|---|
| ICS fetch and parse (time zone, recurring, all-day, cancelled) | Call 1: read calendar text, return names and companies only |
| scope filter: outside-circle attendee OR video link | Call 2: read the research, fill a fixed dossier |
| the 75-min catch-up window and 20-min claim lease | inferring the goal when unstated |
| cleaning each name, building the search queries | choosing the 1-2 opening questions |
| corpus-search and web search on those queries | writing "Couldn't verify." when a field has no support |
| rendering plain text, sending, archiving | |
| state JSON (claimed/delivered/failed), heartbeat metric | |

The rules that lived in `SKILL.md` now live in `compose_prep.py`: the compose rules, the 180-word limit and the cite-or-refuse rule.
`SKILL.md` is deleted.

## Why it changed

The old one-shot agent read calendar text while it held a host shell, private data and network access.
Anyone who could send Daniel an invite could reach all three.
Now search queries hold only cleaned names, so calendar text, corpus content and anything Daniel wrote never leave the box in a query.
Code logs every query to `prep-query-log.txt` for audit.

## Spec deviation (honest note)

Spec fix #1 said "the poller runs the prep directly."
Since 2026-11-06 it does.
`meeting-prep-poller.timer` starts `scan_meetings.py` every 15 minutes, and that script calls `compose_prep.py` itself.
Before that, a script could not call the model, so the poller scheduled a one-shot agent job.
The 20-min lease still protects against lost preps: a claim that never turns into "delivered" expires, and the next poll retries.

## Planned evals (no LLM judge, see docs/eval-doctrine.md)

1. **Physics fixtures in the gate from birth**: evals/test_prep_scan.py - recurring, all-day, Z-vs-TZID, cancelled, circle filter, lease expiry, delivered-idempotence. Runs in eval.sh.
2. **Poller dead-man**: PrepPollerRan metric + CloudWatch alarm (same pattern as WatchdogRan).
3. **Did-it-look invariants** (weekly, deterministic): every qualifying calendar event has a state entry; every delivered dossier has query-log lines; zero query-log lines contain calendar/corpus text.
4. **Verdict labels**: Daniel marks each delivered dossier good or bad with notes, like brief verdicts, to build the first labeled dataset (`prep-dossier-verdicts.jsonl`). The `[SHADOW]` prefix is gone, and dossiers go out as normal messages.

**Model**: Sonnet 5.5 (`claude-sonnet-5-5`, Anthropic API, since 2026-10-23). Any swap requires this agent's own-job benchmark first.
**Store**: ~/.twin-mind/state/{prep-state.json, personal_circle.txt, prep-query-log.txt}. No checkpointer - every prep is a fresh run; continuity lives in files.
