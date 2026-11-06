 # Twin Mind - Architecture Map

A full visual map of the system: where data lives, how the corpus becomes retrievable, the agents that run, the eval gates, and the governance rules.
View this in Zed, GitHub, or a Mermaid live editor to render the diagrams.

Ground truths this reflects: `CLAUDE.md`, `docs/2026-06-30-twin-mind-design.md`, `docs/2026-07-17-corpus-chunking-design.md`, `docs/CHANGELOG.md`.

---

## 1. System at a glance

Where the three worlds sit - the Mac (data prep), the AWS box (the always-on twin), and the channels Daniel touches.
Since 2026-09-23 the corpus, raw tier included, is also backed up to a private encrypted S3 bucket (see `CLAUDE.md`).

```mermaid
flowchart TB
    subgraph MAC["🖥️ Mac - data prep"]
        RAW["raw corpus<br/>(iMessage, transcripts, email...)"]
        PREP["pipeline/*<br/>normalize · chunk · embed · index"]
        REPO["repo: agents / skills / SOUL<br/>(source of truth for code)"]
        RAW --> PREP
    end

    subgraph BOX["☁️ AWS box (eu-west-1, zero-inbound, SSM-only)"]
        LETTA["twin-chat.service<br/>Letta Code (chat agent, own OS user)<br/>MemFS memory"]
        TIMERS["systemd timers<br/>brief · watchdog · meeting prep"]
        DERIVED["corpus<br/>index/ (vectors.db + corpus.db)<br/>+ datasets"]
        AGENTS["agents: chat · brief · background-prep · weekly-recap"]
        LETTA --- AGENTS
        TIMERS --- AGENTS
        DERIVED --- AGENTS
    end

    subgraph CLOUD["🧠 Managed services"]
        ANTHROPIC["Anthropic API<br/>Claude (Sonnet 5.5 drafting, Haiku 4.5 compression)"]
        BEDROCK["AWS Bedrock<br/>Cohere embed · Amazon rerank"]
        LANGFUSE["Langfuse Cloud<br/>traces + evals mirror"]
    end

    subgraph CHAN["📱 Channels"]
        TG["Telegram (interactive twin)"]
        GMAIL["Gmail SMTP (brief + recap, send-only)"]
    end

    PREP -->|"derived data, over SSM"| DERIVED
    REPO -->|"files copied by hand over SSM"| AGENTS
    AGENTS -->|inference| ANTHROPIC
    AGENTS -->|embeddings| BEDROCK
    AGENTS -->|traces/scores| LANGFUSE
    AGENTS <--> TG
    AGENTS --> GMAIL

    classDef mac fill:#e8f0fe,stroke:#4285f4,color:#000
    classDef box fill:#fef7e0,stroke:#f9ab00,color:#000
    classDef cloud fill:#e6f4ea,stroke:#34a853,color:#000
    classDef chan fill:#fce8e6,stroke:#ea4335,color:#000
    class MAC,RAW,PREP,REPO mac
    class BOX,LETTA,TIMERS,DERIVED,AGENTS box
    class CLOUD,ANTHROPIC,BEDROCK,LANGFUSE cloud
    class CHAN,TG,GMAIL chan
```

---

## 2. The RAG data pipeline (raw → retrievable)

How a message or meeting becomes something the twin can search.
This is the pipeline the 2026-07-21 work upgraded: windowed chunking + contextual embedding, promoted to production on both lanes.

```mermaid
flowchart LR
    subgraph SOURCES["Sources"]
        W["Wispr Flow meetings<br/>(official read-only MCP)"]
        G["Granola meetings<br/>(retired 2026-09, history kept)"]
        IM["iMessage"]
        GC["Google Chat"]
        EM["Gmail"]
        CAL["Google Calendar"]
        CON["Contacts"]
    end

    G -->|"historical transcripts"| INBOX["raw/transcripts-inbox/"]
    INBOX -->|"normalize_transcripts.py"| NORM
    IM -->|normalize_imessage.py| NORM
    GC -->|normalize_gchat.py| NORM
    EM -->|normalize_gmail.py| NORM
    CAL -->|normalize_gcal.py| NORM
    CON -->|normalize_contacts.py| NORM

    NORM["normalized/*.jsonl<br/>one record = {source, chat, date, who, text}"]

    NORM -->|"chunk_conversations.py<br/>(window by chat-day + speaker)"| WIN["normalized-windowed/"]
    WIN -->|"add_context.py<br/>(prepend [meeting · date])"| CTX["normalized-windowed-ctx/"]

    CTX -->|"embed_corpus.py<br/>Cohere embed-multilingual-v3 (Bedrock)"| VEC[("vectors.db<br/>sqlite-vec, 1024-dim")]
    CTX -->|"build_index.py<br/>FTS5"| FTS[("corpus.db<br/>keyword index")]

    W -->|"ingest_wispr_meetings.py<br/>(box, every 4h, same windowing + context prefix,<br/>incremental inserts, never a rebuild)"| FTS
    W -->|"ingest_wispr_meetings.py"| VEC

    VEC --> SEARCH
    FTS --> SEARCH
    SEARCH["shared/corpus_search.py<br/>THE retrieval contract"]

    classDef src fill:#e8f0fe,stroke:#4285f4,color:#000
    classDef proc fill:#fef7e0,stroke:#f9ab00,color:#000
    classDef db fill:#e6f4ea,stroke:#34a853,color:#000
    class G,IM,GC,EM,CAL,CON src
    class NORM,WIN,CTX proc
    class VEC,FTS,SEARCH db
```

