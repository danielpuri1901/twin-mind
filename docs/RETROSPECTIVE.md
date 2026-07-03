# Twin Mind - the story so far (Jun 30 - Jul 3, 2026)

Written for Daniel to re-read when lost. One chapter per arc; every claim measured or cited.

## Chapter 0 - The idea and the rules (Jun 30)

Started as "what should I do with $1k AWS credits."
Landed on: a personal AI twin - knows everything about me, triages my inbound, drafts in my voice, coaches me toward my best self, and I stay in the loop on everything.
Three goals, in priority order: (1) learn to build RELIABLE agents (career capital), (2) a daily-useful assistant, (3) the long-term digital twin.
The first independent cold review reshaped everything with one idea: **build the ruler before the diet** - you cannot improve what you cannot measure, so evals come before features.
Stack decisions, each with a reason: Hermes Agent harness (buy the plumbing, own the crown jewels: corpus + evals), Claude on AWS Bedrock (per-token, credits, EU), Langfuse Cloud free (tracing + evals without a $150/mo self-host trap), everything else = small auditable Python CLIs.
Standing rules written into CLAUDE.md: ground every decision in docs, prove comparisons, simplest-deterministic-auditable wins, human approval for anything irreversible.

## Chapter 1 - The corpus (Jun 30 - Jul 2)

Indexed the entire Mac: 161,381 files - and learned ~90% is code/dependency noise; the real "me" is ~14k documents.
Freed 20 GB of disk (caches, node_modules, old videos) to make room.
Ingested and normalized six sources into ONE common format ({source, date, who, text}):
iMessage 20,583 messages (2023-2026) · meeting transcripts 6,558 turns = 68,496 of my spoken words · Gmail 58,903 scanned, 53k newsletter-noise dropped, 5,421 kept (1,105 sent = my writing voice, 2017-2026) · Google Chat 1,563 (2017-2020, school era) · calendar 367 events · contacts 221.
**Total: 34,713 records.**
An LLM compiled the corpus into a human-readable wiki: voice-profile (how I write AND speak, cited), 13 people pages, topic pages (job search, Routes AI, thesis, family), timelines.
Privacy architecture: two-tier - raw exports NEVER leave the Mac; only the derived working set travels. Corpus is a local-only git repo with a hook that physically blocks pushing.

## Chapter 2 - The agent lives (Jul 2)

Hermes installed on the Mac; brain = Claude Sonnet 4.6 via Bedrock eu-west-1 (EU inference profiles - personal data stays in-geography, decided deliberately over a ~10% price delta).
Lockdown from birth: manual approval on dangerous commands, cron denied dangerous commands, later a Telegram allowlist of exactly one human.
First proof of life: asked "what did I discuss with Max Hammer in June?" - the twin ran 28 tool calls over the corpus and reconstructed the whole CrowdVolt interview, cited.
Retrieval design: ALL corpus access through one CLI contract (corpus-search -> JSON lines), so the backend can be swapped without touching anything else. This decision paid off twice later.

## Chapter 3 - The ruler (Jul 2-3)

Daniel curated 32 real "message in -> what I actually replied" pairs, tagged by audience (family / close friend / professional).
Built a judge (LLM, later pinned to temperature 0) scoring three axes: content (right thing said), fidelity (sounds like me FOR THIS AUDIENCE), aspiration (me at my clearest - weighted on professional).
Ran SIX experiments in one evening (~$0.40 each, all traced):
baseline -> +full context -> +lexical retrieval (noisy) -> denoised corpus -> semantic -> hybrid.
What the data said: full conversation context fixed family content (0.00 -> 0.37); retrieval helps professional (+0.05) and HURTS family (noise injection); casual misses are mostly facts-not-in-corpus (a measured ceiling, not a bug); semantic search finds meaning-level matches lexical can't ("bday" ~ "birthday party").
Verdicts DEPLOYED: hybrid = default for Q&A; drafting retrieval is audience-conditional (on professional, light friends, OFF family); stop tuning - at n=32 further deltas are judge noise; production labels are the next instrument.
Cost measured, not guessed: ~$0.007 per chat turn (prompt caching verified working on Bedrock), ~$0.25-1.00/day realistic. Credits last years.

## Chapter 4 - The audit (Jul 3 morning)

A cold simplicity/determinism review found the uncomfortable truth: we had measured, concluded, and NOT deployed - the live twin ran stale instructions; it had even self-edited its own skill file with facts that later went stale.
Root cause: two unsynchronized copies of the twin's brain (repo vs ~/.hermes).
Fixes, same day: the repo became the single source of truth (skills symlinked in, twin forbidden from self-editing), gateway became a supervised service, judge pinned to temp 0, dead code deleted, the empty-but-running EC2 box stopped, every doc de-drifted.
Lesson that now defines the project: drift is the default; audits + single-source-of-truth are the cure.

