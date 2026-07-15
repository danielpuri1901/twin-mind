# background-prep - the job, one page

**Job**: before any professional meeting, Daniel has a half-page dossier on his phone: who he's meeting, what the company does, what happened last time, what he wants out of it, and 1-2 opening questions.

**Success** = dossier delivered 75-15 min before the meeting, every fact checkable, goal line present (stated or clearly-marked inferred).
**Scope ruling (Daniel, 2026-07-14):** err INCLUSIVE - "anything with a calendar meet is important, any meeting is important." Everything Granola recorded mattered in retrospect. Circle starts empty; an unwanted dossier is cheap, a missed one is not.
**Failure** = no dossier for a qualifying meeting, a hallucinated fact, or a privacy leak in a search query.

## Deterministic vs agentic (BEA doctrine)

| Deterministic (code, scan_meetings.py) | Agentic (model, SKILL.md) |
|---|---|
| ICS fetch + parse (tz, recurring, all-day, cancelled) | judging which facts matter |
| scope filter: outside-circle attendee OR video link | inferring the goal when unstated |
| the 75-min catch-up window + 20-min claim lease | composing the half-page |
| state JSON (claimed/delivered/failed) | choosing the 1-2 opening questions |
| 21:00 goal-ask detection | answering "have we met before?" from corpus |
| heartbeat metric | |

## Spec deviation (honest note)

Spec fix #1 said "poller runs the prep directly." A --no-agent script can't invoke the model,
so the poller schedules a one-shot agent cron instead - but the spec's real objection
(claims becoming tombstones that eat preps) is solved with a 20-min lease: a claim that
never turns into "delivered" expires and the next poll retries. No prep can be silently lost.

## Planned evals (bootstrap - no judge until we have real dossiers)

1. **Physics fixtures in the gate from birth**: evals/test_prep_scan.py - recurring, all-day, Z-vs-TZID, cancelled, circle filter, lease expiry, delivered-idempotence. Runs in eval.sh.
2. **Poller dead-man**: PrepPollerRan metric + CloudWatch alarm (same pattern as WatchdogRan).
3. **Did-it-look invariants** (weekly, deterministic): every qualifying calendar event has a state entry; every delivered dossier has query-log lines; zero query-log lines contain calendar/corpus text.
4. **Shadow week**: dossiers delivered with [SHADOW] prefix, Daniel verdicts them (good|bad + notes) exactly like brief verdicts -> feedback.jsonl -> first labeled dataset (`prep-verdicts.jsonl`).
5. **Later** (post-shadow, 15+ labels): calibrated dossier judge (pinned Sonnet) on accuracy/citations/goal-quality; then and only then a model bake-off ON THIS JOB (never a proxy dataset - the rule).

**Model**: Sonnet (eu.anthropic.claude-sonnet-4-6). Any swap requires this agent's own-job benchmark first.
**Store**: ~/.hermes/state/{prep-state.json, personal_circle.txt, prep-query-log.txt}. No checkpointer - every prep is a fresh run; continuity lives in files.
