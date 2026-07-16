"""Recording folder scanning with two-pass stability detection.

Cloud-sync clients write files in multiple steps (temp file -> downloading ->
finalized), so a single scan cannot tell whether a file is fully synced. This
module compares the current scan against the previous persisted scan and only
considers a file "stable" (ready to process) when its size and modification
time are unchanged between the two consecutive scans.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from state_store import StateStore


@dataclass(eq=True)
class ScanEntry:
    size: int
    mtime: float


def _scan_folder(folder: Path) -> dict[str, ScanEntry]:
    entries: dict[str, ScanEntry] = {}
    for path in folder.iterdir():
        if path.is_file():
            stat = path.stat()
            entries[path.name] = ScanEntry(size=stat.st_size, mtime=stat.st_mtime)
    return entries


def _load_snapshot(snapshot_path: Path) -> dict[str, ScanEntry]:
    if not snapshot_path.exists():
        return {}
    raw = json.loads(snapshot_path.read_text(encoding="utf-8") or "{}")
    return {name: ScanEntry(**data) for name, data in raw.items()}


def _save_snapshot(snapshot_path: Path, entries: dict[str, ScanEntry]) -> None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    raw = {name: {"size": entry.size, "mtime": entry.mtime} for name, entry in entries.items()}
    snapshot_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


def scan_stable_files(watch_folder: str | Path, snapshot_path: str | Path) -> list[Path]:
    """Return files whose size and modification time are unchanged since the
    previous scan, meaning cloud sync has finished writing them. Files that
    are new or still changing are skipped and re-checked on the next scan."""
    folder = Path(watch_folder)
    snapshot_file = Path(snapshot_path)

    current = _scan_folder(folder)
    previous = _load_snapshot(snapshot_file)

    stable = [
        folder / name
        for name, entry in current.items()
        if name in previous and previous[name] == entry
    ]

    _save_snapshot(snapshot_file, current)
    return stable


def get_files_to_process(
    watch_folder: str | Path,
    snapshot_path: str | Path,
    state_store: StateStore,
    max_retry_count: int,
) -> list[Path]:
    """Combine newly-stable files with previously-failed files that are still
    under the retry limit into a single work list. Already-succeeded files and
    files that exceeded the retry limit (needs_manual_intervention) are
    excluded."""
    folder = Path(watch_folder)
    stable_files = scan_stable_files(watch_folder, snapshot_path)

    to_process: list[Path] = []
    for path in stable_files:
        file_id = state_store.make_file_id(path.name, path.stat().st_mtime)
        if not state_store.is_processed(file_id):
            to_process.append(path)

    for file_id in state_store.retryable_failed_ids(max_retry_count):
        filename = file_id.rsplit(":", 1)[0]
        candidate = folder / filename
        if candidate.exists() and candidate not in to_process:
            to_process.append(candidate)

    return to_process
