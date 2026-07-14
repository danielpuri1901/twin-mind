#!/usr/bin/env python3
"""
normalize_transcripts.py - convert verbatim meeting/interview transcripts
(Me:/Them: speaker turns) into the corpus common format. One JSONL record per
turn: {source, meeting, date, who, text}.

These are the coach's ground truth - Daniel's actual spoken voice, where
rambling and filler live. Reads the transcripts folder + the GROUND-TRUTH files
+ the one verbatim granola-note. Writes ~/twin-corpus/normalized/transcripts.jsonl.
"""
import os
import re
import json
import glob
import time

HOME = os.path.expanduser("~")
CAREER = os.path.join(HOME, "Desktop", "Career")
SOURCES = (
    glob.glob(os.path.join(CAREER, "career-ops/interview-prep/transcripts/*.md"))
    + glob.glob(os.path.join(CAREER, "Langchain/prep/*GROUND-TRUTH*.md"))
    + [os.path.join(CAREER,
       "career-ops/interview-prep/granola-notes/robert-christine-takehome-review-2026-06-29.md")]
)
OUTDIR = os.path.join(HOME, "twin-corpus", "normalized")
OUT = os.path.join(OUTDIR, "transcripts.jsonl")

TURN = re.compile(r"^(Me|Them):\s*(.*)$")
DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")


def file_date(path):
    m = DATE_IN_NAME.search(os.path.basename(path))
    return m.group(1) if m else time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(path)))


def parse_file(path):
    meeting, date, out = os.path.basename(path)[:-3], file_date(path), []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = TURN.match(line.rstrip("\n"))
        if m and m.group(2).strip():
            out.append({
                "source": "transcript",
                "meeting": meeting,
                "date": date,
                "who": "me" if m.group(1) == "Me" else "them",
                "text": m.group(2).strip(),
            })
    return out


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    records, per_file = [], []
    for path in sorted(set(SOURCES)):
        if not os.path.exists(path):
            continue
        recs = parse_file(path)
        if len(recs) < 2:            # skip near-empty captures (e.g. ife-call)
            continue
        records.extend(recs)
        per_file.append((len(recs), os.path.basename(path)))
    records.sort(key=lambda r: (r["date"], r["meeting"]))
    with open(OUT, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    me = sum(1 for r in records if r["who"] == "me")
    words_me = sum(len(r["text"].split()) for r in records if r["who"] == "me")
    print(f"transcripts: {len(per_file)}")
    print(f"turns:       {len(records)}  (me: {me}, them: {len(records) - me})")
    print(f"your spoken words captured: {words_me:,}")
    print(f"wrote:       {OUT}")


if __name__ == "__main__":
    main()
