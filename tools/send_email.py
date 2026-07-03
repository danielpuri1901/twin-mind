#!/usr/bin/env python3
"""
send_email.py - the twin's send-only email channel (morning brief).
SMTP via Daniel's Gmail app password. Send-only: never touches the inbox.
Recipient is hard-locked to Daniel himself; sending to him is pre-approved
(project rule); anything else must go through a human gate - so it refuses.

Usage: send_email.py "Subject" < body.md      (or --body "text")
Env (from ~/.hermes/.env): TWIN_SMTP_ADDRESS, TWIN_SMTP_APP_PASSWORD
"""
import argparse
import os
import smtplib
import sys
from email.mime.text import MIMEText

ENV = os.path.expanduser("~/.hermes/.env")
if os.path.exists(ENV):
    for line in open(ENV):
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.strip().partition("=")
            os.environ.setdefault(k, v)

ME = os.environ.get("TWIN_SMTP_ADDRESS", "danielpuri1901@gmail.com")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("subject")
    ap.add_argument("--body", default=None)
    ap.add_argument("--to", default=ME)
    args = ap.parse_args()

    if args.to.lower() != ME.lower():
        sys.exit("REFUSED: this channel only sends to Daniel himself. "
                 "External sends require the human-gated path.")

    body = args.body if args.body is not None else sys.stdin.read()
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = args.subject
    msg["From"] = ME
    msg["To"] = ME

    pw = os.environ["TWIN_SMTP_APP_PASSWORD"]
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
        s.starttls()
        s.login(ME, pw)
        s.send_message(msg)
    print(f"sent: '{args.subject}' -> {ME}")


if __name__ == "__main__":
    main()