---

## 3. Inside the retriever (hybrid search)

What `corpus-search` actually does for one query. Default mode = hybrid.
The reranker rung was **built and measured but declined** (marginal gain), so it is not in the live path.

```mermaid
flowchart TB
    Q["query"] --> EMB["embed query<br/>Cohere search_query (Bedrock)"]
    Q --> KW["tokenize / FTS5 query"]

    EMB --> VECL["vector lane<br/>sqlite-vec KNN over vectors.db"]
    KW --> LEXL["lexical lane<br/>BM25 over corpus.db"]

    VECL --> RRF["Reciprocal Rank Fusion<br/>1/(60+rank), summed"]
    LEXL --> RRF
    RRF --> TOPK["top-k results<br/>{source, chat, date, who, text, score}"]
    TOPK --> RR["reranker<br/>(amazon.rerank-v1, Frankfurt)"]

    RR -.->|"DECLINED 2026-07-21<br/>+1 question only, not worth latency"| X["not in production"]
    TOPK ==>|"live path"| OUT["-> agents / evals"]

    classDef live fill:#e6f4ea,stroke:#34a853,color:#000
    classDef dead fill:#f1f3f4,stroke:#9aa0a6,color:#000,stroke-dasharray: 4 4
    class Q,EMB,KW,VECL,LEXL,RRF,TOPK,OUT live
    class RR,X dead
```

---

## 4. The agents (what runs, when)

Four agents, each a folder under `agents/`. Only chat is a long-running agent, on Letta Code. The other three are scripts that systemd timers start.
All read the corpus through `corpus-search`; all Claude inference goes through the Anthropic API (`shared/claude.py`), embeddings through Bedrock.

```mermaid
flowchart TB
    subgraph RT["Box"]
        direction TB
        CHAT["💬 chat - interactive twin<br/>Letta Code, Telegram, on-demand<br/>bridge: mods/twin_mind.ts<br/>tools: corpus · code · email · web search, web fetch (approval)<br/>log: /var/lib/twin-chat/chat-log.jsonl"]
        BRIEF["📋 brief - morning email<br/>systemd timer 07:30 · watchdog 07:50<br/>script: compose_brief.py (one model call)<br/>tools: prefetch · inbox_read · calendar_read · send_email · brief_check<br/>model: Sonnet"]
        PREP["🗂️ background-prep - meeting dossiers<br/>systemd timer every 15 min · fires 75-15 min before meetings<br/>code: scan_meetings · compose_prep (research in code, 2 no-tool model calls)"]
        RECAP["🗓️ weekly-recap - Friday reflection<br/>18:00 Telegram nudge -> 'done' gate -> ~19:30 email<br/>tools: nudge · recap · send_recap<br/>reads the chat log"]
    end

    CORPUS["corpus-search (hybrid retrieval)"]
    BED["Anthropic API (Claude)"]
    TG["Telegram"]
    MAIL["Gmail SMTP"]

    CHAT --> CORPUS
    BRIEF --> CORPUS
    PREP --> CORPUS
    RECAP --> CORPUS
    CHAT & BRIEF & PREP & RECAP --> BED

    CHAT <--> TG
    RECAP -->|nudge| TG
    RECAP -->|recap| MAIL
    BRIEF -->|brief| MAIL
    PREP -->|dossier| TG

    classDef agent fill:#fef7e0,stroke:#f9ab00,color:#000
    classDef svc fill:#e6f4ea,stroke:#34a853,color:#000
    class CHAT,BRIEF,PREP,RECAP agent
    class CORPUS,BED,TG,MAIL svc
```