## Chapter 5 - Senses and channels (Jul 3 afternoon)

Telegram: official bot, paired to exactly one user (Daniel), chosen after Discord (blocked at work) and WhatsApp (unofficial-bridge ban risk) - stability won.
Voice: local faster-whisper on the Mac - voice notes transcribed WITHOUT leaving the machine; zero API, zero cost.
Email: real SMTP sends via app password, recipient HARD-LOCKED to Daniel in code (external sends physically refused).
Inbox: read-only IMAP reader that can never mark mail seen. Calendar: read-only secret-ICS reader (with recurring-event expansion).
Connectors: Notion + Granola via MCP OAuth; web search pinned deterministically (search=Tavily, extraction=Firecrawl - benchmarked choice).
**The first live morning brief ran**: scanned 26 emails, surfaced the right things, drafted a reply in Daniel's voice, sent itself to his inbox, verified its own delivery.
It also made TWO staleness errors (treated an already-happened call and a moved defense date as live).
Same day, the errors became: a regression dataset (twin-triage-v1: source-coverage + recency-resolution failure classes) + two new skill rules (latest-state check; consult Granola for anyone with a pending meeting).
That is the flywheel working: production error -> eval case + fix, same day.

## Chapter 6 - Always-on (Jul 3 evening)

The question that forced the move: "if I close my Mac, does the twin die?" Yes - so migration.
The box: EC2 t4g.small, eu-west-1, ZERO inbound ports (SSM-only), encrypted disk, IAM-role-only credentials, Docker sandbox for the twin's shell (a control the Mac never had).
393 MB deployed through an encrypted tunnel: corpus working set, repo, secrets, OAuth tokens, the twin's memories.
Cutover executed in single-owner order (Mac gateway killed BEFORE box gateway started - one bot, one owner).
**The twin now runs 24/7 in Ireland.** The Mac demotes to corpus factory (iMessage lives there; refreshes sync to the box).
Stepback #4 landed the hardest verdicts yet: (1) "your process documents are better than your process" - the migration overrode our own written gate without recording why (now recorded); (2) the product ran ONCE in six days - the milestone is not infrastructure, it is "the loop runs unattended every morning and screams when it fails"; (3) prompt injection was unaddressed - inbound email is untrusted and web-fetch is an exfil channel (rules added to the twin's soul same hour); (4) secrets need Parameter Store + a compromise runbook; (5) corpus staleness is structural until refresh automation exists.

## The architecture, as of tonight

```
Phone (Telegram / voice notes / email)
        │
        ▼
EC2 box, always-on (Ireland) - zero inbound, SSM-only, encrypted
  Hermes gateway (system service)
  skills+SOUL from the repo (one-way sync, twin cannot self-edit)
  corpus working set: 34,713 records + 25,473 vectors (sqlite files)
  corpus-search contract (hybrid default)  ·  Docker sandbox
        │ outbound only
        ├─▶ Bedrock (Claude, EU, instance role - no keys)
        ├─▶ Langfuse (traces, evals, datasets)
        └─▶ Tavily / Firecrawl / Notion / Granola / Gmail-IMAP / gcal-ICS
Mac (corpus factory): iMessage export -> normalize -> wiki compile -> rsync to box
```

## The numbers

| | |
|---|---|
| Corpus | 34,713 records, 6 sources, 2017-2026 + 25,473 vectors |
| Eval assets | 32 gold pairs (sliced) + 2 triage regressions + 5 score configs + 6 experiment runs |
| Custom code | ~900 lines Python across 13 single-purpose CLIs + 4 markdown skills |
| Spend so far | ~$5-8 of $1,000 credits (embedding + experiments + chat) |
| Recurring | ~$0.25-1.00/day inference + ~$2.40/mo disk; box hours free until Dec 2026 |
| Cold reviews | 4 stepbacks + 1 audit - each changed the build's direction |

## What is genuinely left (the honest list)

1. TONIGHT'S MILESTONE: 7:30 cron on the box + end-to-end scheduled-path test + dead-man's switch (silence must scream).
2. Secrets -> SSM Parameter Store; 10-line compromise runbook; pinned dependency list (3 near-misses from hand-assembled envs).
3. Weekly Mac->box corpus refresh automation.
4. The eval ambient layer: invariant suite over traces, online judge, correction auto-capture.
5. When exports land: WhatsApp/Meta/Discord/TikTok -> normalize -> wiki v3.
6. Earned-later: coach cadence, approved-external-send path, Groq voice on box, fine-tune experiment (the "twin brain").
