# Twin Mind

I am restrained by what I can remember at once.
Twin Mind turns my private history into useful context for each day.

## Explore the system

[Open the agent coordination map](https://danielpuri1901.github.io/twin-mind/agent-coordination.html)

The source lives at [`docs/agent-coordination.html`](docs/agent-coordination.html).
It runs as one standalone page with no server setup.

## What it does

- **Morning brief:** Produces one daily email from calendar events, inbox signals, weather, recent AI work, project activity.
- **Background prep:** Creates a short dossier before professional meetings.
- **Interactive chat:** Grounds Telegram replies in a private personal corpus.
- **Weekly recap:** Collects build progress plus personal reflection into one review.

Twin Mind focuses on tasks that need persistent memory, proactive timing, private context.
A general chatbot remains better for isolated questions.

## How one request works

```text
Schedule / Telegram
        |
        v
Hermes Agent
        |
        +--> skill selects task
        +--> code gathers facts
        +--> corpus-search retrieves context
        +--> Bedrock generates constrained text
        +--> deterministic checks validate output
        +--> approved channel delivers result
        |
        v
Langfuse traces + task-specific evals
```

Code computes dates, counts, lookups, delivery rules.
Models handle judgment plus writing.
Structured model responses use schemas instead of text parsing.

## Memory

Raw personal data stays encrypted on the local machine.
Only a derived working set reaches the private AWS host through SSM.
No corpus data belongs in Git, S3, logs, third-party datasets.

All corpus access uses one command:

```bash
corpus-search "query" --k 20
```

The retrieval layer combines full-text search, multilingual embeddings, reciprocal-rank fusion.
Recent material guides voice plus current behavior.
Older material remains available as historical context.

## Evaluation

Each agent has its own job-specific dataset.
Deterministic checks run first.
Calibrated model judges cover subjective failures only.
Human labels remain the reference point.

Run free checks directly:

```bash
python3 evals/test_tools.py
python3 evals/test_prep_scan.py
python3 evals/test_brief_check.py
python3 evals/test_granola_fetch.py
```

The full ship gate uses Bedrock, so it can create a small model charge:

```bash
evals/eval.sh
```

## Repository map

| Path | Purpose |
| --- | --- |
| `agents/` | One folder per production agent. |
| `shared/` | Corpus access, structured output, shared policy. |
| `evals/` | Regression checks, judges, job-specific evaluation tools. |
| `pipeline/` | Local data normalization, chunking, embedding. |
| `infra/` | Private host templates, monitoring, runtime plugins. |
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
