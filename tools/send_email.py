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

    # Dead-man's switch: heartbeat on every successful brief send (code-level,
    # so the LLM can't forget it). A CloudWatch alarm screams if 24h pass silent.
    if args.subject.lower().startswith("morning brief"):
        try:  # cursor: next brief triages mail since THIS send - no window gaps
            sd = os.path.expanduser("~/.hermes/state"); os.makedirs(sd, exist_ok=True)
            open(os.path.join(sd, "last_brief_sent"), "w").write(datetime.now().astimezone().isoformat())
        except Exception as e:
            print(f"cursor write failed (non-fatal): {e}")
        try:  # aws CLI is preinstalled on the box and the Mac - zero python deps
            import subprocess
            subprocess.run(["aws", "cloudwatch", "put-metric-data",
                            "--namespace", "TwinMind", "--metric-name", "BriefSent",
                            "--value", "1", "--region", "eu-west-1"],
                           check=True, capture_output=True, timeout=30)
            print("heartbeat: BriefSent metric emitted")
        except Exception as e:  # never let the ping break the mail
            print(f"heartbeat FAILED (mail still sent): {e}")


if __name__ == "__main__":
    main()
