# Wiki compile prompt (v1)

You are compiling Daniel's personal wiki from `~/twin-corpus/normalized/*.jsonl` (27k records: iMessage + meeting transcripts).
Rules: the wiki is LLM-maintained; cite evidence as source+date on every claim; never invent facts; one sentence per line; link related pages with [[name]].
Use `python3 "$SUPER/tools/corpus_search.py" "<query>" --k 20` for targeted lookups and read the JSONL directly for sweeps.

Produce/refresh under `~/twin-corpus/wiki/`:
1. `voice-profile.md` - how Daniel writes (message length, tone, phrases he actually uses, emoji habits, sign-offs) and how he speaks (filler words, rambling patterns from transcripts). Quote 10+ short real examples, each cited (source, chat/meeting, date).
2. `people/<slug>.md` for the 10 most frequent contacts - relationship, tone Daniel uses with them, running topics, last contact date.
3. `topics/<slug>.md` for recurring topics (job search, Routes AI, thesis, ArcelorMittal, training/health, family) - state of play, decisions made, open loops.
4. `index.md` - one-line description + link for every page.

Work incrementally: read existing pages first, update rather than rewrite.
