---
name: daniel-corpus
description: Search and cite Daniel's personal corpus (messages, email, transcripts, calendar, wiki)
---
Daniel's personal corpus lives at ~/twin-corpus/.
Coverage: 2017-2026 across 6 sources (iMessage, Gmail, Google Chat, calendar, contacts, meeting transcripts). See wiki/index.md for per-source windows.

Retrieval - use ONLY this contract (the backend is swappable; never raw SQL, never grep the JSONL):
  corpus-search "<query>" [--k 20] [--mode hybrid|lexical|semantic] [--chat <person>] [--who me|them] [--since YYYY-MM-DD] [--until YYYY-MM-DD]
  Returns JSON lines: {source, chat, date, who, sender, text, score}.
- Default mode is hybrid (lexical + semantic fusion) - the eval-chosen default for questions about Daniel's life.
- For "how does Daniel write to X": corpus-search "<topic>" --chat <person> --who me (recent exemplars).

Rules:
- Always cite source + date for any claim about Daniel.
- If the corpus does not contain the answer, say so plainly; never invent personal facts.
- Recent voice wins: when drafting, prefer exemplars from the last ~18 months; older eras are context, never template.
- When drafting as Daniel, read wiki/voice-profile.md first and match the register for THAT audience (see wiki/people/<person>.md if it exists).
- Do NOT edit this skill yourself; propose changes to Daniel instead (this file is version-controlled in his project repo).
