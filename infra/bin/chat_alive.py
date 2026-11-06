#!/usr/bin/env python3
"""Chat-alive heartbeat: emit the ChatServerUp metric only when chat can answer.

Chat is up when twin-chat.service is active AND the Telegram gateway process is running.
When either is missing this emits nothing, so the dead-man alarm twin-mind-chat-deadman fires.
Runs every 15 minutes (twin-chat-alive.timer).
"""
import glob
import subprocess
import sys

GATEWAY = "letta channel-gateway"


def is_up(service_active, cmdlines):
    return service_active and any(GATEWAY in c for c in cmdlines)


def cmdlines():
    out = []
    for path in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            with open(path, "rb") as f:
                out.append(f.read().replace(b"\0", b" ").decode("utf-8", "replace"))
        except OSError:  # the process exited while we scanned
            pass
    return out


def main():
    active = subprocess.run(["systemctl", "is-active", "--quiet", "twin-chat.service"]).returncode == 0
    if not is_up(active, cmdlines()):
        print("chat is down: no ChatServerUp metric sent", file=sys.stderr)
        return 0
    r = subprocess.run(["aws", "cloudwatch", "put-metric-data", "--namespace", "TwinMind",
                        "--metric-name", "ChatServerUp", "--value", "1", "--region", "eu-west-1"],
                       capture_output=True, timeout=30)
    if r.returncode:
        print("ChatServerUp metric failed: " + r.stderr.decode()[:200], file=sys.stderr)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
