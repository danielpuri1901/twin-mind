#!/usr/bin/env python3
"""Test: build_index + corpus_search behave per the retrieval contract."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

TOOLS = os.path.dirname(os.path.abspath(__file__))


def test_build_and_search():
    with tempfile.TemporaryDirectory() as td:
        norm = os.path.join(td, "normalized")
        os.makedirs(norm)
        rec = {"source": "imessage", "chat": "c1", "date": "2026-01-01T10:00:00",
               "who": "me", "sender": "Me", "text": "gurobi presolve trick"}
        with open(os.path.join(norm, "x.jsonl"), "w") as f:
            f.write(json.dumps(rec) + "\n")
        env = dict(os.environ, TWIN_CORPUS=td)

        subprocess.run([sys.executable, os.path.join(TOOLS, "build_index.py")],
                       check=True, env=env)
        db = sqlite3.connect(os.path.join(td, "index", "corpus.db"))
        rows = db.execute("SELECT text FROM msgs WHERE msgs MATCH 'gurobi'").fetchall()
        assert rows == [("gurobi presolve trick",)], rows

        out = subprocess.run(
            [sys.executable, os.path.join(TOOLS, "corpus_search.py"), "gurobi", "--k", "5"],
            check=True, env=env, capture_output=True, text=True).stdout.strip()
        hit = json.loads(out)
        assert hit["text"] == "gurobi presolve trick" and hit["who"] == "me", hit


if __name__ == "__main__":
    test_build_and_search()
    print("ok")
