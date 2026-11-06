---
name: daniel-corpus
description: Search and cite Daniel's personal corpus (messages, meetings, calendar, contacts, past chats)
---
Coverage: 2017 to now. Use only the `corpus_search` tool. Never read corpus files or databases directly.

Results are JSON lines: {source, chat, date, who, sender, text, score}.

- Retrieval is hybrid, the eval-chosen default for questions about Daniel's life.
- For "how does Daniel write to X": call `corpus_search` with `chat` set to the person and `who` set to `me`.

Rules:
- Always cite source and date for any claim about Daniel.
- If the corpus does not contain the answer, say so plainly. Never invent personal facts.
- Recent voice wins: when drafting, prefer the last 18 months. Older eras are context, never a template.
- When drafting as Daniel, read `reference/voice-profile.md` first and match the register for that audience. See `people/<person>.md` if it exists.
