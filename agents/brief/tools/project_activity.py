#!/usr/bin/env python3
"""Validate, cluster, rank, and deduplicate Mac project activity."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT = "~/twin-corpus/notes/project-activity.json"
HANDLED_STORE = "~/.hermes/state/seen-technical-events.jsonl"
NOVELTY_STORE = "~/.hermes/state/seen-technical.jsonl"
SCHEMA_VERSION = 1

CODE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
    ".kt", ".swift", ".c", ".cc", ".cpp", ".h", ".hpp", ".rb",
    ".php", ".scala", ".sh", ".sql", ".tf", ".yaml", ".yml",
    ".toml", ".json", ".xml", ".html", ".css", ".scss",
}
DOC_SUFFIXES = {".md", ".rst", ".txt"}
DEPENDENCY_FILES = {
    "requirements.txt", "package.json", "package-lock.json", "pnpm-lock.yaml",
    "yarn.lock", "poetry.lock", "uv.lock", "cargo.lock", "go.sum",
}
POSITIVE_WORDS = {
    "feat", "feature", "fix", "security", "harden", "guard", "retry",
    "migrate", "migration", "refactor", "perf", "architecture", "pipeline",
    "validate", "validation", "idempotent", "rollback",
}
NOISE_WORDS = {"format", "formatting", "typo", "spelling", "dependabot"}


@dataclass(frozen=True)
class ActivityCluster:
    cluster_id: str
    project: str
    repo_id: str
    event_ids: tuple[str, ...]
    latest_time: int
    subjects: tuple[str, ...]
    paths: tuple[str, ...]
    score: int
    candidate_text: str


def _valid_event(event: object) -> bool:
    if not isinstance(event, dict):
        return False
    required = {
        "event_id": str,
        "kind": str,
        "project": str,
        "repo_id": str,
        "time": int,
        "subject": str,
        "paths": list,
    }
    if any(not isinstance(event.get(key), expected) for key, expected in required.items()):
        return False
    return bool(event["event_id"] and event["project"] and event["repo_id"])


def load_snapshot(path: str, now: datetime | None = None, max_age_days: int = 30) -> list[dict]:
    """Load only a current, versioned, structurally valid activity snapshot."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    data = json.loads(Path(os.path.expanduser(path)).read_text())
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported project activity schema")
    generated_at = data.get("generated_at")
    events = data.get("events")
    if not isinstance(generated_at, int) or not isinstance(events, list):
        raise ValueError("invalid project activity snapshot")
    if now.timestamp() - generated_at > max_age_days * 86400:
        raise ValueError("stale project activity snapshot")
    if generated_at - now.timestamp() > 3600:
        raise ValueError("project activity snapshot is from the future")
    if any(not _valid_event(event) for event in events):
        raise ValueError("invalid project activity event")
    return events


def _path_keys(paths: set[str]) -> set[str]:
    keys = set()
    for raw in paths:
        path = Path(raw)
        keys.add(path.as_posix())
        if len(path.parts) > 1:
            keys.add(path.parts[0])
    return keys


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    name = Path(lowered).name
    return "/test" in f"/{lowered}" or name.startswith("test_") or name.endswith("_test.py")


def _is_noise(subjects: tuple[str, ...], paths: tuple[str, ...]) -> bool:
    words = _words(" ".join(subjects))
    names = {Path(path).name.lower() for path in paths}
    suffixes = {Path(path).suffix.lower() for path in paths}
    docs_only = bool(paths) and suffixes <= DOC_SUFFIXES and not any(_is_test_path(path) for path in paths)
    dependency_only = bool(names) and names <= DEPENDENCY_FILES and bool(words & {"bump", "dependency", "dependencies", "upgrade"})
    cosmetic = bool(words & NOISE_WORDS) and not bool(words & POSITIVE_WORDS)
    return not paths or docs_only or dependency_only or cosmetic


