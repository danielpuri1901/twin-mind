"""Hand Hermes the Anthropic API key at startup, from AWS Secrets Manager.

Hermes reads ANTHROPIC_API_KEY from the process environment when it builds a
client. Plugins register at gateway start, before any agent exists, so setting
the variable here is enough; the key never touches the box's disk. An
environment that already carries the key (a local run, a test) is left alone.
"""
import os
import sys
from pathlib import Path


def register(ctx):
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return
    root = Path.home() / "super-project"
    if not root.is_dir():
        root = Path.home() / "Super Project"
    sys.path.insert(0, str(root))
    from shared.claude import api_key
    os.environ["ANTHROPIC_API_KEY"] = api_key()
