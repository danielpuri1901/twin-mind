---
name: morning-brief
description: Daniel's daily 7:30 brief - inbox-decisions, calendar, AI-advancements digest, coach nudge - sent as a real email
---
Compose Daniel's morning brief and SEND it as ONE real email to danielpuri1901@gmail.com (SMTP send-only via the configured app password; sending TO Daniel himself is pre-approved - no per-send confirmation needed). Short, skimmable, no filler. Follow-ups and anything interactive during the day happen on Telegram.

FORMAT CONTRACT (pinned 2026-07-10 - the rendering is NOT a creative choice; fill the template exactly):
- Subject: exactly `Morning brief - {Weekday} {D} {Month}` (e.g. "Morning brief - Fri 10 Jul"). Plain hyphen. Never vary.
- Section headers: exactly `1. NEEDS YOU TODAY`, `2. TODAY`, `3. AI ADVANCEMENTS`, `4. ONE TECHNICAL THING`, `5. COACH`, `6. OPEN LOOPS` - numbered, uppercase, no emoji in headers.
- Section headers are FRAMED by heavy divider lines (the char ━ repeated ~29x), exactly:
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. NEEDS YOU TODAY
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  (Daniel's spec 2026-07-14. Use ━ U+2501 only - never the em dash —.)
- Dashes: plain hyphen "-" everywhere. NEVER an em dash (Daniel's canon).
- Items: "- " bullets; drafts indented as quoted blocks.
- Facts per item: 2-4 maximum. Same density every day - consistency beats completeness.
- Final line: the coverage line (`Reviewed N messages since <cursor>`). Nothing after it.

Sections, in order:
1. **Needs you today** - inbox decisions (act / skip): what needs a reply, with drafts ready for approval (use daniel-corpus for voice; drafts are proposals, never auto-send). Source-coverage rule: for any person involved in a pending call/meeting/reschedule thread, ALSO check Granola (recent meeting notes) and the corpus wiki before judging state - the meeting may have already happened.
2. **Today** - calendar events with times and locations.
3. **AI advancements** (2-3 items MAX) - not headlines, insights. Format per item: the idea in one sentence, why it matters in one sentence, and if relevant, one line tying it to Daniel's own projects (twin, fine-tune plan, ArcelorMittal bot). Sources to check: new Dwarkesh Podcast episodes, top HN AI/agents discussions, notable model/lab releases. Style example Daniel liked: "RLVR is why LLMs got great at coding/math - verifiable domains give clean reward signal; computer use lacks that, so progress there is slower. Ties to: your scorecard IS manufacturing verifiability."
4. **One technical thing** - teach ONE item from `~/twin-corpus/wiki/learning/digest-queue.md`, picked by day-of-year modulo list length (stateless rotation). Format: the concept in 3-4 sentences, then the EXACT code in this system that embodies it (read and quote the real file via terminal, with path), then ONE quiz question Daniel should answer cold. Items 1-3 are the LangChain interview gaps (see wiki/learning/interview-retrace-langchain-final.md) - he must own them reflexively before the Robert rematch (~Sep). This section exists to combat prompting-without-learning; never skip or thin it.
   AI-news dedupe (2026-07-14, after Sonnet 5 appeared daily: "enough"): before writing section 3, read ~/.hermes/state/digest-covered.txt; NEVER repeat a topic covered in the last 14 days. After sending, append today's item topics (one per line, with date) to that file.
5. **Coach** (1 item) - one nudge from the coach backlog, spaced-repetition style: resurface a prior nudge if unacknowledged, else one new observation grounded in recent corpus evidence.
6. **Open loops** (max 3) - from wiki/topics pages: commitments or threads going stale.

Inbox coverage (added 2026-07-07 after missed-email incident):
- Read inbox with `--since-last-brief` (cursor from the last successful send) - NEVER a fixed --hours window; a failed morning must widen the next window, not drop mail.
- You may see items already reviewed in a previous brief (at-least-once overlap): skip them silently. A duplicate mention beats a silent miss.
- The brief's final line MUST state coverage: "Reviewed N messages since <cursor date/time>." - N is the tool's actual output count. This line is machine-checked.

Rules:
- **Latest-state check (added after the first brief's two staleness errors, 2026-07-03):** before marking ANY item actionable, verify it is still live: scan for newer messages in the same thread, and corpus-search the counterpart/topic for state changes (a call that already happened, a date that moved, a thread Daniel closed). The newest evidence wins. If state is ambiguous, present it as a question ("did the Tiff call already happen?"), never as an action.
- NO job-search scanning (paused by Daniel 2026-07-02; he will say when it returns).
- Total length: readable in 90 seconds on a phone.
- Daniel edits this brief by telling the twin what to change; the twin updates THIS file (show the diff, ask approval before saving).

Feedback capture (added 2026-07-12 - this grows Daniel's own eval dataset):
- When Daniel reacts to a brief on Telegram (e.g. "brief: good, coach: great, teacher: too long, missed X"), parse it and append one JSON line per judgment to ~/twin-corpus/datasets/feedback.jsonl: {"date": "<today>", "section": "brief|inbox-decisions|coach|teacher|ai_news|draft", "verdict": "good|bad", "note": "<his words, verbatim>"}.
- If a verdict is "bad" WITH a note: also DRAFT a regression item from it (scenario = what the brief saw, expected = what Daniel's note implies) and ask him to approve it; on approval append to ~/twin-corpus/datasets/regression-candidates.jsonl. One approval = one future test.
- WEEKLY REVIEW (Sundays, after the brief): send ONE extra Telegram message listing (a) briefs this week Daniel never rated, (b) any day the watchdog flagged, (c) anything you were uncertain about, (d) any operational discovery or workaround you used this week that is not yet in the governed skills - propose it as a diff. He replies with labels in-line. This is the annotation queue.
- Acknowledge in one short line. Never argue with a verdict. A "bad + why" is a gift: repeat the why back in your acknowledgment.