def _score(subjects: tuple[str, ...], paths: tuple[str, ...]) -> int:
    words = _words(" ".join(subjects))
    code_paths = [path for path in paths if Path(path).suffix.lower() in CODE_SUFFIXES and not _is_test_path(path)]
    test_paths = [path for path in paths if _is_test_path(path)]
    infra_paths = [path for path in paths if path.startswith(("infra/", ".github/")) or Path(path).suffix.lower() == ".tf"]
    score = min(len(code_paths), 5) * 2
    score += 3 if test_paths else 0
    score += 2 if infra_paths else 0
    score += min(len(words & POSITIVE_WORDS), 3) * 2
    return score


def _make_cluster(events: list[dict]) -> ActivityCluster:
    ordered = sorted(events, key=lambda event: (event["time"], event["event_id"]))
    event_ids = tuple(event["event_id"] for event in ordered)
    subjects = tuple(dict.fromkeys(event["subject"] for event in ordered))
    paths = tuple(sorted({path for event in ordered for path in event["paths"]}))
    digest = hashlib.sha256("\n".join(sorted(event_ids)).encode()).hexdigest()
    score = _score(subjects, paths)
    candidate_text = (
        f"Project: {ordered[0]['project']}\n"
        f"Changes: {' | '.join(subjects)}\n"
        f"Files: {', '.join(paths[:30])}"
    )
    return ActivityCluster(
        cluster_id=digest,
        project=ordered[0]["project"],
        repo_id=ordered[0]["repo_id"],
        event_ids=event_ids,
        latest_time=max(event["time"] for event in ordered),
        subjects=subjects,
        paths=paths,
        score=score,
        candidate_text=candidate_text,
    )


def cluster_events(events: list[dict], window_hours: int = 6) -> list[ActivityCluster]:
    """Group related changes into transitive, repository-local work sessions."""
    builders: list[dict] = []
    window_seconds = window_hours * 3600
    for event in sorted(events, key=lambda row: (row["repo_id"], row["time"], row["event_id"])):
        event_paths = set(event["paths"])
        event_keys = _path_keys(event_paths)
        target = None
        for builder in reversed(builders):
            if builder["repo_id"] != event["repo_id"]:
                continue
            if event["time"] - builder["latest_time"] > window_seconds:
                break
            if event_keys & builder["path_keys"]:
                target = builder
                break
        if target is None:
            builders.append({
                "repo_id": event["repo_id"],
                "latest_time": event["time"],
                "path_keys": event_keys,
                "events": [event],
            })
        else:
            target["events"].append(event)
            target["latest_time"] = max(target["latest_time"], event["time"])
            target["path_keys"].update(event_keys)
    return [_make_cluster(builder["events"]) for builder in builders]


def _handled_event_ids(path: str) -> set[str]:
    expanded = Path(os.path.expanduser(path))
    try:
        lines = expanded.read_text().splitlines()
    except FileNotFoundError:
        return set()
    handled = set()
    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        ids = row.get("event_ids")
        if not isinstance(ids, list) or not all(isinstance(event_id, str) for event_id in ids):
            raise ValueError("invalid handled technical event row")
        handled.update(ids)
    return handled


def shortlist(
    path: str = SNAPSHOT,
    handled_path: str = HANDLED_STORE,
    limit: int = 5,
) -> list[ActivityCluster]:
    """Return meaningful unhandled work sessions for model judgment."""
    try:
        events = load_snapshot(path)
        handled = _handled_event_ids(handled_path)
        clusters = [
            cluster for cluster in cluster_events(events)
            if not all(event_id in handled for event_id in cluster.event_ids)
            and not _is_noise(cluster.subjects, cluster.paths)
        ]
        clusters.sort(key=lambda cluster: (-cluster.score, -cluster.latest_time, cluster.project.lower(), cluster.cluster_id))
        return clusters[:limit]
    except Exception:
        return []


def record_handled(cluster: ActivityCluster, status: str, path: str = HANDLED_STORE) -> None:
    """Record all events in a selected or rejected cluster after brief delivery."""
    destination = Path(os.path.expanduser(path))
    destination.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "cluster_id": cluster.cluster_id,
        "status": status,
        "event_ids": list(cluster.event_ids),
    }
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
