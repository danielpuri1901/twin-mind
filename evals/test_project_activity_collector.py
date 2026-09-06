#!/usr/bin/env python3
"""End-to-end checks for the Mac-side Git activity collector."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "agents" / "brief" / "tools"
sys.path.insert(0, str(TOOLS))
import collect_project_activity as collector


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "Test User")
    git(path, "config", "user.email", "test@example.com")
    return path


def commit_files(repo: Path, subject: str, files: dict[str, str]) -> str:
    for relative, content in files.items():
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", subject)
    return git(repo, "rev-parse", "HEAD")


class CollectorTests(unittest.TestCase):
    def test_snapshot_includes_changed_names_without_file_contents(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            repo = make_repo(home / "Desktop" / "Projects" / "agentlab")
            commit_id = commit_files(
                repo,
                "feat: add guarded story generation",
                {"worker.py": "COMMITTED_SECRET", "delete.py": "remove me"},
            )
            (repo / "worker.py").write_text("TRACKED_SECRET")
            (repo / "delete.py").unlink()
            (repo / "draft.py").write_text("UNTRACKED_SECRET")

            snapshot = collector.collect_snapshot(home, datetime.now(timezone.utc))
            encoded = json.dumps(snapshot)

            self.assertEqual(snapshot["schema_version"], 1)
            self.assertIn(commit_id, encoded)
            self.assertIn("agentlab", encoded)
            self.assertIn("worker.py", encoded)
            self.assertIn("delete.py", encoded)
            self.assertIn("draft.py", encoded)
            self.assertNotIn(str(home), encoded)
            self.assertNotIn("COMMITTED_SECRET", encoded)
            self.assertNotIn("TRACKED_SECRET", encoded)
            self.assertNotIn("UNTRACKED_SECRET", encoded)

    def test_discovery_prunes_noise_without_a_depth_limit(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            wanted = make_repo(home / "a" / "b" / "c" / "d" / "e" / "project")
            make_repo(home / ".gemini" / "history" / "copy")
            make_repo(home / "app" / "node_modules" / "package")

            self.assertEqual(collector.discover_repositories(home), [wanted.resolve()])

    def test_sensitive_and_generated_paths_are_excluded(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            repo = make_repo(home / "project")
            commit_files(repo, "initial", {"app.py": "pass\n"})
            (repo / ".env").write_text("TOKEN=secret")
            (repo / "credentials.json").write_text("secret")
            (repo / "out").mkdir()
            (repo / "out" / "generated.py").write_text("secret")

            encoded = json.dumps(collector.collect_snapshot(home, datetime.now(timezone.utc)))

            self.assertNotIn(".env", encoded)
            self.assertNotIn("credentials.json", encoded)
            self.assertNotIn("generated.py", encoded)

    def test_write_snapshot_replaces_the_destination(self):
        with tempfile.TemporaryDirectory() as raw:
            destination = Path(raw) / "notes" / "project-activity.json"
            collector.write_snapshot({"schema_version": 1, "events": []}, destination)

            self.assertEqual(json.loads(destination.read_text())["schema_version"], 1)
            self.assertFalse(any(destination.parent.glob("*.tmp")))

    def test_publish_uses_one_rsync_transfer(self):
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "snapshot.json"
            source.write_text("{}")
            with mock.patch.object(collector.subprocess, "run") as run:
                collector.publish_snapshot(
                    source,
                    "twin-mind",
                    "/home/ec2-user/twin-corpus/notes/project-activity.json",
                )

            command = run.call_args.args[0]
            self.assertEqual(command[0], "rsync")
            self.assertEqual(command[-1], "twin-mind:/home/ec2-user/twin-corpus/notes/project-activity.json")
            self.assertTrue(run.call_args.kwargs["check"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
