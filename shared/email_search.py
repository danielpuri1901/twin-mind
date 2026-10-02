"""email-search - read-only search over Daniel's Gmail.

The companion to corpus-search, and deliberately not the same thing. The
corpus holds what should surface without being asked: his own words, his
meetings, his decisions. Email is the other kind, the thing he asks about, so
freshness beats recall and it is fetched live instead of ingested.

That split came from a measurement on 2026-09-28: 60% of the 5,421 gmail
records in the corpus were machine mail, led by no-reply@twitch.tv with 851,
and they were degrading retrieval rather than sitting inert. His own sent
mail stays in the corpus as voice; the rest is fetched from here on demand.

READ-ONLY, and this is not a preference. Every mailbox is selected with
readonly=True so nothing is ever marked seen. CLAUDE.md bans the Hermes email
gateway adapter on this account for exactly that reason: it marks all mail
seen and polls. This tool never sends, never deletes, never flags.

    email-search "invopop"                    # recent mail matching a word
    email-search "" --from juan --days 30     # everything from a person
    email-search "" --unread --limit 20       # what is sitting unread
    email-search "kavak" --sent               # what Daniel wrote about it

Prints JSON lines: {date, from, to, subject, folder, unread, snippet}.
"""

import argparse
import email
import email.utils
import imaplib
import json
import os
import re
import sys
from datetime import datetime, timedelta

INBOX = "INBOX"
SENT = '"[Gmail]/Sent Mail"'
ALL_MAIL = '"[Gmail]/All Mail"'
HOST = "imap.gmail.com"
MAX_SNIPPET = 400


def load_env(path=os.path.expanduser("~/.hermes/.env")):
    """Same env file the brief uses; only fills what is not already set."""
    try:
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


def decode(raw):
    if not raw:
        return ""
    out = []
    for part, enc in email.header.decode_header(raw):
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(part)
    return " ".join(out).strip()


def body_snippet(msg):
    """First readable text, collapsed. Quoted replies and signatures are noise
    in a search result, so the snippet stops at the first quote marker."""
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    text = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace")
                    break
                except Exception:
                    continue
    else:
        try:
            text = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            text = ""
    text = re.split(r"\n\s*(?:On .*wrote:|-{2,}\s*Original Message|_{5,})", text)[0]
    text = re.sub(r"^\s*>.*$", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()[:MAX_SNIPPET]


def build_query(args):
    """Gmail IMAP search. Terms are ANDed, which is what people expect."""
    parts = []
    if args.days:
        since = (datetime.now() - timedelta(days=args.days)).strftime("%d-%b-%Y")
        parts += ["SINCE", since]
    if args.unread:
        parts.append("UNSEEN")
    if getattr(args, "sender", None):
        parts += ["FROM", f'"{args.sender}"']
    if args.query:
        parts += ["TEXT", f'"{args.query}"']
    return parts or ["ALL"]


def search_folder(im, folder, args):
    try:
        im.select(folder, readonly=True)  # readonly: never mark anything seen
    except imaplib.IMAP4.error:
        return []
    typ, data = im.search(None, *build_query(args))
    if typ != "OK" or not data or not data[0]:
        return []
    ids = data[0].split()[-args.limit:]
    out = []
    for mid in reversed(ids):
        typ, raw = im.fetch(mid, "(BODY.PEEK[])")  # PEEK: does not set \Seen
        if typ != "OK" or not raw or not raw[0]:
            continue
        msg = email.message_from_bytes(raw[0][1])
        date = ""
        try:
            dt = email.utils.parsedate_to_datetime(msg.get("Date"))
            date = dt.isoformat()
        except Exception:
            date = (msg.get("Date") or "")[:32]
        out.append({
            "date": date,
            "from": decode(msg.get("From")),
            "to": decode(msg.get("To")),
            "subject": decode(msg.get("Subject")),
            "folder": "sent" if "Sent" in folder else "inbox",
            "snippet": body_snippet(msg),
        })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query", nargs="?", default="", help="text to match; empty to browse")
    ap.add_argument("--from", dest="sender", default=None, help="match the sender")
    ap.add_argument("--days", type=int, default=90, help="how far back (default 90)")
    ap.add_argument("--limit", type=int, default=10, help="max results per folder")
    ap.add_argument("--unread", action="store_true", help="only unread")
    ap.add_argument("--sent", action="store_true", help="search sent mail instead")
    ap.add_argument("--all-mail", action="store_true", help="search All Mail, including archived")
    args = ap.parse_args()

    load_env()
    user = os.environ.get("TWIN_SMTP_ADDRESS")
    password = os.environ.get("TWIN_SMTP_APP_PASSWORD")
    if not user or not password:
        print("email-search: no mail credentials in ~/.hermes/.env", file=sys.stderr)
        return 2

    folder = SENT if args.sent else (ALL_MAIL if args.all_mail else INBOX)
    try:
        with imaplib.IMAP4_SSL(HOST) as im:
            im.login(user, password)
            rows = search_folder(im, folder, args)
    except Exception as exc:
        print(f"email-search: {exc}", file=sys.stderr)
        return 1

    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    if not rows:
        print(json.dumps({"note": "no matching mail", "folder": folder,
                          "days": args.days}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
