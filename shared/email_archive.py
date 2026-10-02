"""Label the backlog from senders Daniel never opens, so it can be archived in one action.

Unsubscribing stops new mail arriving. It does nothing about the thousands of
messages already sitting in the inbox, so this is the other half of the job.

THIS TOOL LABELS. IT DOES NOT ARCHIVE, AND IT CANNOT.

That is a correction, not a design choice. The first version tried to archive
over IMAP with Google's X-GM-LABELS extension, on the reasoning that archiving
in Gmail IS removing the Inbox label:

    UID STORE <ids> -X-GM-LABELS (\\Inbox)

It returned OK on all 8,266 messages and changed nothing. Fetching X-GM-LABELS
on a real inbox message returns only ("\\Important"): Gmail does not expose
\\Inbox through that extension, so there is no Inbox label there to remove.
A command that succeeds and does nothing is worse than one that fails, which
is why the run is now verified by re-counting rather than by its exit code.

The two mechanisms that DO archive over IMAP both go through delete semantics:
setting \\Deleted and expunging, or MOVE, which is COPY plus the same. Gmail
has an account setting for what that means, and its options include moving the
message to Trash and deleting it forever. The setting cannot be read over
IMAP, so a script using either one is gambling on a value it cannot see. This
tool will not do that.

So it does the part that is hard and safe, and leaves the trivial part to
Gmail. It works out which senders are junk, protects banks, government,
university, job applications and account security, and tags the result. The
archiving is then one action in Gmail:

    search:  in:inbox label:"Bulk/Never opened"
    select all, then Archive

Nothing here deletes, nothing is marked read, and the label is reversible.

    email-archive                    # dry run, counts only, no writes
    email-archive --execute          # apply the label
    email-archive --verify           # count what is tagged and still in the inbox
    email-archive --restore          # remove the label again
"""

import argparse
import email
import imaplib
import json
import os
import re
import sys
from datetime import datetime

HOST = "imap.gmail.com"
INBOX = "INBOX"
LABEL = "Bulk/Never opened"
BATCH = 200
RESTORE = os.path.expanduser("~/email-archive-restore.json")

# Never archive these. The rule is matched against the sender's DOMAIN SUFFIX,
# not against a substring of the address, because the first version did the
# latter and let two through that mattered: "@abnamro" did not match
# abnamro@nl.abnamro.com, and "@uva.nl" did not match intree@e.uva.nl. Mail
# from a subdomain is still mail from the institution.
PROTECTED_DOMAINS = {
    # money
    "abnamro.com", "abnamro.nl", "ing.nl", "rabobank.nl", "bunq.com", "revolut.com",
    "bankofamerica.com", "chase.com", "americanexpress.com", "stripe.com", "paypal.com",
    "wise.com", "n26.com", "mastercard.com", "visa.com",
    # government and tax
    "overheid.nl", "belastingdienst.nl", "ind.nl", "digid.nl", "duo.nl", "svb.nl",
    "amsterdam.nl", "rijksoverheid.nl",
    # university and coursework
    "uva.nl", "vu.nl", "instructure.com", "ans.app", "canvas.net", "studeersnel.nl",
    "ie.edu", "jobteaser.com",
    # job applications and applicant tracking
    "ashbyhq.com", "greenhouse.io", "lever.co", "workday.com", "myworkday.com",
    "workablemail.com", "workable.com", "jobs2web.com", "ripplematch.com",
    "smartrecruiters.com", "teamtailor.com", "recruitee.com", "bamboohr.com",
    # account security and identity
    "accounts.google.com", "google.com", "apple.com", "icloud.com", "1password.com",
    "authy.com", "okta.com",
    # things this project actually runs on
    "vodafone.nl",
    "granola.ai", "palantirfoundry.com", "anthropic.com", "openai.com", "langchain.com",
    "amazonaws.com", "aws.amazon.com", "github.com", "gitlab.com", "atlassian.net",
}

# Belt and braces on top of the domain list: an address or display name saying
# it is about a transaction, an account, or an application.
PROTECT = re.compile(
    r"messages-noreply@linkedin|inmail|mailer-daemon|"
    r"invoice|receipt|order|shipping|tracking|delivery|dispatch|billing|"
    r"security|verify|verification|password|2fa|mfa|one-?time|confirm|"
    r"application|interview|offer|contract|payslip|salaris|factuur|"
    r"tikkie|incasso|betaal",
    re.I)


def domain_of(addr):
    return (addr or "").rsplit("@", 1)[-1].lower()


def protected(sender, name=""):
    """True when this sender must never be archived.

    Domain match walks up the labels so a subdomain is covered: mail from
    e.uva.nl is matched by uva.nl.
    """
    if PROTECT.search((sender or "") + " " + (name or "")):
        return True
    parts = domain_of(sender).split(".")
    for i in range(len(parts) - 1):
        if ".".join(parts[i:]) in PROTECTED_DOMAINS:
            return True
    return False


def load_env(path=os.path.expanduser("~/.hermes/.env")):
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


def connect():
    load_env()
    user = os.environ.get("TWIN_SMTP_ADDRESS")
    pw = os.environ.get("TWIN_SMTP_APP_PASSWORD")
    if not user or not pw:
        print("no mail credentials in ~/.hermes/.env", file=sys.stderr)
        sys.exit(2)
    im = imaplib.IMAP4_SSL(HOST)
    im.login(user, pw)
    return im


