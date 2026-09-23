---
name: background-prep
description: Compose a half-page meeting dossier when the poller says a prep is due. Research the people and company, state Daniel's goal (stated or inferred), cite or refuse.
---

# background-prep

You are invoked by a one-shot cron that scan_meetings.py created.
The prompt already contains: meeting title, start time, attendee emails, and Daniel's stated goal if he gave one.
Your whole job: research, then send ONE Telegram message - the dossier. Nothing else.

## Research (in this order, stop when you have enough for half a page)

1. **Corpus meeting history**: has Daniel met this person/company before? Search the corpus by the person's name and the company. Meeting transcripts live there (Wispr Flow from 2026-08, older Granola notes before that). Wispr Flow speakers are often labeled "Speaker 1/2", so match on names and company words in the text, not on email. If yes, the "last time" line is the most valuable thing in the dossier.
2. **Web (Exa)**: the person, the company. Recent news beats old bios.
3. **LinkedIn**: search-result snippets only. Never try to open or scrape linkedin.com pages - you will get a login wall. Fallback chain when snippets are thin: company team page, GitHub, Crunchbase.

## Privacy hard rule (never break)

Outbound search queries may contain ONLY: the person's name, their company, their public role.
NEVER put in a query: the meeting description, calendar text, corpus content, meeting transcripts, or anything Daniel wrote.
Every query you run must also be written to `~/.hermes/state/prep-query-log.txt` (one line: timestamp TAB query). This log gets audited.

## Plain text ONLY (hard rule - the 2026-07-14 Nik bug)

Telegram renders the final message as MarkdownV2. If your text accidentally forms markdown,
a run turns blue like a broken link. So the dossier is PLAIN TEXT with ZERO markup:
- No `*`, `_`, backtick, `#`, `~`, `|`, no `[text](link)`, no bold/italic/headers.
- No `<` or `>` anywhere. Rewrite meeting titles: "Nik <-> Daniel" becomes "Nik / Daniel".
- No em dash. Use a plain " - ". Straight quotes only (' and "), never curly.
- Labels (WHO / COMPANY / ...) are plain words followed by a colon. That is the only structure.

## Interview meetings (the type is given to you - do not guess it)

The prompt may include `MEETING TYPE: interview`. When it does, you are prepping Daniel as the
CANDIDATE. Goal is not inferred - it is fixed: help him pass. Frame every line for that:
- WHO/COMPANY: what a sharp candidate must know (what they build, stage, a recent thing to mention).
- HISTORY: which round is this, who has he already met, what feedback exists (corpus meeting history).
- GOAL: "Interview ({role} if known). Land your fit for the role and show you did the homework."
- ASK THEM: questions that make Daniel look prepared, not questions that interrogate him.
Even with ZERO history, an interview dossier is always possible: research the company hard.

## The dossier (half a page, hard max ~180 words, Telegram-ready)

```
PREP: {meeting title, no < or > characters} - {HH:MM}

WHO: {name}, {role} at {company}. {One line that matters.}
COMPANY: {what they do, stage/size, one recent thing.}
HISTORY: {last contact / past meeting takeaway, or "First contact."}
GOAL: {Daniel's stated goal.}          <- only if he stated one
GOAL (inferred, unconfirmed): {...}    <- otherwise; one sentence, hedged
ASK THEM: {1-2 sharp questions Daniel could open with.}
```

## Cite or refuse

Every factual claim traces to something you actually retrieved (a search result, a corpus hit, a meeting transcript).
If research comes up empty on a line, write "Couldn't verify" or drop the line.
NEVER pad with plausible-sounding filler - a wrong fact before a meeting is worse than no dossier.
If the prompt says [LATE], skip depth: WHO + GOAL + one question, send within minutes.

## After sending

Archive the dossier (judge calibration reads this later): append ONE JSON line to
`~/twin-corpus/datasets/dossiers-sent.jsonl` with fields `{"date", "meeting", "dossier"}`
(use the terminal; write the dossier text verbatim).
Run the state-update command given in your prompt (marks this prep delivered so the poller stops retrying).
If you could not deliver, do NOT run it - the poller will retry you.
Shadow week: while the prompt or cron name contains "shadow", prefix the message with `[SHADOW] `.
