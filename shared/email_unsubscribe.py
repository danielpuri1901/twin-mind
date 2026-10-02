"""Separate scheduled mail from event-driven mail, then unsubscribe from the scheduled kind.

The distinction Daniel drew, and it is the right one: an order confirmation
from Thuisbezorgd is wanted, the Thuisbezorgd newsletter is not. Turning off
"Thuisbezorgd" would lose both.

They separate cleanly in the headers, which is why this works at the address
level and not the domain level:

  newsletter@update.thuisbezorgd.nl   List-Unsubscribe present  -> marketing
  noreply@thuisbezorgd.nl             no List-Unsubscribe       -> transactional

Bulk senders are required to offer List-Unsubscribe; transactional mail
normally carries none, because there is nothing to unsubscribe from. So the
presence of that header is the signal, and an address with no header is never
touched.

Two ways to act, and only one is automated here:

  RFC 8058 one-click. The sender advertises `List-Unsubscribe-Post:
  List-Unsubscribe=One-Click`. A single POST, no cookies, no redirects, no
  rendered page. This exists precisely so machines can do it, so it is safe
  to automate.

  Everything else is a URL meant for a browser. Those are NOT followed here.
  Some are tracking links whose only real function is to confirm a live
  address. They are printed for a human to review.

Nothing is ever deleted, archived or marked seen. The mailbox is opened
read-only; the only writes this makes are the unsubscribe POSTs.
"""

import argparse
import email
import imaplib
import json
import os
import re
import sys
import urllib.error
import urllib.request

HOST = "imap.gmail.com"
ALL_MAIL = '"[Gmail]/All Mail"'
URLS = re.compile(r"<(https?://[^>]+)>")
MAILTOS = re.compile(r"<(mailto:[^>]+)>")

# Never unsubscribe from these, whatever the header says. Job applications,
# bank, and real messages from people are not marketing.
PROTECT = re.compile(
    r"ashbyhq|greenhouse|lever\.co|workday|bankofamerica|@chase|revolut|"
    r"messages-noreply@linkedin|inmail|mailer-daemon|@stripe|@paypal|"
    r"invoice|receipt|order|shipping|tracking|delivery|security|verify",
    re.I)


def load_env(path=os.path.expanduser("~/.hermes/.env")):
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


def headers_for(im, sender):
    """Newest message from this sender, headers only, nothing marked seen."""
    typ, data = im.search(None, "FROM", f'"{sender}"')
    if typ != "OK" or not data or not data[0]:
        return None
    last = data[0].split()[-1]
    typ, raw = im.fetch(last, "(BODY.PEEK[HEADER])")
    if typ != "OK" or not raw or not isinstance(raw[0], tuple):
        return None
    return email.message_from_bytes(raw[0][1])


def clean(url):
    """Strip the folding whitespace RFC 5322 allows inside a long header.

    LinkedIn's List-Unsubscribe URL is long enough to be folded across lines,
    and the continuation arrives as a tab or CRLF sitting in the middle of the
    URL. urllib then refuses it: "URL can't contain control characters". A URL
    has no legal whitespace, so removing all of it is safe and exact.
    """
    return re.sub(r"\s+", "", url or "")


def classify(msg):
    """(kind, target). kind is one-click, browser, mailto or none."""
    if msg is None:
        return "none", ""
    header = msg.get("List-Unsubscribe") or ""
    post = (msg.get("List-Unsubscribe-Post") or "").lower()
    urls = [clean(u) for u in URLS.findall(header)]
    https = [u for u in urls if u.startswith("http")]
    if https and "one-click" in post:
        return "one-click", https[0]
    if https:
        return "browser", https[0]
    mailtos = [clean(u) for u in MAILTOS.findall(header)]
    if mailtos:
        return "mailto", mailtos[0]
    return "none", ""


def one_click(url, timeout=20):
    """RFC 8058: POST List-Unsubscribe=One-Click, nothing else."""
    req = urllib.request.Request(
        url, data=b"List-Unsubscribe=One-Click", method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "Mozilla/5.0 (compatible; mail-preferences/1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, r.status
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)[:90]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--census", default=os.path.expanduser("~/email-census.json"))
    ap.add_argument("--min-unread-pct", type=int, default=90)
    ap.add_argument("--min-total", type=int, default=20)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--execute", action="store_true",
                    help="actually send the one-click POSTs (default: report only)")
    ap.add_argument("--hold", default="",
                    help="comma-separated substrings to skip: senders behind a paid or "
                         "account relationship, where losing the list would cost something")
    args = ap.parse_args()

    load_env()
    user, pw = os.environ.get("TWIN_SMTP_ADDRESS"), os.environ.get("TWIN_SMTP_APP_PASSWORD")
    if not user or not pw:
        print("no mail credentials", file=sys.stderr)
        return 2

    data = json.load(open(args.census))
    held = [h.strip().lower() for h in args.hold.split(",") if h.strip()]
    cand = [s for s in data["senders"]
            if s["never_opened_pct"] >= args.min_unread_pct
            and s["total"] >= args.min_total
            and not PROTECT.search(s["sender"] + " " + (s.get("name") or ""))
            and not any(h in s["sender"].lower() for h in held)][:args.top]
    print(f"candidates: {len(cand)} senders, {sum(c['total'] for c in cand)} messages\n")

    results = []
    with imaplib.IMAP4_SSL(HOST) as im:
        im.login(user, pw)
        im.select(ALL_MAIL, readonly=True)
        for c in cand:
            kind, target = classify(headers_for(im, c["sender"]))
            row = {**c, "kind": kind, "target": target, "result": ""}
            if kind == "one-click" and args.execute:
                ok, detail = one_click(target)
                row["result"] = "unsubscribed" if ok else f"failed: {detail}"
            results.append(row)
            print("%-42s %7d  %-9s %s" % (c["sender"][:42], c["total"], kind, row["result"]))

    out = os.path.expanduser("~/email-unsubscribe-plan.json")
    json.dump(results, open(out, "w"), indent=1)
    by = {}
    for r in results:
        by[r["kind"]] = by.get(r["kind"], 0) + 1
    print(f"\nby kind: {by}")
    print(f"plan written: {out}")
    if not args.execute:
        print("\nreport only. re-run with --execute to send the one-click unsubscribes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
