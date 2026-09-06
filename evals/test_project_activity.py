#!/usr/bin/env python3
"""Deterministic tests for technical activity clustering and novelty."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "agents" / "brief" / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT))

import project_activity as activity
from shared import novelty

NOW = datetime.now(timezone.utc)


def event(
    event_id: str,
    project: str,
    timestamp: int,
    subject: str,
    paths: list[str],
    repo_id: Optional[str] = None,
) -> dict:
    return {
        "event_id": event_id,
        "kind": "commit",
        "project": project,
        "repo_id": repo_id or project,
        "time": timestamp,
        "subject": subject,
        "paths": paths,
    }


def write_snapshot(path: Path, events: list[dict], generated_at: Optional[int] = None) -> None:
    path.write_text(json.dumps({
        "schema_version": 1,
        "generated_at": generated_at or int(NOW.timestamp()),
        "lookback_days": 14,
        "events": events,
    }))


class ProjectActivityTests(unittest.TestCase):
    def test_legacy_topics_seed_the_semantic_store_atomically(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            legacy = root / "technical-covered.txt"
            store = root / "seen-technical.jsonl"
            legacy.write_text(
                "2026-07-24: prompt caching\n"
                "Saturday 25 July: Structured output enforcement\n"
            )
            vectors = [
                ("prompt caching", [1.0, 0.0]),
                ("Structured output enforcement", [0.0, 1.0]),
            ]

            with mock.patch.object(activity, "filter_novel_with_vectors", return_value=vectors) as embed:
                seeded = activity.ensure_technical_history(str(legacy), str(store))

            self.assertTrue(seeded)
            embed.assert_called_once_with(
                ["prompt caching", "Structured output enforcement"],
                store=mock.ANY,
                fail_open=False,
            )
            rows = [json.loads(line) for line in store.read_text().splitlines()]
            self.assertEqual([row["text"] for row in rows], [item[0] for item in vectors])
            self.assertTrue(all(row["vec"] for row in rows))
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_existing_semantic_store_is_never_reseeded(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            legacy = root / "technical-covered.txt"
            store = root / "seen-technical.jsonl"
            legacy.write_text("2026-07-24: prompt caching\n")
            store.write_text(json.dumps({"text": "existing", "vec": [1.0]}) + "\n")

            with mock.patch.object(activity, "filter_novel_with_vectors") as embed:
                seeded = activity.ensure_technical_history(str(legacy), str(store))

            self.assertTrue(seeded)
            embed.assert_not_called()
            self.assertEqual(json.loads(store.read_text())["text"], "existing")

    def test_legacy_seed_fails_closed_when_embedding_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            legacy = root / "technical-covered.txt"
            store = root / "seen-technical.jsonl"
            legacy.write_text("2026-07-24: prompt caching\n")

            with mock.patch.object(activity, "filter_novel_with_vectors", return_value=[]):
                seeded = activity.ensure_technical_history(str(legacy), str(store))

            self.assertFalse(seeded)
            self.assertFalse(store.exists())

    def test_related_agentlab_commits_become_one_work_session(self):
        clusters = activity.cluster_events([
            event("a", "agentlab", 1000, "feat: compose story videos", ["worker.py"]),
            event("b", "agentlab", 2000, "fix: enforce timing limits", ["worker.py", "video.py"]),
            event("c", "agentlab", 3000, "fix: harden story quality", ["video.py"]),
        ])

        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].event_ids, ("a", "b", "c"))
        self.assertEqual(clusters[0].project, "agentlab")

    def test_different_repositories_and_distant_commits_do_not_cluster(self):
        clusters = activity.cluster_events([
            event("a", "agentlab", 1000, "feat: worker", ["worker.py"]),
            event("b", "other", 2000, "fix: worker", ["worker.py"]),
            event("c", "agentlab", 1000 + 7 * 3600, "fix: worker", ["worker.py"]),
        ])

        self.assertEqual(len(clusters), 3)

    def test_shortlist_prefers_technical_work_and_drops_noise(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            snapshot = root / "snapshot.json"
            write_snapshot(snapshot, [
                event("feature", "agentlab", 3000, "feat: guarded story generation", ["worker.py", "tests/test_worker.py"]),
                event("docs", "notes", 4000, "docs: update readme", ["README.md"]),
                event("deps", "demo", 5000, "chore: dependency bump", ["requirements.txt"]),
            ])
            rows = activity.shortlist(str(snapshot), str(root / "handled.jsonl"))

            self.assertEqual([row.project for row in rows], ["agentlab"])

    def test_handled_events_are_not_shortlisted(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            snapshot = root / "snapshot.json"
            handled = root / "handled.jsonl"
            source = event("done", "agentlab", 3000, "feat: guarded worker", ["worker.py"])
            write_snapshot(snapshot, [source])
            cluster = activity.cluster_events([source])[0]
            activity.record_handled(cluster, "delivered", str(handled))

            rows = activity.shortlist(str(snapshot), str(handled))

            self.assertEqual(rows, [])

    def test_stale_or_invalid_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            stale = root / "stale.json"
            invalid = root / "invalid.json"
            write_snapshot(stale, [event("a", "agentlab", 1000, "feat: worker", ["worker.py"])], generated_at=1)
            invalid.write_text('{"schema_version": 99}')

            self.assertEqual(activity.shortlist(str(stale), "missing"), [])
            self.assertEqual(activity.shortlist(str(invalid), "missing"), [])

    def test_technical_novelty_fails_closed_but_ai_default_stays_open(self):
        with tempfile.TemporaryDirectory() as raw:
            store = Path(raw) / "seen.jsonl"
            store.write_text(json.dumps({"text": "old", "vec": [1.0]}) + "\n")
            with mock.patch.object(novelty, "_embed", side_effect=RuntimeError("down")):
                self.assertEqual(novelty.filter_novel(["candidate"], store=str(store), fail_open=False), [])
                self.assertEqual(novelty.filter_novel(["candidate"], store=str(store)), ["candidate"])

    def test_missing_store_is_empty_history_but_broken_rows_fail_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            missing = root / "missing.jsonl"
            broken = root / "broken.jsonl"
            broken.write_text(json.dumps({"text": "unembedded"}) + "\n")

            self.assertEqual(novelty.filter_novel(["candidate"], store=str(missing), fail_open=False), ["candidate"])
            self.assertEqual(novelty.filter_novel(["candidate"], store=str(broken), fail_open=False), [])

    def test_novel_vector_is_reused_when_recording(self):
        with tempfile.TemporaryDirectory() as raw:
            store = Path(raw) / "seen.jsonl"
            store.write_text(json.dumps({"text": "old", "vec": [1.0, 0.0]}) + "\n")
            with mock.patch.object(novelty, "_embed", return_value=[[0.0, 1.0]]) as embed:
                checked = novelty.filter_novel_with_vectors(["new"], store=str(store), fail_open=False)

            self.assertEqual(checked, [("new", [0.0, 1.0])])
            embed.assert_called_once_with(["new"])
            with mock.patch.object(novelty, "_embed") as second_embed:
                novelty.record(["new"], store=str(store), vectors=[[0.0, 1.0]], fail_silently=False)

            second_embed.assert_not_called()
            self.assertEqual(json.loads(store.read_text().splitlines()[-1])["vec"], [0.0, 1.0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
