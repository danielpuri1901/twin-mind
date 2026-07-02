#!/usr/bin/env python3
"""
build_gold_dataset.py - parse Daniel's marked curation sheet into the canonical
gold set (local JSONL = source of truth), then push a copy to Langfuse as a
dataset with slice metadata.
"""
import json
import os
import re
import urllib.request

MD = os.path.expanduser("~/twin-corpus/index/gold-curation.md")
OUT = os.path.expanduser("~/twin-corpus/index/gold-set.jsonl")
DATASET = "twin-gold-v1"
AUD = {"f": "family", "c": "close_friend", "p": "professional", "o": "other"}

HDR = re.compile(r"\[\s*x\s*([fcpo])\s*\]\s*(\d+)\.\s*\((text|email)\)\s*(.+?)\s+·\s+(\d{4}-\d{2}-\d{2})", re.I)


def parse():
    blocks = open(MD, encoding="utf-8").read().split("\n## ")
    items = []
    for b in blocks:
        m = HDR.match(b.strip())
        if not m:
            continue
        tag, num, kind, chat, date = m.groups()
        subject = re.search(r"^Subject: (.+)$", b, re.M)
        context = re.findall(r"^> (.+)$", b, re.M)
        inbound = re.search(r"\*\*Inbound:\*\* (.*?)\n\n\*\*Your reply:\*\*", b, re.S)
        reply = re.search(r"\*\*Your reply:\*\* (.*?)(?:\n\n---|\Z)", b, re.S)
        if not (inbound and reply):
            print(f"  ! could not parse pair {num}, skipping")
            continue
        items.append({
            "id": f"gold-{int(num):02d}",
            "audience": AUD[tag.lower()],
            "kind": kind,
            "chat": chat.strip(),
            "date": date,
            "subject": subject.group(1) if subject else "",
            "context": context,
            "inbound": inbound.group(1).strip(),
            "reply": reply.group(1).strip(),
        })
    return items


def push_langfuse(items):
    pk, sk = os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"]
    base = os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    import base64
    auth = base64.b64encode(f"{pk}:{sk}".encode()).decode()

    def post(path, payload):
        req = urllib.request.Request(base + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Basic {auth}"})
        try:
            return json.load(urllib.request.urlopen(req))
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:200]
            if e.code == 409:   # dataset already exists
                return {"note": "exists"}
            raise SystemExit(f"Langfuse {e.code}: {body}")

    post("/api/public/v2/datasets",
         {"name": DATASET, "description": "Daniel gold pairs v1 - sliced by audience; local gold-set.jsonl is canonical"})
    for it in items:
        post("/api/public/dataset-items", {
            "datasetName": DATASET,
            "id": it["id"],                       # idempotent upsert
            "input": {k: it[k] for k in ("audience", "kind", "chat", "subject", "context", "inbound")},
            "expectedOutput": it["reply"],
            "metadata": {"audience": it["audience"], "kind": it["kind"], "date": it["date"]},
        })
    return len(items)


def main():
    items = parse()
    with open(OUT, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    from collections import Counter
    slices = Counter(i["audience"] for i in items)
    print(f"gold set: {len(items)} pairs -> {OUT}")
    print("slices:", dict(slices))
    n = push_langfuse(items)
    print(f"pushed {n} items to Langfuse dataset '{DATASET}'")


if __name__ == "__main__":
    main()
