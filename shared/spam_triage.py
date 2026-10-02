"""Read the spam folder and surface anything that does not belong there.

A spam filter's false positives are invisible by construction: the mail you
never see is the mail you cannot miss. During a job search that is expensive,
because an applicant tracking system sends from a bulk relay and looks exactly
like the marketing it sits next to.

Read-only. The folder is selected with readonly=True and fetched with
BODY.PEEK, so nothing is marked seen, moved, or removed. It scores and prints;
rescuing anything is a separate, deliberate act.

Scoring is deterministic, not a judgement call. A message earns points for
coming from a domain that matters (applicant tracking, bank, government,
university, account security), for a subject that implies a real transaction
or a real conversation, and for being addressed to one person rather than
blasted. It loses points for the markers of the mail that belongs in spam.

    spam-triage [--days 180] [--min-score 2]
"""

import argparse
import email
import email.header
import email.utils
import imaplib
import os
import re
import sys
from datetime import datetime, timedelta

HOST = "imap.gmail.com"
SPAM = '"[Gmail]/Spam"'
BATCH = 200

# Domains where a false positive costs something real.
GOOD_DOMAINS = re.compile(
    r"ashbyhq|greenhouse\.io|lever\.co|workday|workable|jobs2web|smartrecruiters|"
    r"teamtailor|recruitee|bamboohr|ripplematch|"
    r"abnamro|\bing\.nl|rabobank|bunq|revolut|americanexpress|bankofamerica|stripe|paypal|"
    r"overheid\.nl|belastingdienst|ind\.nl|digid|duo\.nl|svb\.nl|"
    r"uva\.nl|vu\.nl|instructure|ans\.app|ie\.edu|"
    r"accounts\.google|apple\.com|1password|okta|github|gitlab|amazonaws|anthropic|openai",
    re.I)

# Companies in the live pipeline. A reply from one of these sitting in spam is
# the whole reason to run this.
PIPELINE = re.compile(
    r"kavak|invopop|oneleet|interfere|chainfill|postral|blackfin|novo|palantir|"
    r"langchain|crowdvolt|nous ?research", re.I)

REAL_SUBJECT = re.compile(
    r"\binterview\b|\boffer\b|application|your (application|candidacy)|next steps|"
    r"schedule a (call|chat)|take.?home|assessment|reference|contract|"
    r"invoice|factuur|receipt|verification code|sign.?in|security alert|"
    r"\bre:|\bfwd:", re.I)

JUNK_SUBJECT = re.compile(
    r"viagra|casino|crypto|bitcoin|forex|lottery|winner|claim your|"
    r"\bloan\b|weight loss|dating|singles|escort|xxx|porn|"
    r"unclaimed|inheritance|prince|beneficiary|congratulations you|"
    r"limited time|act now|risk.?free|100% free|make money|work from home",
    re.I)

BULK_HINT = re.compile(r"no-?reply|newsletter|marketing|promo|deals?@|offers?@", re.I)


def load_env(path=os.path.expanduser("~/.hermes/.env")):
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
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
            # Spam headers declare charsets that do not exist ("unknown-8bit"
            # is common), so a failed lookup falls back rather than crashing
            # the scan on the one message most worth looking at.
            try:
                out.append(part.decode(enc or "utf-8", errors="replace"))
            except (LookupError, TypeError):
                out.append(part.decode("utf-8", errors="replace"))
        else:
            out.append(part)
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def score(sender, subject, to_field, list_id):
    """Points, and the reasons. Reasons are printed so the score is auditable."""
    pts, why = 0, []
    if GOOD_DOMAINS.search(sender):
        pts += 3
        why.append("known-good domain")
    if PIPELINE.search(sender + " " + subject):
        pts += 4
        why.append("live pipeline company")
    if REAL_SUBJECT.search(subject):
        pts += 2
        why.append("transactional or reply subject")
    if not list_id and not BULK_HINT.search(sender):
        pts += 1
        why.append("not a bulk sender")
    if to_field.count("@") == 1:
        pts += 1
        why.append("addressed to one person")
    if JUNK_SUBJECT.search(subject):
        pts -= 5
        why.append("junk subject")
    if list_id:
        pts -= 1
        why.append("mailing list")
    return pts, why


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--min-score", type=int, default=2)
    ap.add_argument("--show-all", action="store_true", help="print the junk too")
    args = ap.parse_args()

    load_env()
    user = os.environ.get("TWIN_SMTP_ADDRESS")
    pw = os.environ.get("TWIN_SMTP_APP_PASSWORD")
    if not user or not pw:
        print("no mail credentials in ~/.hermes/.env", file=sys.stderr)
        return 2

    since = (datetime.now() - timedelta(days=args.days)).strftime("%d-%b-%Y")
    with imaplib.IMAP4_SSL(HOST) as im:
        im.login(user, pw)
        typ, d = im.select(SPAM, readonly=True)  # readonly: never touch spam
        total = int(d[0]) if typ == "OK" and d and d[0] else 0
        typ, data = im.uid("SEARCH", None, "SINCE", since)
        ids = data[0].split() if typ == "OK" and data and data[0] else []
        print(f"spam folder: {total} messages, {len(ids)} since {since}\n", file=sys.stderr)

        rows = []
        for i in range(0, len(ids), BATCH):
            rng = b",".join(ids[i:i + BATCH]).decode()
            typ, resp = im.uid(
                "FETCH", rng,
                "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE LIST-ID)])")
            if typ != "OK":
                continue
            for item in resp:
                if not isinstance(item, tuple):
                    continue
                try:
                    msg = email.message_from_bytes(item[1])
                except Exception:
                    continue
                sender = decode(msg.get("From"))
                subject = decode(msg.get("Subject"))
                to_field = decode(msg.get("To"))
                list_id = decode(msg.get("List-Id"))
                try:
                    date = email.utils.parsedate_to_datetime(msg.get("Date")).strftime("%Y-%m-%d")
                except Exception:
                    date = (msg.get("Date") or "")[:16]
                pts, why = score(sender, subject, to_field, list_id)
                rows.append((pts, date, sender, subject, why))

    rows.sort(key=lambda r: (-r[0], r[1]))
    keep = [r for r in rows if r[0] >= args.min_score]
    print(f"scanned {len(rows)} · worth a look: {len(keep)}\n")
    for pts, date, sender, subject, why in (rows if args.show_all else keep):
        print(f"[{pts:+d}] {date}  {sender[:58]}")
        print(f"      {subject[:92]}")
        print(f"      {', '.join(why)}\n")
    if not keep:
        print("Nothing in spam scored above the threshold. The filter is not eating anything.")
    else:
        print("Read-only: nothing was moved or marked. Rescue anything in Gmail with "
              "'Not spam', which also teaches the filter.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
