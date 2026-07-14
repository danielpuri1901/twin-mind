# Fix plan: closing the audit gaps (2026-07-08)

Source audits: Anthropic evals paper (spirit yes, letter no), Building Effective Agents + OpenAI
guide + 12-Factor Agents (one violation: brief miscast as free agent; F2/F3 partially rented).
Principle: three surgical sessions, no rebuild. What we explicitly do NOT do: switch frameworks,
go multi-agent, rewrite on LangGraph - all three sources say simplest-first; Hermes stays.

## Session A - "Make the evals RUN" (unblocks on aws login)
Fixes: evals-paper letter-compliance (suites that sit -> suites that run).
1. Deploy to box (skills incl. digest section + SOUL time rule, patched tools, learning wiki).
2. First-ever run of tools/run_triage.py (3 trials x 3 tasks; regression bar = 100%).
3. evals/eval.sh: one command that runs the triage suite (and optionally gold-32) -> exit code.
4. CLAUDE.md rule: NO skill/prompt/model change ships without eval.sh green. This turns
   "eval-first" from intention into mechanism.
DONE = triage suite has a baseline result in Langfuse; a failing item blocks a ship.

## Session B - "Right-shape the brief" (BEA / Factor 8+10)
Fixes: deterministic steps done by hope; ~30-step agent loop where a pipeline belongs.
1. Script pre-stage: hermes cron --script fetches inbox (--since-last-brief), calendar, cursor
   deterministically; stdout injected into the agent prompt. The agent cannot miss what is
   already in its prompt - kills the missed-email class structurally.
2. Post-brief outcome verifier: --no-agent cron at 07:50 checks the OUTCOME (today's brief in
   inbox + BriefSent heartbeat metric) and alerts Telegram on absence. Closes the outcome-grading
   loop daily (evals paper) and is BEA's "programmatic gate".
3. LLM keeps ONLY judgment + composition (its 0-incident zone).
DONE = a brief failure is detected within 20 minutes by code, not by Daniel noticing silence.

## Session C - "Ops hardening" (standing batch, unchanged)
1. Scoped automation credential (kills the aws login ritual - do FIRST).
2. Secrets -> SSM Parameter Store + 10-line compromise runbook.
3. Pinned dependency manifest (infra/box-requirements.txt) + pin interpreter paths in cron/skills.
4. Weekly Mac->box corpus refresh + nightly ~/.hermes state backup.
5. Date header in send_email (tz-honest timestamps).

## Deferred with reasons (do not silently drift)
- Model tiering (Haiku triage / Sonnet drafting): documented ground truth, unimplemented. At
  ~$2/day the saving is real but small; implement WITH eval.sh gating (Session A prerequisite)
  so the downgrade is measured, not vibed.
- Invariant suite as nightly online evaluator: after Session A (it reuses eval.sh plumbing).
- Faithfulness/grounded evaluator: waits for its first hallucination incident (0 so far).
- Compaction pinning + upstream time-injection PR (F3 ownership): queued, low urgency.
- User-simulation eval for Telegram conversations (tau2-style): future lane.

## The test of the whole plan
By the Robert call (~Aug 6): every claim in the interview story is demonstrable in Langfuse -
regression suite running on every change, outcome-verified daily loop, incident log with same-day
regression capture. "Ownership of the build" answered with receipts.
