 # Twin Mind - Architecture Map

A full visual map of the system: where data lives, how the corpus becomes retrievable, the agents that run, the eval gates, and the governance rules.
View this in Zed, GitHub, or a Mermaid live editor to render the diagrams.

Ground truths this reflects: `CLAUDE.md`, `docs/2026-06-30-twin-mind-design.md`, `docs/2026-07-17-corpus-chunking-design.md`, `docs/CHANGELOG.md`.

---

## 1. System at a glance

Where the three worlds sit - the Mac (raw data + prep), the AWS box (the always-on twin), and the channels Daniel touches.

```mermaid
flowchart TB
    subgraph MAC["🖥️ Mac - private, source of truth"]
        RAW["raw corpus<br/>(iMessage, transcripts, email...)<br/>NEVER leaves the Mac"]
        PREP["pipeline/*<br/>normalize · chunk · embed · index"]
        REPO["repo: agents / skills / SOUL<br/>(one-way source of truth)"]
        RAW --> PREP
    end

    subgraph BOX["☁️ AWS box - i-0abed8b0182b8bc9e (eu-west-1, zero-inbound, SSM-only)"]
        HERMES["Hermes Agent runtime<br/>memory · skills · cron · MCP"]
        DERIVED["derived corpus<br/>index/ (vectors.db + corpus.db)<br/>+ datasets + wiki"]
        AGENTS["agents: chat · brief · background-prep · weekly-recap"]
        HERMES --- AGENTS
        DERIVED --- AGENTS
    end

    subgraph CLOUD["🧠 Managed services"]
        BEDROCK["AWS Bedrock<br/>Claude (EU profiles) · Cohere embed · Amazon rerank"]
        LANGFUSE["Langfuse Cloud<br/>traces + evals mirror"]
    end

    subgraph CHAN["📱 Channels"]
        TG["Telegram (interactive twin)"]
        GMAIL["Gmail SMTP (brief + recap, send-only)"]
    end

    PREP -->|"derived data only, over SSM"| DERIVED
    REPO -->|"one-way skill sync (repo -> box)"| HERMES
    AGENTS -->|inference| BEDROCK
    AGENTS -->|traces/scores| LANGFUSE
    AGENTS <--> TG
    AGENTS --> GMAIL

    classDef mac fill:#e8f0fe,stroke:#4285f4,color:#000
    classDef box fill:#fef7e0,stroke:#f9ab00,color:#000
    classDef cloud fill:#e6f4ea,stroke:#34a853,color:#000
    classDef chan fill:#fce8e6,stroke:#ea4335,color:#000
    class MAC,RAW,PREP,REPO mac
    class BOX,HERMES,DERIVED,AGENTS box
    class CLOUD,BEDROCK,LANGFUSE cloud
    class CHAN,TG,GMAIL chan
```

---

## 2. The RAG data pipeline (raw → retrievable)

How a message or meeting becomes something the twin can search.
This is the pipeline the 2026-07-21 work upgraded: windowed chunking + contextual embedding, promoted to production on both lanes.

```mermaid
flowchart LR
    subgraph SOURCES["Sources"]
        G["Granola meetings"]
        IM["iMessage"]
        GC["Google Chat"]
        EM["Gmail"]
        CAL["Google Calendar"]
        CON["Contacts"]
    end

    G -->|"fetch_granola.py"| INBOX["raw/transcripts-inbox/"]
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

Four agents on the Hermes runtime, each a folder under `agents/`. All read the corpus through `corpus-search`; all inference via Bedrock.

```mermaid
flowchart TB
    subgraph RT["Hermes runtime (box)"]
        direction TB
        CHAT["💬 chat - interactive twin<br/>Telegram, on-demand<br/>skills: daniel-corpus · learning-partner · research-papers"]
        BRIEF["📋 brief - morning email<br/>cron 07:30 · watchdog 07:50<br/>tools: prefetch · inbox_read · calendar_read · send_email · brief_check<br/>model: Sonnet"]
        PREP["🗂️ background-prep - meeting dossiers<br/>poller */15 · fires 75-15 min before pro meetings<br/>tools: scan_meetings · personal_circle filter"]
        RECAP["🗓️ weekly-recap - Friday reflection<br/>18:00 Telegram nudge -> 'done' gate -> ~19:30 email<br/>tools: nudge · recap · send_recap"]
    end

    CORPUS["corpus-search (hybrid retrieval)"]
    BED["Bedrock (Claude)"]
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

Nothing ships without the gate. Retrieval and generation are measured separately (RAGAS split); everything mirrors to Langfuse.