def uids_from(im, sender, since=None):
    """UIDs of this sender's messages that are still in the inbox.

    `since` bounds the search the way the census was bounded. Without it this
    searches all time, which on 2026-09-28 turned a 9,567 message job into a
    46,391 message one without saying so.
    """
    crit = ["FROM", f'"{sender}"']
    if since:
        crit = ["SINCE", since] + crit
    typ, data = im.uid("SEARCH", None, *crit)
    if typ != "OK" or not data or not data[0]:
        return []
    return data[0].split()


def store(im, uids, item, value):
    """UID STORE in batches. The only mutating call in this file.

    Asserts on the flag name because the whole safety argument rests on
    \\Deleted never being set here.
    """
    assert "DELETED" not in value.upper(), "this tool must never set \\Deleted"
    for i in range(0, len(uids), BATCH):
        chunk = b",".join(uids[i:i + BATCH]).decode()
        typ, _ = im.uid("STORE", chunk, item, value)
        if typ != "OK":
            print(f"  STORE failed on a batch of {len(uids[i:i + BATCH])}", file=sys.stderr)


def restore(im):
    """Remove the label this tool applied.

    The earlier version tried to re-add \\Inbox, which was the mirror of a
    removal that never happened. Removing the label is the real inverse of
    what this tool does.
    """
    try:
        saved = json.load(open(RESTORE))
    except OSError:
        print(f"no restore file at {RESTORE}", file=sys.stderr)
        return 1
    im.select(INBOX)
    total = 0
    for sender, uids in saved["senders"].items():
        # UIDs are only valid while UIDVALIDITY holds; re-search instead.
        found = uids_from(im, sender)
        if not found:
            typ, data = im.uid("SEARCH", None, "X-GM-RAW", f'"from:{sender} label:{LABEL}"')
            found = data[0].split() if typ == "OK" and data and data[0] else []
        if found:
            store(im, found, "-X-GM-LABELS", f'("{saved["label"]}")')
            total += len(found)
        print("%-42s untagged %d (tagged %d)" % (sender[:42], len(found), len(uids)))
    print(f"\nremoved the label from {total} messages")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--census", default=os.path.expanduser("~/email-census.json"))
    ap.add_argument("--min-unread-pct", type=int, default=90)
    ap.add_argument("--min-total", type=int, default=5)
    ap.add_argument("--label", default=LABEL)
    ap.add_argument("--since", default="01-Oct-2025",
                    help="IMAP date bound, matching the census window. "
                         "Pass an empty string for all time.")
    ap.add_argument("--execute", action="store_true", help="tag and archive (default: count only)")
    ap.add_argument("--restore", action="store_true", help="remove the label again")
    ap.add_argument("--verify", action="store_true",
                    help="count what carries the label and what is still in the inbox")
    args = ap.parse_args()

    im = connect()
    try:
        if args.restore:
            return restore(im)

        if args.verify:
            for box in (f'"{args.label}"', "INBOX"):
                typ, d = im.select(box, readonly=True)
                print("%-24s %s" % (box, d[0].decode() if typ == "OK" else "not found"))
            im.select(INBOX, readonly=True)
            typ, d = im.uid("SEARCH", None, "X-GM-RAW",
                            f'"in:inbox label:\\"{args.label}\\""')
            n = len(d[0].split()) if typ == "OK" and d and d[0] else 0
            print(f"\ntagged and still in the inbox: {n}")
            print("0 means the Gmail archive step is done." if n == 0 else
                  "Archive them in Gmail: search  in:inbox label:\"" + args.label + "\"")
            return 0

        data = json.load(open(args.census))
        targets = [s for s in data["senders"]
                   if s["never_opened_pct"] >= args.min_unread_pct
                   and s["total"] >= args.min_total
                   and not protected(s["sender"], s.get("name"))]
        held = [s for s in data["senders"]
                if s["never_opened_pct"] >= args.min_unread_pct
                and s["total"] >= args.min_total
                and protected(s["sender"], s.get("name"))]
        if held:
            print(f"HELD, never archived ({len(held)} senders):")
            for h in sorted(held, key=lambda x: -x["total"]):
                print("  %-44s %5d  %s" % (h["sender"][:44], h["total"], h.get("name", "")[:34]))
            print()
        print(f"{len(targets)} senders match (>={args.min_unread_pct}% unread, "
              f">={args.min_total} messages, not protected)")
        print(f"window: {'since ' + args.since if args.since else 'ALL TIME'}\n")

        im.select(INBOX, readonly=not args.execute)
        done, touched = {}, 0
        for t in targets:
            uids = uids_from(im, t["sender"], args.since)
            if not uids:
                continue
            if args.execute:
                store(im, uids, "+X-GM-LABELS", f'("{args.label}")')
                done[t["sender"]] = [u.decode() for u in uids]
            touched += len(uids)
            print("%-42s %6d in inbox  (%d total, %d%% unread)"
                  % (t["sender"][:42], len(uids), t["total"], t["never_opened_pct"]))

        print(f"\n{touched} messages in the inbox from {len(targets)} senders")
        if args.execute:
            json.dump({"ran": datetime.now().isoformat(), "label": args.label,
                       "senders": done}, open(RESTORE, "w"), indent=1)
            print(f"labelled '{args.label}'. Restore file: {RESTORE}")
            print("Nothing was deleted, archived, or marked read.")
            print("\nTo archive them, in Gmail:")
            print(f'  search   in:inbox label:"{args.label}"')
            print("  select all, then Archive")
            print("\nUndo the label with: email-archive --restore")
        else:
            print("\ndry run. Nothing was written. Re-run with --execute.")
        return 0
    finally:
        try:
            im.logout()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
