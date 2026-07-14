# Twin Mind - canonical changelog
One dated entry per working session. Newest on top. The full narrative lives in RETROSPECTIVE.md; this file is the terse ledger.

## 2026-07-14 (later) - granola transcript ingest BUILT, gate-green
- pipeline/fetch_granola.py BUILT: Mac-side 15-min poller, the post-call mirror of background-prep.
  Path-2 auth chain lifted verbatim from the proven granola_path2_decrypt.py (Keychain -> storage.dek
  -> DEK -> supabase.json.enc -> live Bearer). Lists /v2/get-documents, and for any NEW meeting whose
  transcript is final saves the verbatim Me:/Them: transcript to raw/transcripts-inbox/, then normalize
  + build_index inline. Deterministic, no LLM, no secrets ever printed or written.
- Scope enforced (Daniel's ruling): first run BASELINES every current meeting (no file, never
  backfilled); only meetings appearing after baseline are ingested. State: ~/.hermes/state/transcript-state.json
  (seen doc ids + updated-timestamps + written filename). Saved doc whose updated-timestamp advances is
  re-fetched and overwrites the same file; unchanged docs never re-fetched.
- Speaker map: source microphone -> Me, everything else -> Them (strict, all the normalizer reads today).
  Finality gate: segments exist AND tail is_final; a still-transcribing meeting stays pending and is
  re-checked next poll (no half-written file). Any fetch/parse failure is counted AND printed, never hidden.
- Failure doctrine: decrypt/Keychain failure SCREAMS (prints loud, skips heartbeat so the dead-man fires,
  exits 1); a 401 is the soft "app not running" state (retry next poll). Heartbeat is two-way: local
  timestamp file (authoritative Mac-side, weekly-review checks staleness) + best-effort CloudWatch
  TranscriptPollerRan. Reindex runs under a non-blocking flock so it never overlaps a manual corpus refresh.
