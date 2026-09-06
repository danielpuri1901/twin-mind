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

    def test_nested_untracked_files_are_named_individually(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            repo = make_repo(home / "project")
            commit_files(repo, "initial", {"app.py": "pass\n"})
            nested = repo / "new" / "feature.py"
            nested.parent.mkdir()
            nested.write_text("PRIVATE_SOURCE")

            encoded = json.dumps(collector.collect_snapshot(home, datetime.now(timezone.utc)))

            self.assertIn("new/feature.py", encoded)
            self.assertNotIn("PRIVATE_SOURCE", encoded)

    def test_discovery_prunes_noise_without_a_depth_limit(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            wanted = make_repo(home / "a" / "b" / "c" / "d" / "e" / "project")
            make_repo(home / ".gemini" / "history" / "copy")
            make_repo(home / "app" / "node_modules" / "package")

            self.assertEqual(collector.discover_repositories(home), [wanted.resolve()])

    def test_discovery_includes_linked_worktrees(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            repo = make_repo(home / "project")
            commit_files(repo, "initial", {"app.py": "pass\n"})
            git(repo, "branch", "feature")
            worktree = repo / ".worktrees" / "feature"
            git(repo, "worktree", "add", "-q", str(worktree), "feature")
            feature_id = commit_files(worktree, "feat: linked worktree", {"feature.py": "pass\n"})

            repositories = collector.discover_repositories(home)
            snapshot = collector.collect_snapshot(home, datetime.now(timezone.utc))

            self.assertIn(repo.resolve(), repositories)
            self.assertIn(worktree.resolve(), repositories)
            feature = next(event for event in snapshot["events"] if event["event_id"] == feature_id)
            self.assertEqual(feature["project"], "project")
            self.assertEqual(feature["paths"], ["feature.py"])
            self.assertFalse(any(
                path.startswith(".worktrees/")
                for event in snapshot["events"]
                for path in event["paths"]
            ))
            event_ids = [event["event_id"] for event in snapshot["events"]]
            self.assertEqual(len(event_ids), len(set(event_ids)))

    def test_dirty_ids_are_namespaced_by_repository(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            first = make_repo(home / "first")
            second = make_repo(home / "second")
            commit_files(first, "initial", {"app.py": "pass\n"})
            commit_files(second, "initial", {"app.py": "pass\n"})
            (first / "draft.py").write_text("one")
            (second / "draft.py").write_text("two")

            snapshot = collector.collect_snapshot(home, datetime.now(timezone.utc))
            dirty_ids = [event["event_id"] for event in snapshot["events"] if event["kind"] == "dirty"]

            self.assertEqual(len(dirty_ids), 2)
            self.assertEqual(len(set(dirty_ids)), 2)

    def test_current_deletion_is_not_filtered_by_index_mtime(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            repo = make_repo(home / "project")
            commit_files(repo, "initial", {"delete.py": "remove me"})
            os.utime(repo / ".git" / "index", (1, 1))
            (repo / "delete.py").unlink()

            snapshot = collector.collect_snapshot(home, datetime.now(timezone.utc))
            dirty_paths = [
                path
                for event in snapshot["events"]
                if event["kind"] == "dirty"
                for path in event["paths"]
            ]

            self.assertIn("delete.py", dirty_paths)

    def test_sensitive_and_generated_paths_are_excluded(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            repo = make_repo(home / "project")
            commit_files(repo, "initial", {"app.py": "pass\n"})
            (repo / ".env").write_text("TOKEN=secret")
            (repo / "credentials.json").write_text("secret")
            (repo / "out").mkdir()
            (repo / "out" / "generated.py").write_text("secret")
            (repo / "vendor").mkdir()
            (repo / "vendor" / "package.py").write_text("secret")
            (repo / "target").mkdir()
            (repo / "target" / "artifact.py").write_text("secret")
            (repo / "coverage").mkdir()
            (repo / "coverage" / "report.json").write_text("secret")
            (repo / "secrets.py").write_text("secret")
            (repo / "token.txt").write_text("secret")
            (repo / ".netrc").write_text("secret")
            (repo / "service-account.json").write_text("secret")
            (repo / "kubeconfig").write_text("secret")
            (repo / "api_key.py").write_text("secret")
            (repo / "private_key.py").write_text("secret")
            (repo / ".ssh").mkdir()
            (repo / ".ssh" / "id_rsa").write_text("secret")
            for name in ("program.exe", "installer.dmg", "image.webp", "diagram.svg", "audio.mp3", "archive.7z"):
                (repo / name).write_text("binary")

            encoded = json.dumps(collector.collect_snapshot(home, datetime.now(timezone.utc)))

            self.assertNotIn(".env", encoded)
            self.assertNotIn("credentials.json", encoded)
            self.assertNotIn("generated.py", encoded)
            self.assertNotIn("package.py", encoded)
            self.assertNotIn("artifact.py", encoded)
            self.assertNotIn("report.json", encoded)
            self.assertNotIn("secrets.py", encoded)
            self.assertNotIn("token.txt", encoded)
            self.assertNotIn("id_rsa", encoded)
            for name in (
                ".netrc", "service-account.json", "kubeconfig", "api_key.py", "private_key.py",
                "program.exe", "installer.dmg", "image.webp", "diagram.svg", "audio.mp3", "archive.7z",
            ):
                self.assertNotIn(name, encoded)

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
