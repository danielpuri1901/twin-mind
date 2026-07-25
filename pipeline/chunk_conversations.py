#!/usr/bin/env python3
"""Window conversational records into retrieval-friendly chunks (2026-07-17).

Per-turn / per-message chunking makes semantically empty micro-chunks (measured medians:
imessage 19, gchat 7, transcripts 44 chars) - you cannot retrieve a topic from `"lol"`.
This groups consecutive turns within ONE conversation-day into ~TARGET-char, speaker-labeled
chunks with OVERLAP, so each chunk carries a coherent slice of conversation.

Research basis (docs/2026-07-17-corpus-chunking-design.md): window by thread + speaker turns,
~300-500 tokens with 20-30% overlap; Cohere embed-v3 caps at 512 tokens.

Reads  ~/twin-corpus/normalized/<source>.jsonl        (per-turn, the conversational sources)
Writes ~/twin-corpus/normalized-windowed/<source>.jsonl (same schema, so embed_corpus indexes it unchanged)
Non-conversational sources (gmail, gcal, contacts) are left alone.
"""
import glob
import json
import os
from collections import defaultdict

HOME = os.path.expanduser("~")
IN = os.path.join(HOME, "twin-corpus", "normalized")
OUT = os.path.join(HOME, "twin-corpus", "normalized-windowed")
CONV_SOURCES = ("imessage", "gchat", "transcripts")
TARGET = 1600   # ~400 tokens, safely under Cohere's 512-token cap
OVERLAP = 400   # ~25%


def _line(r):
    who = (r.get("sender") or r.get("who") or "?").strip() or "?"
    return f"{who}: {(r.get('text') or '').strip()}"


def window(records):
    """records = one (conversation, date) slice in chronological order. Yield windowed chunks
    (speaker-labeled multi-turn text) with ~OVERLAP-char overlap between consecutive chunks."""
    lines = [_line(r) for r in records if (r.get("text") or "").strip()]
    base = records[0]
    chat = base.get("chat", base.get("meeting", ""))
    i = 0
    while i < len(lines):
        buf, size, j = [], 0, i
        while j < len(lines) and size < TARGET:
            buf.append(lines[j]); size += len(lines[j]) + 1; j += 1
        yield {"source": base.get("source", ""), "chat": chat, "date": (base.get("date", "") or "")[:10],
               "who": "mixed", "sender": "", "text": "\n".join(buf)}
        if j >= len(lines):
            break
        # advance start, leaving ~OVERLAP chars of tail as overlap; always make progress
        back, bsz = 0, 0
        while (j - 1 - back) > i and bsz < OVERLAP:
            bsz += len(lines[j - 1 - back]) + 1; back += 1
        i = max(i + 1, j - back)


def main():
    os.makedirs(OUT, exist_ok=True)
    for src in CONV_SOURCES:
        path = os.path.join(IN, src + ".jsonl")
        if not os.path.exists(path):
            print(f"{src}: no {path}, skip"); continue
        groups = defaultdict(list)
        for l in open(path, encoding="utf-8"):
            r = json.loads(l)
            day = (r.get("date", "") or "")[:10]   # collapse timestamps to the day so a chat-day groups
            groups[(r.get("chat", r.get("meeting", "")), day)].append(r)
        n_in = sum(len(v) for v in groups.values())
        n_out = 0
        with open(os.path.join(OUT, src + ".jsonl"), "w", encoding="utf-8") as f:
            for recs in groups.values():
                recs.sort(key=lambda x: x.get("date", ""))   # chronological within the chat-day
                for chunk in window(recs):
                    f.write(json.dumps(chunk, ensure_ascii=False) + "\n"); n_out += 1
        print(f"{src}: {n_in} turns/msgs -> {n_out} windowed chunks ({n_in/max(n_out,1):.1f}x fewer)")


if __name__ == "__main__":
    main()
