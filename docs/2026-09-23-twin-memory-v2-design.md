# Twin Mind memory v2: per-day sessions, corpus-backed recall

Status: approved 2026-09-23. Supersedes the corpus storage rule of 2026-07-02.

## Outcome

The twin remembers Daniel across days without depending on a context window surviving.
Every day is one session.
When the day closes, the conversation is written into the corpus.
Anything older than yesterday is retrieved, not injected.

## Why

The twin's long-term memory is currently the context window of a single session.
That session, `20260720_085317_380aeb85`, opened on 2026-07-20 and has never closed.
It holds 56 active messages and 2,259 compacted ones, and it has read 16.3 million cached tokens.

Three sources agree this is the wrong shape.

LangChain separates thread-scoped short-term memory from cross-session long-term memory held in namespaced stores, and names three kinds: semantic (facts), episodic (experiences) and procedural (instructions).
It also warns that long histories make models lose accuracy on stale content while costing more and answering slower.

Anthropic's agent design reference is more direct.
Context editing prunes stale turns and compaction summarises near the limit, but both work **inside** one session.
Memory is the only cross-session mechanism.
Its memory stores are many small text files, each immutably versioned.

OpenAI adds one rule that matters here: chaining turns with `previous_response_id` carries the conversation but not the instructions, which are re-sent every turn.

Mapping those three kinds onto what Twin Mind has today: semantic lives in the corpus and wiki, procedural lives in SOUL.md and the skills, and episodic lives nowhere.
That is the gap this design fills.

The cost of the current shape is already visible.
`~/.hermes/memories/MEMORY.md`, written on 2026-09-01, states that corpus retrieval is keyword-only with no vector database.
That is false: the retrieval contract is hybrid and `vectors.db` is 118MB.
Anthropic's own warning explains why this persists: memories are returned verbatim into every later context, so one wrong fact replays forever.

## Decisions

| Decision | Choice |
| --- | --- |
| Corpus storage | S3, all tiers including raw |
| Episodic store | The corpus, as a new `twin-chat` source |
| Session boundary | Hard daily cut at 04:00 Europe/Amsterdam |
| Day-start context | Mechanical, no model call |
| Older context | Retrieved through `corpus-search` |

The storage decision amends the two-tier rule approved on 2026-07-02, which kept raw data on the Mac and forbade any corpus data in S3.
Daniel changed that rule on 2026-09-23 after being told that the derived tier holds verbatim message text, and that raw includes health, legal, identity and financial material.

## Components

### 1. Corpus in S3

One bucket, `twin-corpus-<account-id>`, in eu-west-1, holding `raw/`, `normalized/`, `wiki/` and `index/`.

Controls, all required before any upload:

- Encryption with a customer-managed KMS key, not the AWS-managed one, so key use is auditable and revocable.
- Versioning on, so a bad sync cannot destroy history.
- Block public access on, at the bucket level.
- A bucket policy that denies any request without TLS, and denies every principal outside the account.
- Server access logging to a separate bucket.

The Mac pushes `raw/`.
The box reads and writes the derived tiers.

### 2. Daily cut

A timer closes the open session at 04:00 Europe/Amsterdam.
The next message opens a new one.

The supported trigger for this is not yet known.
`hermes sessions` exposes list, export, delete, prune, rename and browse, but no close or reset, and `config.yaml` has no session timeout.
The session history shows both `agent_close` and `session_reset` as end reasons, so the capability exists inside Hermes.
Finding the trigger is the first task of the implementation plan, because every other component depends on it.

### 3. chat-ingest

A systemd timer on the box, modelled on the existing `summary-ingest.timer`.

After the cut it runs `hermes sessions export --source telegram`, which writes JSONL and avoids reading `state.db` internals.
Each message becomes a corpus record of the standard shape, `{source: "twin-chat", chat, date, who, sender, text}`.
Records append to `normalized/twin-chat.jsonl` and are upserted into `index/corpus.db`, then synced to S3.

The job keys on message id, so running it twice changes nothing.

### 4. Day-start block

A shell hook declared in `~/.hermes/config.yaml`.
No hooks are configured today, so this is the first one.

It emits, with no model call:

- Yesterday's last N exchanges, verbatim.
- Open threads, defined mechanically as Daniel's messages from the last day that end in a question, plus anything he marked explicitly.

The block has a hard token cap and truncates oldest first.
A mechanical block cannot invent Daniel's own history back at him, which a generated digest can.

### 5. Staleness alarm

Any corpus source with no new record for N days sends one Telegram message.

This exists because the failure mode has already happened twice.
Corpus ingestion stopped in July and nothing reported it.
The classic video track answered "empty" every day for a week and nothing reported that either.
Silence must never mean broken.

### 6. MEMORY.md demoted

`MEMORY.md` stops holding facts and holds pointers to what is searchable.
Facts belong in the corpus, where they carry a source and a date and can be corrected.

## Open question

The two corpora disagree.
The box's `corpus.db` is 20MB and holds 1,526 iMessage records.
The Mac's is 277MB and holds 20,583.

The default assumption for implementation is that the Mac's copy is canonical for history, and the box's live additions merge into it.
This must be confirmed before anything is promoted to canonical in S3, or the migration will faithfully preserve a subset and call it Daniel's memory.

## Risks

Putting raw data in S3 widens the blast radius of any key or policy error.
Raw includes health, legal, identity and financial documents.
The controls above are the mitigation, and they are required rather than recommended.

Uploaded objects should be treated as permanently outside the Mac, even after deletion.
