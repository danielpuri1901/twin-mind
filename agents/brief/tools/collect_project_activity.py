#!/usr/bin/env python3
"""Collect recent Git activity on the Mac without copying source contents."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 1
DEFAULT_OUTPUT = Path("~/twin-corpus/notes/project-activity.json").expanduser()
DEFAULT_REMOTE_HOST = "twin-mind"
DEFAULT_REMOTE_PATH = "/home/ec2-user/twin-corpus/notes/project-activity.json"
MAX_COMMITS_PER_REPO = 20
PROTECTED_PROJECT_ROOTS = ("Desktop", "Documents", "Downloads")

EXCLUDED_DIRS = {
    "Library", ".Trash", ".cache", ".local", ".nvm", ".gemini",
    ".codex", ".claude", ".agents", ".hermes", "node_modules",
    ".venv", "venv", "env", "dist", "build", "out", "outputs",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "vendor", "target", "coverage", ".next", ".turbo", ".terraform",
    ".output", ".ssh", ".aws", ".gnupg", "Pods", "DerivedData",
    ".worktrees", "worktrees",
}
EXCLUDED_DIRS_LOWER = {directory.lower() for directory in EXCLUDED_DIRS}
EXCLUDED_NAMES = {
    ".env", ".env.local", ".env.production", "credentials",
    "credentials.json", "secrets.json", ".npmrc", ".pypirc",
    "id_rsa", "id_ed25519", ".netrc", "kubeconfig",
}
SENSITIVE_NAME_WORDS = {"secret", "secrets", "credential", "credentials", "token", "tokens"}
SENSITIVE_NAME_FRAGMENTS = {"api_key", "private_key", "service_account"}
EXCLUDED_SUFFIXES = {
    ".lock", ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mov",
    ".zip", ".tar", ".gz", ".pdf", ".db", ".sqlite", ".sqlite3",
    ".pem", ".key", ".p12", ".pyc",
}
ALLOWED_SUFFIXES = {
    ".c", ".cc", ".cfg", ".conf", ".cpp", ".cs", ".css", ".dart",
    ".ex", ".exs", ".fs", ".fsx", ".go", ".gradle", ".graphql", ".h",
    ".hpp", ".hrl", ".html", ".ini", ".ipynb", ".java", ".js", ".json",
    ".jsx", ".kt", ".lua", ".md", ".php", ".plist", ".properties",
    ".proto", ".py", ".r", ".rb", ".rs", ".rst", ".scala", ".scss",
    ".sh", ".sql", ".svelte", ".swift", ".tf", ".toml", ".ts", ".tsx",
    ".txt", ".vue", ".xml", ".yaml", ".yml",
}
ALLOWED_NAMES = {
    ".dockerignore", ".editorconfig", ".gitignore", "cmakelists.txt",
    "dockerfile", "gemfile", "justfile", "makefile", "procfile", "rakefile",
}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.stdout


def discover_repositories(home: Path) -> list[Path]:
    """Find user projects while pruning caches, histories, vendors, and generated trees."""
    home = home.resolve()
    repositories: list[Path] = []
    for root, dirs, files in os.walk(home):
        dirs[:] = sorted(
            directory for directory in dirs
            if directory in {".git", ".worktrees", "worktrees"}
            or (directory not in EXCLUDED_DIRS and not directory.startswith("."))
        )
        if ".git" in dirs or ".git" in files:
            repositories.append(Path(root))
            if ".git" in dirs:
                dirs.remove(".git")
    return sorted(repositories)


def require_scan_access(home: Path) -> None:
    """Refuse a partial snapshot when launchd lacks macOS folder access."""
    for name in PROTECTED_PROJECT_ROOTS:
        folder = home / name
        if not folder.exists():
            continue
        try:
            with os.scandir(folder) as entries:
                next(entries, None)
        except PermissionError as error:
            raise PermissionError(
                f"Cannot scan {folder}. Grant Full Disk Access to /usr/bin/python3."
            ) from error


def _allowed_path(raw_path: str) -> bool:
    path = raw_path.strip().strip('"')
    if not path:
        return False
    parts = Path(path).parts
    if any(part.lower() in EXCLUDED_DIRS_LOWER for part in parts):
        return False
    name = Path(path).name.lower()
    if name in EXCLUDED_NAMES or name.startswith(".env."):
        return False
    normalized_name = name.replace("-", "_").replace(".", "_")
    name_words = set(normalized_name.split("_"))
    if name_words & SENSITIVE_NAME_WORDS:
        return False
    if any(fragment in normalized_name for fragment in SENSITIVE_NAME_FRAGMENTS):
        return False
    suffix = Path(name).suffix.lower()
    if suffix in EXCLUDED_SUFFIXES:
        return False
    return name in ALLOWED_NAMES or suffix in ALLOWED_SUFFIXES


@lru_cache(maxsize=None)
def _repo_identity(repo: Path, home: Path) -> tuple[str, str]:
    relative = repo.resolve().relative_to(home.resolve()).as_posix()
    repo_id = hashlib.sha256(relative.encode()).hexdigest()[:16]
    common_raw = _git(repo, "rev-parse", "--git-common-dir").strip()
    common = Path(common_raw)
    if not common.is_absolute():
        common = repo / common
    common = common.resolve()
    project = common.parent.name if common.name == ".git" else repo.name
    return project, repo_id


def _commit_events(repo: Path, home: Path, cutoff: datetime) -> list[dict]:
    project, repo_id = _repo_identity(repo, home)
    raw = _git(
        repo,
        "log",
        f"--since={int(cutoff.timestamp())}",
        "--no-merges",
        f"-{MAX_COMMITS_PER_REPO}",
        "--format=@@%H%x09%ct%x09%s",
        "--name-only",
    )
    events: list[dict] = []
    current: Optional[dict] = None
    for line in raw.splitlines():
        if line.startswith("@@"):
            if current and current["paths"]:
                events.append(current)
            commit_id, timestamp, subject = line[2:].split("\t", 2)
            current = {
                "event_id": commit_id,
                "kind": "commit",
                "project": project,
                "repo_id": repo_id,
                "time": int(timestamp),
                "subject": subject[:180],
                "paths": [],
            }
        elif current is not None and _allowed_path(line):
            current["paths"].append(line[:240])
    if current and current["paths"]:
        events.append(current)
    return events


def _status_entries(repo: Path) -> list[tuple[str, str]]:
    raw = _git(repo, "status", "--porcelain=v1", "--untracked-files=all", "-z")
    records = raw.split("\0")
    entries: list[tuple[str, str]] = []
    skip_rename_source = False
    for record in records:
        if not record:
            continue
        if skip_rename_source:
            skip_rename_source = False
            continue
        if len(record) < 4:
            continue
        status, path = record[:2], record[3:]
        entries.append((status, path))
        if "R" in status or "C" in status:
            skip_rename_source = True
    return entries


def _path_mtime(repo: Path, status: str, path: str, now: datetime) -> float:
    if "D" in status:
        return now.timestamp()
    try:
        return (repo / path).stat().st_mtime
    except OSError:
        return 0.0


def _dirty_event(repo: Path, home: Path, cutoff: datetime, now: datetime) -> Optional[dict]:
    project, repo_id = _repo_identity(repo, home)
    entries = []
    paths = []
    mtimes = []
    for status, path in _status_entries(repo):
        if not _allowed_path(path):
            continue
        modified = _path_mtime(repo, status, path, now)
        if modified < cutoff.timestamp():
            continue
        entries.append(f"{status} {path}")
        paths.append(path)
        mtimes.append(modified)
    if not entries:
        return None
    normalized = f"{repo_id}\n" + "\n".join(sorted(entries))
    return {
        "event_id": "dirty:" + hashlib.sha256(normalized.encode()).hexdigest(),
        "kind": "dirty",
        "project": project,
        "repo_id": repo_id,
        "time": int(max(mtimes)),
        "subject": "Current working-tree changes",
        "paths": sorted(paths)[:80],
    }


def collect_snapshot(home: Path, now: datetime, lookback_days: int = 14) -> dict:
    """Return a bounded, source-free activity snapshot for all discovered projects."""
    require_scan_access(home)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=lookback_days)
    events = []
    for repo in discover_repositories(home):
        try:
            events.extend(_commit_events(repo, home, cutoff))
            dirty = _dirty_event(repo, home, cutoff, now)
            if dirty:
                events.append(dirty)
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
    unique_events = {}
    for event in events:
        unique_events.setdefault(event["event_id"], event)
    events = list(unique_events.values())
    events.sort(key=lambda event: (-event["time"], event["project"].lower(), event["event_id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": int(now.timestamp()),
        "lookback_days": lookback_days,
        "events": events[:200],
    }


def write_snapshot(snapshot: dict, destination: Path) -> None:
    """Write a complete snapshot, then atomically replace the prior file."""
    destination = destination.expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=destination.name + ".",
        suffix=".tmp",
        dir=destination.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def publish_snapshot(source: Path, remote_host: str, remote_path: str) -> None:
    """Publish only the derived snapshot through the existing SSH-over-SSM host."""
    subprocess.run(
        [
            "rsync",
            "--delay-updates",
            "--chmod=u=rw,go=",
            str(source),
            f"{remote_host}:{remote_path}",
        ],
        check=True,
        timeout=60,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--lookback-days", type=int, default=14)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--remote-host", default=DEFAULT_REMOTE_HOST)
    parser.add_argument("--remote-path", default=DEFAULT_REMOTE_PATH)
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    snapshot = collect_snapshot(args.home, now, args.lookback_days)
    write_snapshot(snapshot, args.output)
    if args.publish:
        publish_snapshot(args.output.expanduser(), args.remote_host, args.remote_path)
    print(
        f"project activity: {len(snapshot['events'])} events from "
        f"{len({event['repo_id'] for event in snapshot['events']})} active repositories"
    )


if __name__ == "__main__":
    main()
