# Twin Mind - canonical changelog
One dated entry per working session. Newest on top. The full narrative lives in RETROSPECTIVE.md; this file is the terse ledger.

## 2026-07-13 - the twin's secret diary
- INCIDENT: brief showed Sam/Postral meeting at 17:00; real time 19:00. Root cause: calendar_read
  stripped ICS timezones (the Z suffix) - not a hallucination; the model faithfully relayed bad tool
  data and added an unwarranted "CEST" label. Fixed (Z + TZID -> local), proven against the live event.
- DISCOVERY via trace diagnosis: the twin maintained a private self-authored skill
  ("morning-brief-infra-notes"), patched it 3x this morning, and even ATTEMPTED to patch the governed
  morning-brief skill (blocked by a profile quirk, not obedience). Framework's skill_manage guidance
  conflicted with our SOUL rule.
- THE TWIST: the diary was ~85% verified gold - including a REAL bug in send_email.py (missing
  datetime import; the cursor NEVER wrote; the twin manually worked around it daily since Jul 9
  without telling us) and Tirith scanner patterns explaining past format constraints. Also contained
  confident false entries (--today flag "confirmed working" - flag doesn't exist).
- RESOLUTION: bug fixed (twin credited), diary salvaged into governed skills/morning-brief/OPERATIONS.md
  (corrected), rogue skill deleted, SOUL loophole closed (no skill_manage; report bugs same day, never
  silently work around), Sunday review now surfaces undocumented workarounds. Gate green; all deployed.
- Feedback row logged (calendar tz). Langfuse thread view = Sessions tab (answered).

## 2026-07-12 - the loop learns to listen
- SHIPPED through the gate (9/9 green): brief format contract + fact-density pin, feedback capture (Daniel's daily verdicts -> datasets/feedback.jsonl), SOUL explaining rule, audience-retrieval router (drift found by Daniel's "where in the code?" - verdict 07-03, deployed 07-12, receipts: family content 0.37->0.07 under hybrid retrieval).
- Renames per new global naming rule: run_triage->run_regression, run_baseline->run_benchmark, TRIAGE_SYS->INBOX_DECISION_RULES, scorecard-pairs->gold-candidates-pool; stale artifacts archived.
- Doctrine adopted: docs/eval-doctrine.md - two LangChain online-eval articles translated to n=1 (deterministic checks on everything, judges calibrated against Daniel, verdicts->dataset within a day, weekly review queue). All four of Daniel's proposed evals (coach/teacher/email/retrieval) formally planned.
- Artifacts: agent-memory whiteboard + evals whiteboard (claude.ai/code).
- OPEN: brief_check.py (07:50 outcome+format verifier), datasets/ move, ~/twin-mind folder rename (Daniel's go), hardening session (automation credential first), judges after ~20 verdicts.

## 2026-07-08 - Session A complete: the evals RUN
- Deployed to box: SOUL time rule, inbox cursor + coverage contract, digest section ("one technical thing" daily, interview-gap queue leads), 8 learning-wiki files. Gateway restarted.
- FIRST regression suite run: tools/run_triage.py (3 tasks x 3 trials, code+judge graders, tracked metrics) -> 9/9 PASS. Baseline established.
- tools/eval.sh = the ship gate; CLAUDE.md rule: no skill/prompt/model change ships without it green.
- Research trio audited (Anthropic evals + BEA, OpenAI guide, 12-Factor): ~85% aligned; fix plan at docs/plans/2026-07-08-compliance-fix-plan.md (Session B: brief workflow-ification; Session C: hardening).
- Interview retrace: verbatim misses filed + Tiffany debrief transcript in corpus; Robert window ~Aug 6 (Daniel's own request, confirmed by mailbox read); triage-03 minted from the brief's missed-reply error.

## 2026-07-04 - first production incident, resolved same day
- INCIDENT: first unattended 7:30 brief failed to email (silently). Root cause: Docker terminal sandbox starved the agent's hands (.env/tools/venv absent in container). The twin diagnosed its own confinement, composed a degraded-but-smart brief from Granola+memory, delivered via Telegram, and stated the cause. Latest-state rules visibly applied ("state ambiguous - present as question").
- FIX 1: box terminal.backend -> local (documented trade-off: single-purpose zero-inbound box; approvals+SOUL rules remain; "Docker with proper mounts" backlogged).
- FIX 2: inbox_read --hours was date-granular (IMAP SINCE) -> real hour cutoff added. CORRECTION: yesterday's "test email arrived" was a false positive from this bug; box email delivery had never actually worked until today.
- FIX 3: heartbeat via aws CLI subprocess (system python3 lacked boto3; failure was swallowed as designed).
- VERIFIED end-to-end as cron runs it: email delivered + BriefSent metric = 1.0 in CloudWatch.
- LESSON BANKED: detection lag (24h alarm) too slow - tighter schedule-aware check backlogged; verification tools must be tested for lying before being trusted.
- Also: AWS login session expiry keeps severing the admin tunnel (3rd time) - scoped automation credential for the Mac->box sync queued in hardening batch.

## 2026-07-03 (evening session)
- MILESTONE COMPLETE: morning brief cron scheduled (7:30 daily, box) + scheduled path proven E2E (test brief delivered) + dead-man's switch armed (code-level BriefSent heartbeat in send_email.py, 24h CloudWatch alarm -> SNS; pending Daniel's subscription confirm).
- cron_mode: deny confirmed NOT to block the brief's send path.
- Prompt caching ground truth CORRECTED: measured working on Bedrock (~83-99k cache-read tokens/turn, ~1/10 rate); compaction policy queued for the fattening Telegram session.
- Papers reviewed (middle-depth): MemGPT (validates stack; steal memory-pressure saves), PersonaTree (wiki-v3 blueprint: patterns layer + per-claim confidence + depth-conditioned retrieval).
- New skill: research-papers (Semantic Scholar REST via curl, keyless). Deployed to box.
- Box fixes: langfuse SDK installed (traces verified from box), sqlite-vec installed (hybrid verified server-side), pairing re-approved, SOUL knows its runtime.
- Corrections banked as regression data: twin-triage-v1 (2 items: source-coverage, recency-resolution) + skill rules.
- OPEN (tomorrow's hardening batch): secrets -> SSM Parameter Store, compromise runbook, pinned dependency manifest (4 missing-dep strikes), weekly Mac->box corpus refresh, nightly ~/.hermes state backup, ephemeral tool-status UX (grounding needed), invariant eval suite, correction auto-capture.

## 2026-07-03
- MIGRATED: twin now 24/7 on EC2 (eu-west-1, zero-inbound, SSM-only, Docker sandbox). Mac = corpus factory. Cutover clean (single-owner order).
- Fixed on box: messaging extra, sqlite-vec (hybrid verified server-side).
- Security: untrusted-content rules added to SOUL (injection); twin forbidden from self-editing skills.
- First live morning brief sent + self-verified; 2 staleness errors -> twin-triage-v1 regression dataset + 2 skill rules (latest-state check, Granola source coverage).
- Senses: Telegram paired (Daniel only), local Whisper voice, IMAP inbox reader (PEEK), ICS calendar reader (+recurrence), Notion+Granola MCP, web pinned (Tavily search / Firecrawl extract).
- Corrections banked: LangChain rejected (door open ~Sep), thesis defense reset from Jul 7.
- Audit (am): repo = single source of truth (symlinks), launchd service, hybrid default deployed, judge temp 0, debris deleted.
- Stepback #4 verdict adopted: milestone = "loop runs unattended every morning and screams when it fails". OPEN: 7:30 cron + E2E scheduled test + dead-man's switch; secrets->Parameter Store + runbook; weekly corpus refresh.

## 2026-07-02
- Corpus complete: 34,713 records / 6 sources (Gmail denoised 58.9k->5.4k); wiki v2 (2017-2026).
- Gold set: 32 pairs, audience-sliced; judge (content/fidelity/aspiration); 6 experiment runs -> hybrid default for Q&A, audience-conditional drafting retrieval, tuning stopped at benchmark resolution.
- Embeddings: 25,473 vectors (Cohere multilingual v3, sqlite-vec, ~$0.40).
- Langfuse tracing live + score configs; cost measured ~$0.007/turn (caching verified).
- AWS: daniel-admin (root retired), budget alert (credits excluded), box launched then stopped.

## 2026-07-01 and earlier (Jun 30)
- Scope + rules locked (eval-first, simplest/deterministic/auditable, two-tier corpus privacy).
- Machine indexed (161k files); 20GB disk freed; iMessage 20,583 + transcripts 6,558 turns ingested; wiki v1; corpus local-only git with push-block.
- Hermes chosen + installed on Mac; Bedrock EU; first corpus-grounded answer (Max Hammer, 28 tool calls).
