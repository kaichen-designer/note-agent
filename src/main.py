"""Single pipeline entry point: scan -> transcribe -> structure -> Notion.

Both the Windows Task Scheduler job and the manual run_now.bat invoke this
same script with no arguments (Dual Trigger Entry Points), so scheduled and
manual runs execute identical logic against the same state store. This script
never creates or modifies the Notion database schema -- that is the job of
the separate one-time setup_notion_database.py entry point.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))

from notion_agent import create_notion_page, structure_note
from state_store import StateStore
from transcribe import transcribe_file
from watcher import get_files_to_process

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STATE_PATH = DATA_DIR / "state.json"
SNAPSHOT_PATH = DATA_DIR / "scan_snapshot.json"
LOG_PATH = DATA_DIR / "pipeline.log"
LOCK_PATH = DATA_DIR / "pipeline.lock"
PROGRESS_PATH = DATA_DIR / "transcribe_progress.json"

AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".aac", ".ogg", ".flac", ".wma", ".mp4", ".mkv"}

PROCESSED_SUBFOLDER = "已處理"


def archive_processed_file(audio_path: Path, log: logging.Logger) -> None:
    """Move a successfully-processed recording into the 已處理 subfolder so
    the watch folder root only holds recordings that still need attention.
    Archiving is cosmetic cleanup: if the move fails (e.g. the cloud sync
    client still holds the file), we log a warning and leave the file --
    the state store already prevents reprocessing either way."""
    try:
        dest_dir = audio_path.parent / PROCESSED_SUBFOLDER
        dest_dir.mkdir(exist_ok=True)
        dest = dest_dir / audio_path.name
        counter = 1
        while dest.exists():
            dest = dest_dir / f"{audio_path.stem}_{counter}{audio_path.suffix}"
            counter += 1
        shutil.move(str(audio_path), str(dest))
        log.info("已歸檔: %s -> %s", audio_path.name, dest)
    except OSError as exc:
        log.warning("歸檔失敗(檔案保留原位,不影響筆記): %s", exc)

# A legitimate run can last over an hour (long recording + model load), but a
# lock left behind by a crash or power loss must not block the pipeline
# forever. Locks older than this are treated as stale and taken over.
LOCK_STALE_SECONDS = 4 * 60 * 60


def acquire_pipeline_lock() -> bool:
    """Prevent two pipeline runs (e.g. a manual run_now.bat and the scheduled
    task) from processing the same files concurrently, which would create
    duplicate Notion pages because state is only written after a file
    finishes. Returns False when another live run holds the lock."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        import time

        if time.time() - LOCK_PATH.stat().st_mtime > LOCK_STALE_SECONDS:
            LOCK_PATH.unlink(missing_ok=True)
            try:
                fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return False
        else:
            return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def release_pipeline_lock() -> None:
    LOCK_PATH.unlink(missing_ok=True)


def _setup_logging() -> logging.Logger:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    # Under pythonw.exe (windowless scheduled runs) there is no console:
    # sys.stdout is None and attaching a StreamHandler would raise on write.
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )
    return logging.getLogger("pipeline")


def _load_config() -> dict:
    load_dotenv(PROJECT_ROOT / ".env")
    missing = [
        name
        for name in ("WATCH_FOLDER_PATH", "ANTHROPIC_API_KEY", "NOTION_API_KEY", "NOTION_DATABASE_ID")
        if not os.environ.get(name)
    ]
    if missing:
        raise SystemExit(
            f"缺少必要設定:{', '.join(missing)}。請依 config/.env.example 建立 .env 並填入設定值。"
        )
    return {
        "watch_folder": os.environ["WATCH_FOLDER_PATH"],
        "anthropic_api_key": os.environ["ANTHROPIC_API_KEY"],
        "notion_api_key": os.environ["NOTION_API_KEY"],
        "notion_database_id": os.environ["NOTION_DATABASE_ID"],
        "transcribe_venv_python": os.environ.get(
            "TRANSCRIBE_VENV_PYTHON", str(PROJECT_ROOT / ".venv-transcribe" / "Scripts" / "python.exe")
        ),
        "whisper_model_size": os.environ.get("WHISPER_MODEL_SIZE", "large-v3"),
        "max_retry_count": int(os.environ.get("MAX_RETRY_COUNT", "3")),
        "vad_filter": os.environ.get("VAD_FILTER", "true").strip().lower() != "false",
    }


def process_file(audio_path: Path, store: StateStore, config: dict, log: logging.Logger) -> None:
    file_id = StateStore.make_file_id(audio_path.name, audio_path.stat().st_mtime)
    record = store.get(file_id)

    # Notion write failed previously: reuse the preserved transcript instead
    # of re-transcribing (Notion Write Failure Handling).
    transcript = record.transcript if record and record.transcript else None

    if transcript is None:
        log.info("轉錄中: %s", audio_path.name)
        result = transcribe_file(
            audio_path,
            config["transcribe_venv_python"],
            config["whisper_model_size"],
            progress_path=PROGRESS_PATH,
            vad_filter=config["vad_filter"],
        )
        if not result.success:
            store.mark_failed(file_id, f"轉錄失敗: {result.error}", config["max_retry_count"])
            log.error("轉錄失敗 (%s): %s", audio_path.name, result.error)
            return
        transcript = result.transcript
    else:
        log.info("使用先前保留的逐字稿,略過重新轉錄: %s", audio_path.name)

    recording_date = datetime.fromtimestamp(
        audio_path.stat().st_mtime, tz=timezone.utc
    ).strftime("%Y-%m-%d")

    try:
        note = structure_note(
            transcript, audio_path.name, recording_date, config["anthropic_api_key"]
        )
    except Exception as exc:
        store.mark_failed(
            file_id, f"結構化失敗: {exc}", config["max_retry_count"], transcript=transcript
        )
        log.error("結構化失敗 (%s): %s", audio_path.name, exc)
        return

    write_result = create_notion_page(
        note,
        transcript,
        audio_path.name,
        recording_date,
        config["notion_database_id"],
        config["notion_api_key"],
    )
    if not write_result.success:
        store.mark_failed(
            file_id,
            f"Notion 寫入失敗: {write_result.error}",
            config["max_retry_count"],
            transcript=transcript,
        )
        log.error("Notion 寫入失敗 (%s): %s", audio_path.name, write_result.error)
        return

    store.mark_success(file_id)
    log.info("完成: %s -> Notion page %s", audio_path.name, write_result.page_id)
    archive_processed_file(audio_path, log)


def main() -> int:
    log = _setup_logging()

    if not acquire_pipeline_lock():
        log.info("另一個執行實例正在處理中,本次略過(避免重複處理產生重複筆記)")
        return 0

    try:
        config = _load_config()
        store = StateStore(STATE_PATH)

        to_process = [
            path
            for path in get_files_to_process(
                config["watch_folder"], SNAPSHOT_PATH, store, config["max_retry_count"]
            )
            if path.suffix.lower() in AUDIO_EXTENSIONS
        ]

        if not to_process:
            log.info("本次掃描沒有需要處理的錄音檔")
            return 0

        log.info("本次掃描待處理 %d 個檔案", len(to_process))
        for audio_path in to_process:
            process_file(audio_path, store, config, log)

        return 0
    finally:
        release_pipeline_lock()


if __name__ == "__main__":
    sys.exit(main())