```mermaid
flowchart TB
    subgraph GATE["🚦 Ship gate - evals/eval.sh (mandatory before deploy)"]
        TT["tool tests (deterministic)"]
        REG["regression suite<br/>run_regression.py · bar = 100%"]
    end

    subgraph RETR["Retrieval eval (did we FETCH the right chunk?)"]
        RE["retrieval_eval.py<br/>source_recall@k (deterministic, home labels)"]
        RB["retrieval_braintrust.py<br/>the ablation ladder"]
        HC["hybrid_check.py<br/>promotion gate (hybrid mode)"]
    end

    subgraph GENR["Generation eval (did the LLM WRITE it right?)"]
        GE["generation_eval.py<br/>faithfulness + answer_correctness"]
    end

    subgraph BRIEFE["Brief/judge evals"]
        BB["run_brief_bench.py"]
        CS["calibrate_sections.py · judge_brief.py"]
        PB["run_prep_bench.py"]
    end

    subgraph PLAT["Observability + platforms"]
        BT["Braintrust (experiments)"]
        LF["Langfuse (traces + dataset mirror)"]
        CMP["evals/compare/ (braintrust · langfuse · arize · langsmith adapters)"]
        PUSH["push_to_langfuse.py"]
    end

    DS[("~/twin-corpus/datasets/<br/>corpus-qa · brief-verdicts · prep-verdicts ...")]

    DS --> RE & GE & BB
    RE --> RB --> BT
    RE --> HC
    GE --> BT
    BB --> CS
    DS --> PUSH --> LF
    CMP --> BT & LF
    GATE -.->|blocks deploy| SHIP["deploy to box"]

    classDef gate fill:#fce8e6,stroke:#ea4335,color:#000
    classDef eval fill:#fef7e0,stroke:#f9ab00,color:#000
    classDef plat fill:#e6f4ea,stroke:#34a853,color:#000
    class GATE,TT,REG,SHIP gate
    class RETR,GENR,BRIEFE,RE,RB,HC,GE,BB,CS,PB,DS eval
    class PLAT,BT,LF,CMP,PUSH plat
```

---

## 6. Governance and data flow (the rules that constrain everything)

The non-negotiables: raw data never leaves the Mac, the box never self-edits, humans approve anything irreversible.

```mermaid
flowchart LR
    subgraph MAC["Mac (trusted)"]
        RAW["raw corpus - encrypted, local-only git"]
        DERIVE["derive: normalize + index"]
        RAW --> DERIVE
    end

    subgraph BOX["Box (derived only)"]
        IDX["index/ + wiki + datasets"]
        SKILLS["skills / SOUL (read-only mirror)"]
    end

    RAW -. "NEVER (pre-push hook hard-fails)" .-> X1["S3 / git remote / SaaS"]
    DERIVE -->|"SSM, point-to-point"| IDX
    REPO2["repo (source of truth)"] -->|"one-way sync"| SKILLS
    SKILLS -. "twin proposes diffs, human approves" .-> REPO2

    subgraph HITL["Human-in-the-loop gates"]
        READ["read / search / draft -> autonomous"]
        SEND["send / spend / commit / IAM -> approval"]
    end

    classDef mac fill:#e8f0fe,stroke:#4285f4,color:#000
    classDef box fill:#fef7e0,stroke:#f9ab00,color:#000
    classDef stop fill:#fce8e6,stroke:#ea4335,color:#000
    class MAC,RAW,DERIVE mac
    class BOX,IDX,SKILLS,REPO2 box
    class X1,HITL,READ,SEND stop
```

---

## Legend / key facts

| Thing | Value |
|---|---|
| Box | EC2 `i-0abed8b0182b8bc9e`, t4g.small, eu-west-1, zero-inbound, SSM-only, role `twin-mind-role` |
| Agent framework | Hermes (Nous Research) - memory, skills, cron, MCP |
| Inference | Bedrock: Claude EU profiles (Sonnet drafting / Haiku triage), Cohere embed-multilingual-v3, Amazon rerank (eu-central-1) |
| Retrieval | Hybrid (FTS5 + sqlite-vec + RRF) via `corpus-search`; windowed + contextual chunks (promoted 2026-07-21) |
| Observability | Langfuse Cloud (free tier); Braintrust for experiments |
| Channels | Telegram Bot API (interactive), Gmail SMTP (brief + recap, send-only, recipient-locked) |
| Hard rules | raw stays on Mac · one-way skill sync · ship gate green before deploy · approval for send/spend/irreversible |
