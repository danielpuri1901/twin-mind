# Twin Mind - project rules

A personal AI twin + life-coach that learns from Daniel's own data, runs on AWS, stays human-in-the-loop, and gets sharper as the corpus grows.

Design: `docs/2026-06-30-twin-mind-design.md` · Build plan: `docs/gameplan.md` · Data sources: `docs/ingestion-plan.md`

## Ground truths (locked - do not relitigate without a reason)

- **Agent:** Hermes Agent (Nous Research, MIT, Python), run as a managed container. Provides memory, skills, cron, MCP, and Discord natively.
- **Inference:** Claude via AWS Bedrock (per-token, paid by AWS credits). Tiered: Haiku 4.5 for triage/classify, Sonnet 4.6 for drafting, Opus only for hard reasoning.
- **Region:** eu-west-1 home, EU geo inference profiles (`eu.anthropic.*`) - keeps personal-data processing in-geography per the Bedrock geographic-CRIS doc; accepted possible ~10% premium over global.
- **Caching caveat (measured, not assumed):** Hermes does not emit cache checkpoints on the Bedrock path, so input tokens bill at full rate. Cost estimates must be measured via Langfuse/CloudWatch, not assumed. Future option: contribute Bedrock cachePoint support upstream.
- **Observability + evals:** Langfuse Cloud free tier. NOT self-hosted (self-hosting runs ~$150+/mo idle - a proven cost trap).
- **Corpus, two-tier (approved 2026-07-02):** raw data stays on the Mac, encrypted, NEVER pushed or synced anywhere. Only the derived working set (wiki/ + corpus.db + normalized/) deploys, point-to-point over SSM, to the box's encrypted EBS. Nothing corpus-related ever touches S3, git remotes, or third-party storage. Common format: one record = `{source, date, who, text}`.
- **Active window (2026-07-02):** the full corpus is memory (recall, facts, timeline); only the rolling last ~12 months defines voice exemplars, professional register, tendencies, coach baselines, and scorecard pairs. Older eras are context, never template.
- **Corpus versioning:** ~/twin-corpus is a LOCAL-ONLY git repo (raw/ untracked; normalized/ + wiki/ snapshotted per refresh; pre-push hook hard-fails so it can never leave the machine).
- **Retrieval contract:** all corpus access goes through the `corpus-search` CLI (shimmed on PATH; `tools/corpus_search.py`: query -> JSON lines). Backends: FTS5 + Cohere-multilingual-v3 embeddings in sqlite-vec. **Default mode: hybrid** (bake-off verdict 2026-07-03); drafting retrieval is audience-conditional. Skills and evals call only the contract.
- **Build order:** validate the whole twin ON THE MAC (index, wiki, gold pairs, local Hermes vs Bedrock) before creating any AWS resource beyond CLI auth + Bedrock access. AWS is lift-and-shift of a known-good config.
- **Channel (final, 2026-07-02):** Telegram = interactive home (official Bot API - stable for years, zero ban risk, free proactive, not blocked at work). Morning brief = real email send via Daniel's Gmail (SMTP app password, send-only; NEVER the Hermes email gateway adapter on his personal inbox - it marks all mail seen and polls). Discord dropped (blocked at work); WhatsApp Baileys optional later as a parallel channel (unofficial bridge: re-pairing + ban risk documented).
- **Eval-first:** build the scorecard before tuning anything. Nothing "improves" the twin unless it beats the scorecard.
- **Autonomy by reversibility:** act autonomously on read / search / research / draft; require human approval for send / spend / commit / anything irreversible.
- **Cost discipline:** credits go to compute (Bedrock + a one-off GPU for the fine-tune), not storage. Stop GPUs the moment a run ends. No idle managed services.

## Engineering rules - how we make decisions here

- **Ground every AWS design decision in the official AWS docs, and cite the doc.** Never decide infrastructure from memory.
- **Never hallucinate or invent** a service, API, flag, price, or limit. If unsure, look it up before writing it down.
- **"Better" requires proof.** Before choosing X over Y, show the real comparison - cost, docs, tradeoffs. "I assume there's a better way" is not a reason; prove it or don't claim it.
- **Think it through.** No unexamined assumptions on anything that costs money or is hard to reverse.
- Prose and commit conventions follow the global `~/.claude/CLAUDE.md` (no em dash, sentence-per-line in long markdown, no auto co-author on commits).

## Current state (update as it changes)

- **2026-07-03 (decision record + stepback #4 verdict):** Migration to the box executed BEFORE the data exports landed, overriding the documented gate - Daniel directed it ("when my computer is off it should still run - that's the whole point"); always-on beats waiting for data that arrives whenever. Gate override recorded here per process rules. Stepback #4 marching order adopted: **the milestone is "the loop runs unattended every morning and screams when it fails"** - cron + dead-man's switch outrank all other work. Also adopted: inbound-content-is-data-not-instructions rule (injection), secrets to SSM Parameter Store + compromise runbook, one-way skill sync (repo -> box; the box twin NEVER self-edits skills, it proposes diffs), Mac-side weekly corpus refresh to the box.

- **2026-07-03:** Phase 0 infra COMPLETE and verified. Box `i-0abed8b0182b8bc9e` (t4g.small, eu-west-1, encrypted, zero-inbound, SSM Online, swap) invokes Bedrock via instance role ("box-online" proven). Operating as `daniel-admin`. Email channel live (send-only, recipient-locked, tested). Bake-off concluded across 6 runs: hybrid = corpus-search default for Q&A; drafting retrieval is audience-conditional (on professional, light friends, OFF family); further lane-tuning stopped - benchmark resolution spent, production approval-labels are the next instrument. Corpus: 34,713 records + 25,473 vectors (Cohere multilingual v3, sqlite-vec). Pending human items: Telegram BotFather token, routines deletion, root MFA, IAM password rotation. Pending data: WhatsApp, Meta, Discord, TikTok exports. Migration of Hermes Mac→box happens after those land.

- **Live daily state (2026-07-03, post-audit):** Twin runs on the Mac as a **launchd-supervised service** (auto-restart; `hermes gateway status`). Telegram connected + paired (Daniel only, user 6309668956). Email channel live (send-only, recipient-locked). Corpus: 6 sources normalized, 34,713 records + 25,473 vectors. Skills + SOUL.md are **symlinked from this repo** into `~/.hermes/` - the repo is the single source of truth; the twin is instructed not to self-edit them. EC2 box **stopped** until migration day (data exports pending). Gold one-off tools archived in `tools/gold/`.
- **Documented decisions (were silent drift, now explicit):** terminal.backend stays `local` on the Mac (Docker not installed here; manual approvals are the interim guard - the box uses Docker per plan). `approvals.cron_mode: deny` stays; the brief's email send is not a dangerous-pattern command, verify when scheduling. Eval judge runs at temperature 0 as of today; earlier runs carried judge noise.
- **Next build (audit-ranked):** IMAP inbox reader + ICS calendar reader (the twin cannot see inbound yet), then schedule the morning brief. Everything else in the daily loop exists.
