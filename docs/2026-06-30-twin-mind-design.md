# Twin Mind - design and build plan

Date: 2026-06-30
Status: scope locked, ready to build
Working name: Twin Mind

## What this is

A personal AI that lives on a small server, talks to you on Discord, and does two jobs.
It learns from your real data until it sounds and thinks like you.
You stay in the loop on everything.

The whole point is to learn how to build agents that are *reliable*, while ending up with something you actually use every day.

## The two jobs

**1. The doer.**
It reads your inbound (email, messages), drafts replies in your voice, and shows them to you each morning.
You skim, approve, tweak, or kill. Done in minutes.

**2. The coach.**
It watches *how you operate* - how you write, decide, handle setbacks, deal with people - and feeds you a few sharp nudges to become the best version of yourself.
Think of it as `/stepback`, pointed at you, on a schedule.

Both run on the same store of your data. The doer is easy to measure (did the draft match what you would send). The coach is measured more loosely, by tracking specific habits over weeks.

## The one rule: measure before you build

Before improving anything, we build a scorecard.
A scorecard is 20 real "message that came in -> reply you actually sent" pairs, plus a judge that scores how close the twin's draft is to your real one.

Why first: if you build the twin and measure last, you never know if a change helped or quietly hurt.
Build the scale before the diet. Every later step has to move the score, or it does not ship.
Reliable is not a feeling. It is a number you move.

## The stack

We use what is already built. Almost no custom code.

| Piece | What it does | Why this one |
| --- | --- | --- |
| Hermes Agent | The agent itself: memory, skills, self-learning, cron, Discord, connectors, sandboxing | Open-source, MIT, Python. Ships the twin features built-in. |
| AWS Bedrock | Runs Claude (the brain) | Pay per token, covered by your $1k credits. Prompt caching works here. |
| Small server (EC2 t4g.small or Lightsail) | Where Hermes runs, always on | t4g.small is free through Dec 2026. Lightsail is a flat $5-10/mo. |
| Langfuse Cloud (free tier) | Traces every step, and runs the scorecard (LLM-as-judge) | MIT, free for one user. Hermes already has a Langfuse plugin. Self-hosting it would cost more than the agent, so we do not. |
| Your data, in a git folder | The corpus: years of you, inspectable and exportable | Plain files you own. Becomes the training set later. |

Models, tiered to save money:
- Triage and classify ("does this need a reply, how urgent"): Haiku 4.5 (`anthropic.claude-haiku-4-5`)
- Drafting in your voice: Sonnet 4.6 (`global.anthropic.claude-sonnet-4-6`)
- Hard reasoning, only when needed: Opus 4.8 (`anthropic.claude-opus-4-8`)

Note: the exact Hermes provider config line for Bedrock comes from the Hermes "AI Providers" doc, which I could not load while writing this. We read it and use their documented value at setup. We do not invent it.

## Your data and connectors

The twin should know everything about you and reach all your tools.

- **Corpus**: a git folder of your sent email, your writing, and your past Claude conversations. It grows every day. This is the differentiated thing - nobody else has it.
- **Connectors**: Hermes connects to your tools through its built-in MCP client. We wire them in one at a time, using each service's MCP server and your own credentials: Gmail, Google Calendar, Drive, GitHub, Notion, Granola, Canvas.
- These are currently connected to your Claude account; Hermes connects to them itself, so each one is a small per-connector setup, not a one-click import. We start with the ones triage needs (Gmail, Calendar).

Hermes also keeps small, always-loaded notes you can read and edit:
- `SOUL.md` - the twin's identity (and later, the coach's identity)
- `USER.md` - your profile: how you communicate, your preferences, what to avoid
- `MEMORY.md` - facts it has learned

These are tiny on purpose. The deep archive is the corpus.

## The build, step by step

Each phase ships something real. We do not start the next until the current one passes the scorecard.

### Phase 0 - Foundations and the scorecard
- AWS: turn on Claude in Bedrock (one-time use-case form in `us-east-1`), spin up the small server, give it an IAM role that can call Bedrock, set a billing alarm.
- Install Hermes (`curl ... | bash`), point it at Bedrock, connect Discord with `hermes gateway setup`.
- Build the scorecard in Langfuse: load 20 real "inbound -> reply you sent" pairs as a dataset, add an LLM-as-judge that scores "sounds like Daniel" and "right action."
- Ship: you can chat with the twin on Discord, and you can score it.

### Phase 1 - The doer, measured
- Move your existing email-draft routine into a Hermes skill.
- Turn on Gmail and Calendar via MCP.
- Set a cron job for the morning triage.
- Gate every send behind your approval (Hermes does this natively).
- Ship: a morning message - "9 things need you, I drafted 7" - that you approve, and the scorecard says the drafts are good.

### Phase 2 - The corpus
- Start harvesting your data into the git folder (Claude exports, sent mail, writing samples).
- Wire it into Hermes so it recalls relevant past replies when drafting, and distills a summary of you into `USER.md`.
- Ship: drafts sound more like you, and the score climbs.

### Phase 3 - All connectors
- Wire in the rest: Drive, GitHub, Notion, Granola, Canvas.
- Gate by reversibility: act on its own for read, search, research, draft; ask you before send, commit, or spend.
- Ship: the twin can work across your whole stack, safely.

### Phase 4 - The coach
- Give the coach an identity in `SOUL.md` and a "coach" skill: read recent comms and decisions, surface 1-3 high-leverage patterns, grounded in real evidence from the corpus.
- Schedule it with cron, and re-surface nudges with spaced repetition (the schedule is the repetition).
- Track named habits (like message conciseness) over time.
- Ship: scheduled human-max nudges that are accurate because they come from your own data.

### Phase 5 - The twin brain (optional showpiece)
- One-off: rent a GPU (EC2 spot), fine-tune a small model on your corpus to draft as you, measure it against the Phase 0 scorecard, write up the result, then stop the GPU.
- Ship: either a model that writes like you, or proof that recall already wins. Both are real, portfolio-worthy results.

## Cost

Moderate daily use, Sonnet with caching, single user.

| Item | Cost |
| --- | --- |
| Inference (Sonnet + Haiku via Bedrock) | ~$15-25/mo |
| Server (Lightsail flat, or t4g.small free through 2026) | $0-10/mo |
| Langfuse Cloud (free tier) | $0 |
| GPU fine-tune (Phase 5) | ~$50 one-off, then stop it |

Recurring total: ~$15-40/mo.
Your $1k credits last about two years.
The one mistake that breaks this: self-hosting Langfuse on AWS (six containers, ~$175/mo idle). We use the free Cloud tier instead.

You are not paying twice. Your $100/mo Claude plan is for you building this in Claude Code. The running twin uses Bedrock credits. Two separate lanes.

## What is pre-built vs what we build

Pre-built (we configure, not code):
- Hermes: agent loop, memory, skills, self-learning, cron, Discord, MCP connectors, prompt caching, context compression, sandboxing and approvals, subagents.
- AWS: Bedrock inference, the server.
- Langfuse: tracing and the LLM-as-judge scorecard.

We build (small, mostly markdown and config):
- The scorecard (a Langfuse dataset plus a judge).
- The corpus folder structure.
- `SOUL.md` and the coach skill (instructions, not code).
- One fine-tune script in Phase 5.

## Open question

The coach aims you at "best version of yourself" in general, with no single institution to target. If that ever changes (a specific role, program, or goal), tell the coach and it re-points.

## Next

Approve this, then we turn it into a step-by-step build plan and start Phase 0.
