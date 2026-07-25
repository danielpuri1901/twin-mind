#!/usr/bin/env python3
"""Contextual embedding (deterministic) - Anthropic's Contextual Retrieval, cheap version.

The problem: we embed a chunk's raw text only. The meeting name, date, and real participant names
live in metadata COLUMNS, not in the embedded text - so "them: latency is the priority" embeds
without "Spiros", "2026-06-25", or the topic. A query like "what did Max say" can't match, because
the chunk text says "them:", and "Max" only exists in the chat stem (which isn't embedded).

The fix: prepend a one-line context header - `[<chat/meeting> · <date>]` - to each record's TEXT
before embedding. The chat stem already carries the names/topic (e.g. "2026-06-17-crowdvolt-max-
hammer"), so this pulls them INTO the vector. Deterministic, no LLM (Anthropic uses an LLM to write
a richer blurb; we start with the metadata we already have and can test the LLM version later).

Reads jsonl, writes jsonl with the SAME schema (only `text` changes) so embed_corpus indexes it
unchanged.

    add_context.py OUT_DIR IN1.jsonl IN2.jsonl ...
"""
import json
import os
import sys


def contextualize(r):
    chat = (r.get("chat") or r.get("meeting") or "").strip()
    date = (r.get("date") or "")[:10]
    head = " · ".join(x for x in [chat, date] if x)
    text = (r.get("text") or "").strip()
    return {**r, "text": f"[{head}]\n{text}" if head else text}


def main():
    out_dir, inputs = sys.argv[1], sys.argv[2:]
    os.makedirs(out_dir, exist_ok=True)
    for path in inputs:
        name = os.path.basename(path)
        n = 0
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            for line in open(path, encoding="utf-8"):
                f.write(json.dumps(contextualize(json.loads(line)), ensure_ascii=False) + "\n")
                n += 1
        print(f"{name}: {n} records contextualized -> {os.path.join(out_dir, name)}")


if __name__ == "__main__":
    main()
