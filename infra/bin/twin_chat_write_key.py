#!/usr/bin/env python3
"""Put the Anthropic key where the chat service can read it, in RAM only.

Runs as root at service start, like the Hermes anthropic-key plugin before it: the instance role
reads the secret at runtime. The chat agent's OS user cannot reach that role, so root hands over
the key through /run, a tmpfs. The key is never written to disk and never printed.
"""
import os
import pwd
import sys

sys.path.insert(0, "/home/ec2-user/super-project")
from shared.claude import api_key  # noqa: E402

DIR = "/run/twin-chat"
PATH = os.path.join(DIR, "anthropic.env")

owner = pwd.getpwnam("twin-chat")
os.makedirs(DIR, mode=0o700, exist_ok=True)
os.chown(DIR, owner.pw_uid, owner.pw_gid)
descriptor = os.open(PATH + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    handle.write(f"ANTHROPIC_API_KEY={api_key()}\n")
os.chown(PATH + ".tmp", owner.pw_uid, owner.pw_gid)
os.replace(PATH + ".tmp", PATH)
