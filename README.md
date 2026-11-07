# Twin Mind

I am restrained by what I can remember at once.
Twin Mind turns my private history into useful context for each day.

## Explore the system

[Open the agent coordination map](https://danielpuri1901.github.io/twin-mind/agent-coordination.html)

The source lives at [`docs/agent-coordination.html`](docs/agent-coordination.html).
It runs as one standalone page with no server setup.

## What it does

- **Morning brief:** Produces one daily email from calendar events, inbox signals, weather, recent AI work, and project activity.
  Action items require source evidence and an explicit state.
  Unread flags do not establish urgency or completion.
- **Background prep:** Creates a short dossier before professional meetings.
  Code does the research.
  Two model calls with no tools write the text.
- **Interactive chat:** Runs on self-hosted Letta Code behind a Telegram bot.
  It keeps long-term memory and grounds replies in a private personal corpus.
- **Weekly recap:** Collects build progress, the week's meetings, and personal reflection into one review.
- **Meeting ingest:** Pulls finished meetings from Wispr Flow every 4 hours, so transcripts become searchable context.

Twin Mind focuses on tasks that need persistent memory, proactive timing, private context.
A general chatbot remains better for isolated questions.

## How one request works

```text
systemd timer                      Telegram message
(brief, watchdog, meeting prep)    (chat)
        |                                  |
        v                                  v
script on the box                  Letta Code, twin-chat.service
        |                                  |
        +--> code gathers facts            +--> mod retrieves corpus context each turn
        +--> corpus-search retrieves       +--> tools: corpus, code, email, web search
        +--> Anthropic API writes          +--> Anthropic API writes
             constrained text              +--> chat log records each message
        +--> checks validate output
        +--> approved channel delivers
        |                                  |
        +----------------+-----------------+
                         v
                Langfuse traces + task-specific evals
```

Chat tracing through the chat log is not built yet.

Code computes dates, counts, lookups, delivery rules.
Models handle judgment plus writing.
Structured model responses use schemas instead of text parsing.

Only chat is an agent.
The other jobs are plain scripts that systemd starts.
Chat reaches the corpus through a narrow sudo rule, and its OS user has no access to the instance role, the env file or the corpus files.
The bridge between Letta and the rest of the system is one file, `agents/chat/mods/twin_mind.ts`.
Chat messages go to `/var/lib/twin-chat/chat-log.jsonl`, and the corpus ingest and the weekly recap read that log.

## Memory

The private AWS host holds the canonical working corpus.
Raw archives and derived corpus data are backed up to private S3 storage under the current storage policy.
The policy requires a customer-managed encryption key, versioning, blocked public access, access logging, and restricted bucket access.
Personal corpus records do not belong in the public code repository.

The canonical export includes a manifest of source counts and checksums.
Indexes are derived from that export.
The twin's conversations are ingested from the chat log on a timer, so memory does not depend on a session ending.
The chat agent also keeps its own memory in Letta's git-backed memory files.
Two files load every turn.
The rest load on demand.

All corpus access uses one command:

```bash
corpus-search "query" --k 20
```

The retrieval layer combines full-text search, multilingual embeddings, reciprocal-rank fusion.
Recent material guides voice plus current behavior.
Older material remains available as historical context.

## Evaluation

Free tests block every image build.
Alerts reach Telegram when a job fails or goes silent.
The rule for any new check is in `docs/eval-doctrine.md`.

Run free checks directly:

```bash
python3 evals/test_tools.py
python3 evals/test_prep_scan.py
python3 evals/test_brief_check.py
python3 evals/test_wispr_ingest.py
python3 evals/test_recap_meetings.py
```

The full ship gate calls the Anthropic API, so it can create a small model charge.
`infra/deploy_box.sh` runs it on the box before every deploy and stops if it is red.
`infra/check_box.sh` proves that the box matches `main`.

```bash
evals/eval.sh
```

## Repository map

| Path | Purpose |
| --- | --- |
| `agents/` | One folder per production agent. |
| `shared/` | Corpus access, structured output, shared policy. |
| `evals/` | Free tests, the regression suite and retrieval benchmarks. |
| `pipeline/` | Data normalization, chunking, embedding, plus the box-side meeting ingester. |
| `infra/` | Private host templates, systemd units, sudo rule, monitoring. Hermes plugins stay for rollback. |
| `docs/` | Design records, visual maps, technical decisions. |

## Configuration

Copy the safe environment example:

```bash
cp .env.example .env
set -a
source .env
set +a
```

Fill the local file with your own values.
Git ignores `.env`, private keys, AWS credentials, local state, personal corpus files.

Copy the safe instance example only when a local script needs an EC2 target:

```bash
cp infra/instance-id.example.txt infra/instance-id.txt
```

Runtime secrets belong in a private environment file, AWS Systems Manager Parameter Store, the relevant managed secret store.
See [`SECURITY.md`](SECURITY.md) before reporting a possible credential leak.

## Status

This is a personal research system.
Its architecture changes when production feedback exposes a better design.
