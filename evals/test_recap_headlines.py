#!/usr/bin/env python3
"""Friday nudge headlines and recap CHANGELOG window accept both heading forms (2026-11-06):
`## DATE - title` and the newer bare `## DATE` with the summary on the first line below.
Deterministic, free, no network."""
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents", "weekly-recap", "tools"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
import nudge as N
import recap as R

d = lambda n: (datetime.now(N.TZ).date() - timedelta(days=n)).isoformat()
long_line = "word " * 60
path = os.path.join(tempfile.mkdtemp(), "CHANGELOG.md")
open(path, "w").write(f"""# Title

## {d(1)}

Bare form summary line.

- detail bullet

## {d(2)} (cost)

{long_line}

## {d(3)} - Old form title

- detail

## {d(30)}

Too old.
""")
N.CHANGELOG = R.CHANGELOG = path

heads = N.week_headlines()
assert heads[0] == "Bare form summary line.", heads
assert heads[1].endswith("...") and len(heads[1]) == 120, heads[1]
assert heads[2] == "Old form title", heads
assert len(heads) == 3, heads

block = R.changelog_week()
assert "Bare form summary line." in block and "Old form title" in block and "Too old." not in block
print("recap headlines: ok")
