# Twin Mind - canonical changelog
One dated entry per working session. Newest on top. The full narrative lives in RETROSPECTIVE.md; this file is the terse ledger.

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
