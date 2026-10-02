"""Write a Gmail filter file for senders that have no working unsubscribe.

Three groups end up here, and all three need the same thing for the same
reason: there is no way to make them stop at the source.

  no List-Unsubscribe header   Steam, metalshop, Songkick, SoundCloud, G2A.
                               The opt-out lives in an account setting on
                               their website, not in the mail.
  HTTP 403 on one-click        Bloomberg, Medium. They publish a one-click
                               endpoint and then refuse anything that is not
                               a browser.
  still arriving               anything unsubscribed that keeps sending,
                               which is common for a week or two.

A filter is the only mechanism left, and it is the better one anyway: it acts
before the message is ever seen, so the inbox stays clean without a second
cleanup in six months.

Gmail cannot import filters over IMAP or through an app password, so this
writes the XML that Gmail's own importer reads:

    Gmail -> Settings -> Filters and Blocked Addresses -> Import filters

Each filter archives and marks as read. None of them delete, and none of them
mark as spam, which would train Gmail against a sender Daniel may later want.

    make-mail-filters                      # the seven that have no opt-out
    make-mail-filters --from-plan          # add anything that failed to unsubscribe
"""

import argparse
import json
import os
import sys
from xml.sax.saxutils import quoteattr

# No List-Unsubscribe header at all, measured 2026-09-28.
NO_HEADER = [
    ("noreply@steampowered.com", "Steam"),
    ("info@newsletter.metalshop.nl", "Metalshop"),
    ("emails@songkick.com", "Songkick"),
    ("info@announcements.soundcloud.com", "SoundCloud"),
    ("feedback@g2a.com", "G2A"),
]

# Publish a one-click endpoint and then reject the POST.
REFUSED = [
    ("noreply@news.bloomberg.com", "Bloomberg, HTTP 403"),
    ("noreply@medium.com", "Medium, HTTP 403"),
]

LABEL = "Bulk/Filtered"

ENTRY = """  <entry>
    <category term='filter'></category>
    <title>Mail Filter</title>
    <id>tag:mail.google.com,2008:filter:{n}</id>
    <content></content>
    <apps:property name='from' value={sender}/>
    <apps:property name='shouldArchive' value='true'/>
    <apps:property name='shouldMarkAsRead' value='true'/>
    <apps:property name='label' value={label}/>
    <apps:property name='sizeOperator' value='s_sl'/>
    <apps:property name='sizeUnit' value='s_smb'/>
  </entry>
"""


def build(rows, label):
    body = "".join(
        ENTRY.format(n=i + 1, sender=quoteattr(addr), label=quoteattr(label))
        for i, (addr, _why) in enumerate(rows))
    return ("<?xml version='1.0' encoding='UTF-8'?>\n"
            "<feed xmlns='http://www.w3.org/2005/Atom' "
            "xmlns:apps='http://schemas.google.com/apps/2006'>\n"
            "  <title>Mail Filters</title>\n" + body + "</feed>\n")


SWEEP = """  <entry>
    <category term='filter'></category>
    <title>Mail Filter</title>
    <id>tag:mail.google.com,2008:filter:sweep</id>
    <content></content>
    <apps:property name='hasTheWord' value={q}/>
    <apps:property name='shouldArchive' value='true'/>
    <apps:property name='sizeOperator' value='s_sl'/>
    <apps:property name='sizeUnit' value='s_smb'/>
  </entry>
"""


