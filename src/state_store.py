"""Local state tracking for processed recordings.

Tracks each recording file by identity (filename + modification time) so the
pipeline can avoid reprocessing successfully-handled files and can retry
failed ones up to a configured limit.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

PENDING = "pending"
SUCCESS = "success"
FAILED = "failed"
NEEDS_MANUAL_INTERVENTION = "needs_manual_intervention"


@dataclass
class FileState:
    file_id: str
    status: str = PENDING
    last_attempt_at: float | None = None
    retry_count: int = 0
    failure_reason: str | None = None
    transcript: str | None = None


class StateStore:
    """Reads and writes recording processing state to a local JSON file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, FileState] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        for file_id, data in raw.items():
            self._records[file_id] = FileState(**data)

    def _save(self) -> None:
        raw = {file_id: asdict(state) for file_id, state in self._records.items()}
        self.path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def make_file_id(filename: str, modified_time: float) -> str:
        return f"{filename}:{int(modified_time)}"

    def get(self, file_id: str) -> FileState | None:
        return self._records.get(file_id)

    def is_processed(self, file_id: str) -> bool:
        record = self._records.get(file_id)
        return record is not None and record.status == SUCCESS

    def mark_pending(self, file_id: str) -> FileState:
        record = self._records.get(file_id) or FileState(file_id=file_id)
        record.status = PENDING
        self._records[file_id] = record
        self._save()
        return record

    def mark_success(self, file_id: str) -> FileState:
        record = self._records.get(file_id) or FileState(file_id=file_id)
        record.status = SUCCESS
        record.last_attempt_at = time.time()
        record.failure_reason = None
        self._records[file_id] = record
        self._save()
        return record

    def mark_failed(
        self,
        file_id: str,
        reason: str,
        max_retry_count: int,
        transcript: str | None = None,
    ) -> FileState:
        record = self._records.get(file_id) or FileState(file_id=file_id)
        record.retry_count += 1
        record.last_attempt_at = time.time()
        record.failure_reason = reason
        if transcript is not None:
            record.transcript = transcript
        if record.retry_count >= max_retry_count:
            record.status = NEEDS_MANUAL_INTERVENTION
        else:
            record.status = FAILED
        self._records[file_id] = record
        self._save()
        return record

    def all_records(self) -> list[FileState]:
        return list(self._records.values())

    def retryable_failed_ids(self, max_retry_count: int) -> list[str]:
        return [
            file_id
            for file_id, record in self._records.items()
            if record.status == FAILED and record.retry_count < max_retry_count
        ]
