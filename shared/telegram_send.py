#!/usr/bin/env python3
"""Send plain text to Daniel's Telegram home chat through the Bot API.

It also runs a scheduled job and forwards the job's stdout, which is the rule the
watchdog pattern depends on: a silent job stays silent, any output becomes a message,
and a non-zero exit is always reported.

    telegram_send.py "text"
    telegram_send.py --run /path/to/python agents/brief/tools/brief_check.py

Sending does not poll for updates, so it never conflicts with the chat agent that
holds the same bot token.
"""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

ENV = os.path.expanduser("~/.twin-mind/.env")
LIMIT = 4000  # Telegram rejects a message above 4096 characters


def env(key):
    """The process environment first, then the env file. Quotes a line may carry are stripped."""
    value = os.environ.get(key, "")
    if not value:
        with open(ENV, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith(key + "="):
                    value = line.split("=", 1)[1]
                    break
    return value.strip().strip("\"'")


def send(text):
    """Send `text`, split to fit the limit. Raises on any failure; returns the last API reply."""
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_HOME_CHANNEL")
    if not token or not chat:
        raise RuntimeError(f"TELEGRAM_BOT_TOKEN and TELEGRAM_HOME_CHANNEL must be set in {ENV}")
    thread = env("TELEGRAM_HOME_CHANNEL_THREAD_ID")
    reply = {}
    for start in range(0, len(text), LIMIT):
        fields = {"chat_id": chat, "text": text[start:start + LIMIT]}
        if thread:
            fields["message_thread_id"] = thread
        data = urllib.parse.urlencode(fields).encode()
        request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        reply = json.load(urllib.request.urlopen(request, timeout=20))
        if not reply.get("ok"):
            raise RuntimeError(f"Telegram refused the message: {reply.get('description')}")
    return reply


def run_job(command):
    """Run `command`, forward its stdout, report a failure. Returns the job's exit code."""
    job = subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if job.stderr:
        print(job.stderr, file=sys.stderr, end="")
    message = job.stdout.strip()
    if job.returncode != 0:
        last = (job.stderr.strip().splitlines() or ["no error output"])[-1][:300]
        message = f"JOB FAILED ({os.path.basename(command[-1])}, exit {job.returncode}): {last}\n\n{message}".strip()
    if message:
        send(message)
    return job.returncode


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--run":
        sys.exit(run_job(sys.argv[2:]))
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    send(sys.argv[1])