def sweep(label):
    """A filter whose only job is to archive what is already tagged.

    Gmail's UI caps a manual selection at one page, so archiving thousands of
    conversations by hand is not practical. The filter import page has an
    "Apply new filters to existing email" checkbox, which applies the rule
    retroactively in one action, and that is the lever this uses.

    Gmail filters cannot match on a label directly, but the "has the words"
    field accepts full search syntax, so `label:"..."` works there.
    """
    return ("<?xml version='1.0' encoding='UTF-8'?>\n"
            "<feed xmlns='http://www.w3.org/2005/Atom' "
            "xmlns:apps='http://schemas.google.com/apps/2006'>\n"
            "  <title>Mail Filters</title>\n"
            + SWEEP.format(q=quoteattr(f'label:"{label}"')) + "</feed>\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.expanduser("~/mailFilters.xml"))
    ap.add_argument("--label", default=LABEL)
    ap.add_argument("--taxonomy", action="store_true",
                    help="write the standing category filters (jobs, money, uni, "
                         "government, security, orders, travel, tools)")
    ap.add_argument("--sweep", action="store_true",
                    help="write a single filter that archives everything already "
                         "carrying --label, for a one-action bulk cleanup")
    ap.add_argument("--from-plan", default="",
                    help="an email-unsubscribe-plan.json; adds every sender whose "
                         "unsubscribe failed")
    args = ap.parse_args()

    if args.taxonomy:
        out = args.out.replace(".xml", "-taxonomy.xml")
        open(out, "w").write(taxonomy_xml(TAXONOMY))
        print(f"{len(TAXONOMY)} category filters -> {out}\n")
        for r in TAXONOMY:
            flags = []
            if r.get("important"):
                flags.append("mark important")
            flags.append("never spam")
            print("  %-14s %-3d rules   %s" % (r["label"],
                  len(r.get("from", [])) + (1 if r.get("words") else 0),
                  ", ".join(flags)))
            print("  %-14s %s\n" % ("", r["why"]))
        print("Gmail -> Settings -> Filters and Blocked Addresses -> Import filters")
        print("Tick 'Apply new filters to existing email' to label the history too.")
        print("None of these archive or delete. They label, and flag the urgent ones.")
        return 0

    if args.sweep:
        out = args.out.replace(".xml", "-sweep.xml") if args.out.endswith(".xml") else args.out
        open(out, "w").write(sweep(args.label))
        print(f"one sweep filter -> {out}\n")
        print(f'  matches: label:"{args.label}"')
        print("  action:  skip the inbox (archive it)\n")
        print("Gmail -> Settings -> Filters and Blocked Addresses -> Import filters")
        print("TICK 'Apply new filters to existing email' on the import screen.")
        print("That is what archives the backlog. Without it the filter only affects new mail.")
        print("\nIt does not delete, does not mark read, and can be deleted afterwards.")
        return 0

    rows = NO_HEADER + REFUSED
    if args.from_plan:
        try:
            plan = json.load(open(args.from_plan))
        except OSError as exc:
            print(f"could not read the plan: {exc}", file=sys.stderr)
            return 1
        known = {a for a, _ in rows}
        for r in plan:
            if r.get("result", "").startswith("failed") and r["sender"] not in known:
                rows.append((r["sender"], r["result"]))
                known.add(r["sender"])

    open(args.out, "w").write(build(rows, args.label))
    print(f"{len(rows)} filters -> {args.out}\n")
    for addr, why in rows:
        print("  %-42s %s" % (addr, why))
    print("\nGmail -> Settings -> Filters and Blocked Addresses -> Import filters")
    print(f"Each one archives, marks as read, and labels '{args.label}'. None delete.")
    return 0




# ---------------------------------------------------------------------------
# The standing taxonomy.
#
# Built from the senders the census actually found, not from a generic set of
# folders. Each rule is deterministic: a domain or a word, never a judgement.
# That matters because a filter runs on every message forever, so a rule that
# is right 90% of the time is wrong thousands of times.
#
# Order is not significant to Gmail, which applies every matching filter, so
# the categories are kept disjoint by domain. The one overlap that is
# deliberate: a bulk sender can also carry a category label, because knowing
# an archived message was an order still helps when searching for it.
#
# markImportant is used sparingly. Marking everything important marks nothing
# important. It is reserved for mail with a deadline or money attached.
# ---------------------------------------------------------------------------

TAXONOMY = [
    {
        "label": "1 Jobs",
        "why": "applicant tracking systems: an interview invitation must never be missed",
        "important": True, "never_spam": True,
        "from": ["ashbyhq.com", "greenhouse.io", "lever.co", "hire.lever.co",
                 "myworkday.com", "workday.com", "workablemail.com", "workable.com",
                 "jobs2web.com", "ripplematch.com", "smartrecruiters.com",
                 "teamtailor.com", "recruitee.com", "bamboohr.com", "ashbyhq.com"],
    },
    {
        "label": "2 Money",
        "why": "banks, cards and recurring bills",
        "important": True, "never_spam": True,
        "from": ["nl.abnamro.com", "abnamro.com", "ing.nl", "rabobank.nl", "bunq.com",
                 "revolut.com", "emcom.bankofamerica.com", "member.americanexpress.com",
                 "stripe.com", "paypal.com", "wise.com", "vodafone.nl",
                 "googleone-noreply@google.com"],
    },
    {
        "label": "3 University",
        "why": "UvA, Canvas, exams and the career centre",
        "important": False, "never_spam": True,
        "from": ["uva.nl", "e.uva.nl", "vu.nl", "instructure.com", "ans.app",
                 "comms.ie.edu", "jobteaser.com", "communications.jobteaser.com",
                 "studeersnel.nl"],
    },
    {
        "label": "4 Government",
        "why": "anything with a statutory deadline",
        "important": True, "never_spam": True,
        "from": ["overheid.nl", "belastingdienst.nl", "ind.nl", "digid.nl", "duo.nl",
                 "svb.nl", "rijksoverheid.nl", "amsterdam.nl"],
    },
    {
        "label": "5 Security",
        "why": "sign-in alerts and verification codes, which are worthless late",
        "important": True, "never_spam": True,
        "from": ["accounts.google.com", "noreply-accounts@google.com",
                 "no_reply@email.apple.com", "noreply@email.apple.com",
                 "1password.com", "okta.com", "authy.com"],
        "words": 'subject:("verification code" OR "sign-in" OR "security alert" OR '
                 '"new device" OR "password was" OR "two-factor")',
    },
    {
        "label": "6 Orders",
        "why": "the event-driven half of retail, which the unsubscribe pass deliberately kept",
        "important": False, "never_spam": True,
        "words": 'subject:(order OR bestelling OR invoice OR factuur OR receipt OR '
                 'bon OR shipped OR verzonden OR delivery OR bezorgd OR tracking OR '
                 '"track your" OR refund)',
    },
    {
        "label": "7 Travel",
        "why": "boarding passes and tickets, needed on a date",
        "important": False, "never_spam": True,
        "from": ["ns.nl", "flixbus.com", "travel.mail.flixbus.com", "swiss.com",
                 "austrian.com", "brusselsairlines.com", "my.lufthansa.com",
                 "milesandmore.com", "booking.com", "airbnb.com", "ticketswap.com",
                 "ticketmaster.nl"],
    },
    {
        "label": "8 Tools",
        "why": "the services this project runs on",
        "important": False, "never_spam": True,
        "from": ["granola.ai", "mail.granola.ai", "palantirfoundry.com", "notion.so",
                 "mail.notion.so", "slack.com", "atlassian.net", "po.atlassian.net",
                 "github.com", "anthropic.com", "openai.com", "amazonaws.com",
                 "railway.app", "vercel.com", "langchain.com", "cursor.com",
                 # Found in spam on 2026-09-28. Gmail bins the whole eval and
                 # retrieval tooling category as marketing, which is wrong for
                 # someone whose current project IS evals.
                 "arize.com", "exa.ai", "braintrustdata.com", "gurobi.com",
                 "tavily.com", "langfuse.com", "smith.langchain.com",
                 "elevenlabs.io", "posthog.com", "supabase.com", "resend.com"],
    },
]

CAT = """  <entry>
    <category term='filter'></category>
    <title>Mail Filter</title>
    <id>tag:mail.google.com,2008:filter:cat{n}</id>
    <content></content>
{props}    <apps:property name='label' value={label}/>
    <apps:property name='shouldNeverSpam' value='true'/>
{important}    <apps:property name='sizeOperator' value='s_sl'/>
    <apps:property name='sizeUnit' value='s_smb'/>
  </entry>
"""


def taxonomy_xml(rules):
    """One filter per category. Senders are ORed into a single `from` field,
    which is how Gmail expresses a sender list without a filter each."""
    out = []
    for i, r in enumerate(rules, 1):
        props = ""
        if r.get("from"):
            props += ("    <apps:property name='from' value=%s/>\n"
                      % quoteattr(" OR ".join(r["from"])))
        if r.get("words"):
            props += ("    <apps:property name='hasTheWord' value=%s/>\n"
                      % quoteattr(r["words"]))
        important = ("    <apps:property name='shouldAlwaysMarkAsImportant' value='true'/>\n"
                     if r.get("important") else "")
        out.append(CAT.format(n=i, props=props, label=quoteattr(r["label"]),
                              important=important))
    return ("<?xml version='1.0' encoding='UTF-8'?>\n"
            "<feed xmlns='http://www.w3.org/2005/Atom' "
            "xmlns:apps='http://schemas.google.com/apps/2006'>\n"
            "  <title>Mail Filters</title>\n" + "".join(out) + "</feed>\n")

if __name__ == "__main__":
    sys.exit(main())
