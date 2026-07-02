# Gameplan - build now, ready when the data lands

Data is trickling in (iMessage now, Gmail running, WhatsApp ~3 days, Discord ~days, Meta/TikTok ~days). So we don't sit and wait. We build the **data-agnostic pipeline** now, test it on what we already have, and make ingesting each new export a one-command job. When it lands, it's plug-and-play.

## The pipeline every source flows through

```
raw/  (drop zone, per source)
  -> normalizer   (per-source script -> one common format)
  -> corpus       (clean markdown / JSONL: {source, date, who, text})
  -> compile      (an LLM turns the corpus into the wiki)
  -> wiki/        (concept articles, timelines, people, your voice profile)
  -> twin         (queries the wiki, drafts in your voice)
  -> coach        (analyzes patterns, nudges you)
```

The common format is the trick: every message and doc becomes the same simple shape, so the twin doesn't care whether it came from WhatsApp or email.

## Three tracks, run in parallel

**Track A - the pipeline (build now, nothing to wait for)**
1. Define the common format: one record = `{source, date, who, text}`.
2. Write normalizers (small scripts), built and tested on data we already have:
   - iMessage (`chat.db` -> common format) - today
   - documents (the curated doc slice -> text) - today
   - then ready stubs for WhatsApp `_chat.txt`, Discord JSON, Meta JSON, Gmail, TikTok JSON
3. Write the compile step: an LLM prompt/skill that turns the corpus into the wiki, run incrementally as data grows.

**Track B - the scorecard (build now - this is "Phase 0", it comes before tuning anything)**
- 20 real `inbound -> the reply you actually sent` pairs (from Gmail + iMessage) + an LLM-as-judge in Langfuse. This is how we know the twin sounds like you. Nothing "improves" until it beats this.

**Track C - the agent infra (build now, totally independent of the data)**
- AWS: enable Claude in Bedrock, spin up the small box, set up the Discord bot, Langfuse Cloud free tier.
- Install Hermes, point it at Bedrock, get it talking to you on Discord. It starts nearly empty and gets smarter as the corpus fills.

## As each export arrives (the plug-and-play part)

| Source | When | Step |
|---|---|---|
| iMessage | now | normalizer -> corpus -> recompile wiki |
| Gmail | running | normalizer -> corpus + scorecard pairs |
| Documents | now | ingest curated slice -> corpus |
| WhatsApp | ~3 days | normalizer (top threads) -> corpus |
| Discord | ~days | normalizer -> corpus |
| Meta / TikTok | ~days | normalizer -> corpus |

Every new source = re-run its normalizer, recompile the wiki, and the twin (already live) instantly knows the new data.

## Definition of "ready to go"

When a new export lands: ingesting it is one command, the wiki recompiles, the twin already running on Discord immediately knows the new data, and the scorecard tells us whether drafts got better.

## Order of operations (next steps)

1. Pull iMessage + ingest the document slice (data we have today).
2. Build the common format + the iMessage/document normalizers.
3. Build the scorecard (needs Gmail, which is exporting now).
4. Stand up the agent infra (Track C) in parallel - it doesn't need the data.
5. Compile the first wiki from what we've got; let the twin answer questions about you.
6. As WhatsApp / Discord / Meta / TikTok land, run their normalizers and recompile.
7. Add the coach once the corpus and twin are solid.