---

## 5. The eval stack

The rule is that nothing ships without the gate. The gate is run by hand, because there is no deploy CI. Retrieval and generation are measured separately (RAGAS split); everything mirrors to Langfuse.

```mermaid
flowchart TB
    subgraph GATE["🚦 Ship gate - evals/eval.sh (rule, run by hand)"]
        TT["free tests (deterministic)"]
        REG["regression suite<br/>run_regression.py · bar = 100%"]
    end

    subgraph RETR["Retrieval benchmarks (by hand, before a retrieval change)"]
        RE["retrieval_eval.py<br/>source_recall@k (deterministic, home labels)"]
        LM["longmemeval_retrieval.py"]
    end

    DS[("~/twin-corpus/datasets/<br/>corpus-qa ...")]

    DS --> RE
    GATE -.->|"rule, run by hand"| SHIP["deploy to box (files copied over SSM)"]

    classDef gate fill:#fce8e6,stroke:#ea4335,color:#000
    classDef eval fill:#fef7e0,stroke:#f9ab00,color:#000
    class GATE,TT,REG,SHIP gate
    class RETR,RE,LM,DS eval
```

---

## 6. Governance and data flow (the rules that constrain everything)

The non-negotiables: the corpus leaves the Mac only to the controlled S3 bucket, never to a code remote.
The chat agent cannot reach secrets or the corpus files.
Humans approve anything irreversible.

```mermaid
flowchart LR
    subgraph MAC["Mac"]
        RAW["raw corpus - local git, raw/ untracked"]
        DERIVE["derive: normalize + index"]
        RAW --> DERIVE
    end

    subgraph BOX["Box"]
        IDX["corpus index/ + datasets"]
        JOBS["scripts and timers (job user)"]
        CHATU["chat agent (twin-chat OS user)"]
    end

    S3["private S3 bucket<br/>KMS key, versioning, no public access, TLS only, access logs"]

    RAW -. "NEVER (pre-push hook hard-fails)" .-> X1["git remote / SaaS"]
    RAW -->|"corpus sync"| S3
    DERIVE -->|"SSM, point-to-point"| IDX
    IDX -->|"corpus sync, failed snapshots block upload"| S3
    CHATU -->|"narrow sudo rule: search tools only"| JOBS
    CHATU -. "no instance role, no .env, no corpus files" .-> X2["secrets"]

    subgraph HITL["Human-in-the-loop gates"]
        READ["read / search / draft -> autonomous"]
        SEND["send / spend / commit / IAM / web fetch -> approval"]
    end

    classDef mac fill:#e8f0fe,stroke:#4285f4,color:#000
    classDef box fill:#fef7e0,stroke:#f9ab00,color:#000
    classDef stop fill:#fce8e6,stroke:#ea4335,color:#000
    class MAC,RAW,DERIVE mac
    class BOX,IDX,JOBS,CHATU,S3 box
    class X1,X2,HITL,READ,SEND stop
```

---

## Legend / key facts

| Thing | Value |
|---|---|
| Box | One private EC2 host, t4g.small, eu-west-1, zero-inbound, SSM-only. Not a git checkout; deploys are files copied by hand over SSM |
| Chat agent | Letta Code 0.34.41, self-hosted, `twin-chat.service`, own OS user `twin-chat`, Sonnet 5.5. Bridge: `agents/chat/mods/twin_mind.ts`. Chat log: `/var/lib/twin-chat/chat-log.jsonl` (`shared/chat_log.py`). Hermes is stopped, kept for rollback |
| Scheduled jobs | systemd timers (`infra/systemd/`): morning-brief, morning-brief-watchdog, meeting-prep-poller |
| Inference | Anthropic API since 2026-10-22: Claude Sonnet 5.5 drafting (since 2026-10-23), Haiku 4.5 compression; key from Secrets Manager `aws-inference`. Bedrock keeps Cohere embed-multilingual-v3 and Amazon rerank (eu-central-1) |
| Retrieval | Hybrid (FTS5 + sqlite-vec + RRF) via `corpus-search`; windowed + contextual chunks (promoted 2026-07-21) |
| Observability | Langfuse Cloud (free tier) is the only trace store |
| Channels | Telegram Bot API (interactive), Gmail SMTP (brief + recap, send-only, recipient-locked) |
| Hard rules | corpus never to a code remote · ship gate green before deploy (by hand) · approval for send/spend/irreversible and for each web fetch |
