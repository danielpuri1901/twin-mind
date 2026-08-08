# Twin Mind

A personal AI that learns from my own data, drafts in my voice, acts across my tools, and coaches me toward my best self.
I stay in the loop on everything it does.

Twin Mind only does the things a stateless chatbot cannot: it holds persistent memory of my life, it is proactive instead of purely reactive, and it works over my private data.
Everything else it would do worse than a general chatbot, so it does not try to.

## What it does

- **Morning brief** - a daily email at 07:30. Deterministic pipeline: facts are gathered by code (calendar, inbox triage, weather, recent AI news, the latest changelog entry), then exactly one constrained LLM call composes the sections, then code renders and sends it. The format, date, and counts are code-guaranteed, so the only thing left to evaluate is content quality.
- **Background prep** - a half-page dossier delivered before professional meetings, built from calendar plus the corpus.
- **Interactive chat** - a Telegram twin grounded in my corpus through automatic retrieval on every non-trivial turn.

## Architecture

- **Agent runtime:** Hermes Agent (Nous Research, MIT). Provides memory, skills, cron, and MCP.
- **Inference:** Claude via AWS Bedrock, tiered by task (Haiku for triage, Sonnet for drafting, Opus for hard reasoning). EU inference profiles keep personal-data processing in region.
- **Corpus + retrieval:** one record is `{source, date, who, text}`. Hybrid retrieval (BM25 + Cohere multilingual embeddings in sqlite-vec) fused with reciprocal rank fusion. Contextual embedding adds a deterministic metadata prefix to each chunk before embedding. All corpus access goes through one contract, the `corpus-search` CLI.
- **Observability + evals:** traces, datasets, and judge scores mirror to a hosted dashboard, while local files stay the source of truth.
- **Host:** a small always-on AWS box, reached over SSM only, with zero inbound. Derived data ships point-to-point; raw data never leaves my machine.

## Principles

- **Eval-first.** Build the scorecard before tuning anything. Nothing ships unless it beats the scorecard, enforced by a ship gate (`evals/eval.sh`) that must be green before deploy.
- **Deterministic by default.** Compute every fact in code and inject it into the prompt. The model judges and writes; it never computes a date, count, or lookup. When the model must return structured data, its shape is enforced with structured outputs, never scraped from text.
- **Human in the loop by reversibility.** Act autonomously on read, search, and draft. Require approval for send, spend, or anything hard to reverse.
- **Evals measure the actual job.** Each agent is graded against its own golden set for its own job, with one judge per failure mode, calibrated against my own labels.
- **One folder per agent.** Everything an agent is lives under `agents/<name>/`. Shared code is shared only when two or more agents use it.

## Repo map

| Path | What it holds |
|---|---|
| `agents/` | One folder per agent (brief, background-prep, chat): its skill, operations notes, and tools. |
| `shared/` | Cross-agent code: the corpus-search contract, structured-output helper, the SOUL. |
| `evals/` | The ship gate, calibrated judges, per-agent golden datasets, deterministic checks. |
| `pipeline/` | Data-prep that runs on my machine: source normalizers, chunking, embedding. |
| `infra/` | Box config, monitoring, and Hermes plugins (tracing, auto-retrieval). |
| `docs/` | Design docs, architecture map, and the changelog. |

## A note on data

This is a personal project. Raw personal data stays encrypted on my own machine and is never committed here; only code and derived, non-sensitive artifacts live in this repo.
