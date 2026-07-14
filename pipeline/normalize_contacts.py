#!/usr/bin/env python3
"""
normalize_contacts.py - Google Contacts .vcf -> common format.
One record per contact: a searchable directory line (name, emails, phones).
"""
import glob
import json
import os
import re

SRC = glob.glob(os.path.expanduser(
    "~/twin-corpus/raw/google/extracted/Takeout/Contacts/*/*.vcf"))
OUT = os.path.expanduser("~/twin-corpus/normalized/contacts.jsonl")


def main():
    seen, records = set(), []
    for path in SRC:
        card = None
        for line in open(path, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line == "BEGIN:VCARD":
                card = {"emails": [], "phones": []}
            elif line == "END:VCARD" and card is not None:
                name = card.get("fn", "")
                if name:
                    text = name
                    if card["emails"]:
                        text += " <" + ", ".join(card["emails"]) + ">"
                    if card["phones"]:
                        text += " tel: " + ", ".join(card["phones"])
                    if text not in seen:
                        seen.add(text)
                        records.append({"source": "contacts", "chat": "directory",
                                        "date": "", "who": "", "sender": "",
                                        "text": text})
                card = None
            elif card is not None:
                if line.startswith("FN"):
                    card["fn"] = line.split(":", 1)[-1]
                elif line.startswith("EMAIL"):
                    card["emails"].append(line.split(":", 1)[-1].lower())
                elif line.startswith("TEL"):
                    card["phones"].append(re.sub(r"[^\d+]", "", line.split(":", 1)[-1]))

    with open(OUT, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"contacts: {len(records)} -> {OUT}")


if __name__ == "__main__":
    main()