- normalize_transcripts.py: one-line SOURCES add (raw/transcripts-inbox/*.md) - wires in the inbox AND
  finally the hand-pasted tiffany file (14 turns). Verified without mutating the real corpus.
- 33 GRANOLA-INGEST FIXTURES born into the gate (evals/test_granola_fetch.py, wired into eval.sh next to
  test_prep_scan.py): baseline scope + freeze/no-backfill, idempotence, update re-fetch (same file reused),
  finality gating, speaker mapping, parse-failure honesty, failed-doc retry. Injected at the fetch boundary
  so no test touches network or Keychain. Gate GREEN (26 prep + 33 granola fixtures + 9/9 regression).
- launchd LaunchAgent staged: infra/com.twinmind.granola-transcript-poller.plist (15-min, RunAtLoad,
  logs to ~/.hermes/logs/granola-poller.{out,err}.log). NOT loaded - install one-liner handed to Daniel.
- DEVIATION from spec: reindex runs normalize + build_index (FTS, free, local) inline, but NOT the Bedrock
  embed step - it rebuilds the whole vectors.db over the network and costs money every poll (a 15-min-poller
  cost trap that also couples ingestion to AWS). New meetings are keyword-searchable within minutes; vectors
  catch up on the existing weekly Mac->box refresh. Incremental append-embed noted as the future optimization.

## 2026-07-14 (late night) - background-prep BUILT, gate-green, deploy staged
- AGENT #2 BUILT per spec v2: agents/background-prep/{SKILL.md (dossier contract, cite-or-refuse,
  privacy query rule + query log), JOB.md, tools/scan_meetings.py (15-min no-agent poller: ICS
  physics, circle/video-link scope filter, 75-min idempotent catch-up, 20-min claim lease, 21:00
  goal-ask, PrepPollerRan heartbeat, shadow-flag file)}. personal_circle.txt seeded (manual on
  purpose: contacts.jsonl has phones, not relationship-tagged emails).
- Spec deviation recorded in JOB.md: no-agent poller can't invoke the model, so it schedules a
  one-shot Sonnet cron; the spec's lost-prep objection is answered by the lease (stale claim
  expires -> retry). Nothing can be silently dropped.
- 15 CALENDAR-PHYSICS FIXTURES born into the gate (evals/test_prep_scan.py, wired into eval.sh):
  Z-vs-TZID same instant, all-day/cancelled excluded, circle filter, video-link rule, folded
  ATTENDEE, lease expiry, delivered idempotence, recurring keyed apart. All green first run.
- SKILL-GUARD FIX along the way: gateway re-materializes bundled skill dirs on restart
  (.bundled_manifest, reappeared 13:25) - "symlinks only" unenforceable; guard now allows
  manifest-listed dirs only. Would have false-alarmed the 07:50 watchdog on day one of v3.
- Gate GREEN (fixtures + 9/9 regression). Deploy payload staged; box push HELD pending Daniel's
  answer on the Fargate question (asked mid-deploy). Shadow week starts at deploy.
- Agent card artifact published (scope/access/middleware/model/evals/det-vs-agentic/stack fit).
- PRE-PROD EVAL built (Daniel's ask) and it PAID immediately: evals/run_prep_bench.py --scope
  replays the filter over the REAL feed (27 events/30d). Caught 3 prod bugs before prod:
  (1) recruiter as ORGANIZER-only never counted (Growth Protocol interview would have had NO
  prep), (2) Meet link lives in X-GOOGLE-CONFERENCE/LOCATION not DESCRIPTION, (3) mirrored
  invites (same start+link) would double-dossier. All fixed + 6 new fixtures; gate 21/21 green.
  --pick 8 selects past real meetings for the [BENCH] dossier run through the real harness;
  Daniel's verdicts on those = prep-labels.jsonl golden set, born before launch.
- DANIEL'S GO + scope ruling ("any meeting is important" - err inclusive, circle starts empty,
  recorded in JOB.md). DEPLOYED: files+symlink+shadow flag+watchdog fix on the box, prep-poller
  cron */15 live (first tick 17:15), PrepPollerRan seeded + 3h dead-man alarm (in
  recreate-monitoring.sh), 8 [BENCH] one-shots fired 17:10-17:38 on real past meetings
  (Chainfill, LangChain, Nik, Roxi, Postral, Spiros, 2x AWS interviews). Cron-create quoting
  lesson: positional prompt dies in nested bash -lc; pass args directly to sudo.
  Tonight 18:45: first organic shadow prep (Sam/Postral 20:00).
- BENCH VERDICTS 1-5 (Daniel, live): 1-3 good (Chainfill/LangChain/take-home; LangChain dossier
  reconstructed the full 4-round pipeline + rejection reason from Granola). Two findings became
  fixes, both gate-green (26/26) + deployed:
  (1) NIK DOSSIER RENDERED AS BLUE HTML - root cause: gateway delivers final Telegram msg as
  MarkdownV2 (cli-config.yaml.example:634); brief was immune only because it is EMAIL. Dossier had
  no plain-text contract so a run formed a valid MarkdownV2 entity. Fix: hard PLAIN-TEXT rule in
  SKILL (no markup, no < >, rewrite 'X <-> Y' to 'X / Y', no em dash, straight quotes).
  (2) INTERVIEW GOAL 'impossible to infer' cold - added deterministic is_interview() (title words
  + ATS/recruiter domains) -> passes 'MEETING TYPE: interview' so the candidate frame + fixed goal
  hold even with zero corpus history. 5 fixtures. Roxi dossier SELF-FLAGGED personal (spotted
  'Ma Corla' Spanish endearments) - scope self-correction working; circle candidate.
  prep-labels.jsonl now 6 rows (the golden set, growing from live verdicts).

## 2026-07-14 (night) - v3 shipped, judge calibrated, bake-off run, second agent specced
- BRIEF v3 LIVE for tomorrow 07:30: designed WITH Daniel (act-fast core: one-liners no drafts;
  weather; conversation-driven teacher w/ answers; dedupe enforced; open-loops dropped), built as
  deterministic prefetch (state-flagged inbox, noise tier, Open-Meteo) + prose-only agent + v3
  watchdog (subject-date, Answer-line, weather, dedupe checks). Cron carries the script stage.
- REPO RESTRUCTURED agent-shaped: agents/{brief,chat}, shared/, evals/, pipeline/. Leanness law in
  CLAUDE.md. Box skills: 4 governed only (18 bundled archived). Gate stayed green through the move.
- JUDGE CALIBRATED: 64% -> 80% in one rubric iteration vs Daniel-endorsed labels (62); remaining
  disagreements = instrument-scope (staleness->regression suite, answer-line->watchdog). Judge
  caught one wrong label ([7] Dan Luu repeat). calibrate_judges.py is the standing harness.
- MODEL BAKE-OFF (regression eliminator): Sonnet 9/9, Haiku 9/9, gpt-oss-20b 9/9 (!), 120b 8/9 DQ,
  Nova-2-Lite 0/9 (floor = format compliance). Haiku 3-day brief trial starts Jul 16 (one variable
  at a time; verdicts referee). OPEN: 20b prose benchmark failed 3x (args/env/HTML error) - rerun
  FOREGROUND with full stderr before judging its prose; does not block Haiku trial.
- SECOND AGENT SPECCED: agents/background-prep (dossiers ~1h before professional calls).
  Brainstormed with Daniel (Telegram T-60, mechanical scope filter, infer-goal-ask-when-thin,
  half-page). Hostile stepback adopted: idempotent catch-up poller (no one-shot machinery),
  attendee-not-organizer heuristic, personal-circle day one, outbound-query privacy rule + log,
  calendar-physics fixtures in the gate, shadow week, Sonnet at launch. Gate zero PASSED (ICS
  carries ATTENDEE/ORGANIZER/DESCRIPTION). Principle recorded: every agent is tested on ITS OWN
  job before model swaps.
- QA-gold minted (24 items, Daniel's prose-style labels; AM = TAX dept agents, internship ends
  Sep 9 - major fact corrections propagated to wiki).

## 2026-07-14 (evening) - stepback #6: refocus, green gate, freeze list
- RED GATE resolved per cold ruling: regression pass = code grader AND every assertion; the judge's
  holistic "overall" bit DELETED (a vibe layered on a deterministic pass; flicker was grader skew
  from the jargon-rename, not a regression). 9/9 green; inbox-decisions renames landed; deployed.
- Collaboration rules adopted (in CLAUDE.md): one-consolidated-ask when human input blocks >24h;
  Daniel timeboxes label sessions like meetings.
- CRITICAL PATH (5 steps): [1] gate green DONE -> [2] Daniel's 35-min label session -> [3] calibrate
  shadow judges vs labels -> [4] five-model bake-off -> [5] Session B brief workflow-ification.
- FROZEN: Session C hardening (except Daniel's 10-min interactive credential run) until bake-off
  ships; cross-run memory beyond digest-covered until Session B; teacher-gold until a real drill
  session produces material; fine-tune until 50+ labels AND post-Aug 6.
- DROPPED: further naming passes until September; datasets/-move + folder-rename cosmetics.

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
- evals/eval.sh = the ship gate; CLAUDE.md rule: no skill/prompt/model change ships without it green.
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
