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
- **Retrieval contract:** all corpus access goes through the `corpus-search` CLI (`tools/corpus_search.py`: query -> JSON lines). Skills and evals call only that contract, so retrieval (FTS today, embeddings if evals ever demand) is swappable without touching anything else.
- **Build order:** validate the whole twin ON THE MAC (index, wiki, gold pairs, local Hermes vs Bedrock) before creating any AWS resource beyond CLI auth + Bedrock access. AWS is lift-and-shift of a known-good config.
- **Channel:** Discord (free proactive messages; avoids WhatsApp's template/approval wall).
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

- Corpus normalized so far: **iMessage** (20,583 msgs, 9,050 Daniel's) + **meeting transcripts** (16 meetings, 68,496 of Daniel's spoken words), at `~/twin-corpus/normalized/`.
- Normalizers built: `tools/normalize_imessage.py`, `tools/normalize_transcripts.py`. Common-format template proven.
- Incoming: Gmail (trimmed Takeout), WhatsApp (~3 days), Discord, Meta/TikTok, LinkedIn.
- Phase: starting **Phase 0** - AWS infra (Bedrock access, compute for Hermes, Discord, budget guardrails) + the scorecard.
