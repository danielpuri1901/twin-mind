"""email-census - who floods Daniel's inbox, and what he never opens.

Read-only. Selects every mailbox with readonly=True and fetches with
BODY.PEEK, so nothing is ever marked seen. It does not delete, archive,
label, or unsubscribe. Its only output is a report.

The column that decides everything is not volume, it is the read ratio. A
sender with 851 messages and 851 unread is junk. A sender with 40 messages
Daniel opened every time is a correspondent who happens to be prolific.
Sorting by volume alone would sweep the second kind away with the first.

List-Unsubscribe headers are collected per sender so the unsubscribe list can
be assembled without opening a single email and hunting for the link. The
links are reported, never followed: some are tracking URLs that confirm a
live address, so a human decides which ones to click.

    email-census [--days 365] [--top 40] [--out report.json]
"""

import argparse
import email
import imaplib
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta

HOST = "imap.gmail.com"
ALL_MAIL = '"[Gmail]/All Mail"'
BATCH = 400
ADDR = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
UNSUB_URL = re.compile(r"<(https?://[^>]+)>")


def load_env(path=os.path.expanduser("~/.hermes/.env")):
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


def address_of(raw):
    m = ADDR.search(raw or "")
    return m.group(0).lower() if m else (raw or "unknown").strip().lower()[:80]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--out", default=os.path.expanduser("~/email-census.json"))
    args = ap.parse_args()

    load_env()
    user = os.environ.get("TWIN_SMTP_ADDRESS")
    pw = os.environ.get("TWIN_SMTP_APP_PASSWORD")
    if not user or not pw:
        print("email-census: no mail credentials in ~/.hermes/.env", file=sys.stderr)
        return 2

    since = (datetime.now() - timedelta(days=args.days)).strftime("%d-%b-%Y")
    stats = defaultdict(lambda: {"total": 0, "unread": 0, "unsub": "", "name": ""})

    with imaplib.IMAP4_SSL(HOST) as im:
        im.login(user, pw)
        im.select(ALL_MAIL, readonly=True)  # readonly: nothing is ever marked seen
        typ, data = im.search(None, "SINCE", since)
        ids = data[0].split() if typ == "OK" and data and data[0] else []
        print(f"scanning {len(ids)} messages since {since} ...", file=sys.stderr)

        for start in range(0, len(ids), BATCH):
            chunk = ids[start:start + BATCH]
            rng = b",".join(chunk).decode()
            typ, resp = im.fetch(
                rng, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM LIST-UNSUBSCRIBE)])")
            if typ != "OK":
                continue
            flags = ""
            for item in resp:
                if isinstance(item, tuple):
                    head = item[0].decode(errors="replace")
                    flags = head
                    msg = email.message_from_bytes(item[1])
                    sender = address_of(msg.get("From"))
                    rec = stats[sender]
                    rec["total"] += 1
                    if "\\Seen" not in flags:
                        rec["unread"] += 1
                    if not rec["name"]:
                        rec["name"] = re.sub(r"\s+", " ", (msg.get("From") or "")).strip()[:70]
                    if not rec["unsub"]:
                        u = msg.get("List-Unsubscribe") or ""
                        urls = UNSUB_URL.findall(u)
                        http = [x for x in urls if x.startswith("http")]
                        if http:
                            rec["unsub"] = http[0][:300]
            print(f"  {min(start + BATCH, len(ids))}/{len(ids)}", file=sys.stderr)

    rows = []
    for addr, r in stats.items():
        ratio = r["unread"] / r["total"] if r["total"] else 0
        rows.append({"sender": addr, "name": r["name"], "total": r["total"],
                     "unread": r["unread"], "never_opened_pct": round(100 * ratio),
                     "unsubscribe": r["unsub"]})
    rows.sort(key=lambda x: -x["total"])

    json.dump({"scanned_days": args.days, "senders": rows}, open(args.out, "w"), indent=1)
    print(f"\nreport: {args.out}   senders: {len(rows)}\n")
    print("%-42s %7s %7s %6s %s" % ("sender", "total", "unread", "never", "unsub"))
    for r in rows[:args.top]:
        print("%-42s %7d %7d %5d%% %s" % (r["sender"][:42], r["total"], r["unread"],
                                          r["never_opened_pct"], "yes" if r["unsubscribe"] else "-"))
    junk = [r for r in rows if r["never_opened_pct"] >= 90 and r["total"] >= 5]
    print(f"\nnever-opened senders (>=90% unread, >=5 messages): {len(junk)}")
    print(f"messages they account for: {sum(r['total'] for r in junk)}")
    print(f"of those, with an unsubscribe link: {sum(1 for r in junk if r['unsubscribe'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
