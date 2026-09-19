#!/usr/bin/env python3
"""
normalize_gmail.py - convert a Gmail Takeout mbox into the corpus common format.

Design choices (voice quality first):
- Skip messages labeled Spam or Trash (X-Gmail-Labels).
- Prefer text/plain body; fall back to crudely de-tagged text/html.
- Strip quoted reply chains so Daniel's records contain only Daniel's words.
- Keep subject, labels, counterpart, and Message-ID/In-Reply-To for future
  scorecard threading.
- who=me when From is Daniel's address; chat = counterpart address.
"""
import json
import mailbox
import os
import re
import sys
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

SRC = os.path.expanduser("~/twin-corpus/raw/google/All mail Including Spam and Trash-002.mbox")
OUT = os.path.expanduser("~/twin-corpus/normalized/gmail.jsonl")
ME = "you@example.com"
MAX_BODY = 4000

QUOTE_MARKERS = re.compile(
    r"^(On .{5,120} wrote:\s*$|-{3,}\s*Original Message|-{3,}\s*Forwarded message"
    r"|From: .+@.+|_{10,}|Sent from my )", re.IGNORECASE)


def hdr(msg, name):
    raw = msg.get(name, "")
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


def body_text(msg):
    part = None
    if msg.is_multipart():
        for p in msg.walk():
            if p.get_content_type() == "text/plain":
                part = p
                break
        if part is None:
            for p in msg.walk():
                if p.get_content_type() == "text/html":
                    part = p
                    break
    else:
        part = msg
    if part is None:
        return ""
    try:
        payload = part.get_payload(decode=True) or b""
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return ""
    if part.get_content_type() == "text/html":
        text = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;?", " ", text)
    return text


def strip_quotes(text):
    out = []
    for line in text.splitlines():
        if QUOTE_MARKERS.match(line.strip()):
            break
        if line.lstrip().startswith(">"):
            continue
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def main():
    n_read = n_kept = n_skipped_label = 0
    with open(OUT, "w", encoding="utf-8") as f:
        for msg in mailbox.mbox(SRC):
            n_read += 1
            if n_read % 5000 == 0:
                sys.stderr.write(f"  ...{n_read} scanned, {n_kept} kept\n")
            labels = (msg.get("X-Gmail-Labels") or "")
            if "Spam" in labels or "Trash" in labels:
                n_skipped_label += 1
                continue
            # Noise policy (Daniel, 2026-07-02): promo/updates/social tabs are noise
            # unless the message is sent/starred/important/personal/receipt mail.
            DROP = ("Category Promotions", "Category Updates", "Category Social")
            KEEP = ("Sent", "Important", "Starred", "Category Personal",
                    "Category Purchases", "Category Travel", "Category Bills")
            if any(d in labels for d in DROP) and not any(k in labels for k in KEEP):
                n_skipped_label += 1
                continue
            from_addr = parseaddr(hdr(msg, "From"))[1].lower()
            to_addr = parseaddr(hdr(msg, "To"))[1].lower()
            who = "me" if from_addr == ME else "them"
            counterpart = to_addr if who == "me" else from_addr
            try:
                date = parsedate_to_datetime(msg.get("Date")).isoformat()
            except Exception:
                continue
            text = strip_quotes(body_text(msg))
            if not text or len(text) < 10:
                continue
            f.write(json.dumps({
                "source": "gmail",
                "chat": counterpart or "unknown",
                "date": date,
                "who": who,
                "sender": from_addr,
                "subject": hdr(msg, "Subject"),
                "labels": labels,
                "message_id": msg.get("Message-ID", ""),
                "in_reply_to": msg.get("In-Reply-To", ""),
                "text": text[:MAX_BODY],
            }, ensure_ascii=False) + "\n")
            n_kept += 1

    print(f"scanned: {n_read}  kept: {n_kept}  spam/trash skipped: {n_skipped_label}")
    print(f"wrote:   {OUT}")


if __name__ == "__main__":
    main()
