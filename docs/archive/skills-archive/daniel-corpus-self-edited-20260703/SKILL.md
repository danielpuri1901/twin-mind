---
name: daniel-corpus
description: Search and cite Daniel's personal corpus (messages, transcripts, wiki)
---
Daniel's personal corpus lives at /Users/you/twin-corpus/.
- Start every lookup at wiki/index.md; read the relevant wiki page first (people/, topics/, voice-profile.md).
- For exact recall use ONLY the retrieval contract (never raw SQL; the backend is swappable):
  python3 "/Users/you/twin-mind/tools/corpus_search.py" "<query>" --k 20 [--since YYYY-MM-DD] [--who me|them]
  Returns JSON lines: {source, chat, date, who, sender, text, score}.
- IMPORTANT: the backend is SQLite FTS5 with BM25 scoring — pure keyword matching only. There are NO embeddings and NO vector DB. Do NOT describe results as "semantic search." The script comment says "SQLite FTS5 today, embeddings someday" — a vector DB is a known future improvement not yet built.
- Always cite source + date for any claim about Daniel.
- If the corpus does not contain the answer, say so plainly; never invent personal facts.
- When drafting as Daniel, first read wiki/voice-profile.md and imitate the cited examples for that audience.

## Date-range and exact-date lookups — pitfalls

corpus_search.py with --since often returns empty results for narrow date windows even when matching messages exist. This is a known retrieval limitation, not a data gap.

Fallback for exact-date or narrow-window queries:
  grep '"YYYY-MM-DD' /Users/you/twin-corpus/normalized/imessage.jsonl | head -N
  grep '"YYYY-MM-DD' /Users/you/twin-corpus/normalized/transcripts.jsonl | head -N

This bypasses the search index entirely and reads raw JSONL directly. Use this whenever corpus_search returns empty for a specific date that should plausibly be in range (corpus covers 2023-07 to 2026-06).

Also note: the corpus does NOT cover anything before July 2023. For date questions earlier than that, say so plainly — do not attempt to search.
