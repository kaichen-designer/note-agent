import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import main as main_module
from notion_agent import NotionWriteResult, StructuredNote
from state_store import FAILED, StateStore
from transcribe import TranscriptionResult

FAKE_NOTE = StructuredNote(
    title="週會記錄",
    summary="摘要",
    key_points=["重點"],
    action_items=["待辦"],
    category_tag="會議",
)

CONFIG = {
    "transcribe_venv_python": "unused",
    "whisper_model_size": "tiny",
    "anthropic_api_key": "unused",
    "notion_api_key": "unused",
    "notion_database_id": "unused",
    "max_retry_count": 3,
    "vad_filter": True,
}


class NotionWriteFailurePreservesTranscriptTests(unittest.TestCase):
    """Notion Write Failure Handling: when the Notion write fails after a
    successful transcription, the transcript is preserved in state and the
    next attempt reuses it instead of re-transcribing."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmpdir.name)
        self.audio = self.folder / "meeting.m4a"
        self.audio.write_bytes(b"fake audio")
        self.store = StateStore(self.folder / "state.json")
        # A silent logger: tests must not write into the real data/pipeline.log.
        import logging

        self.log = logging.getLogger("test_pipeline_silent")
        self.log.handlers = [logging.NullHandler()]
        self.log.propagate = False

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_write_failure_preserves_transcript_and_retry_skips_transcription(self):
        with (
            patch.object(
                main_module,
                "transcribe_file",
                return_value=TranscriptionResult(success=True, transcript="逐字稿內容"),
            ) as mock_transcribe,
            patch.object(main_module, "structure_note", return_value=FAKE_NOTE),
            patch.object(
                main_module,
                "create_notion_page",
                return_value=NotionWriteResult(success=False, error="invalid database id"),
            ),
        ):
            main_module.process_file(self.audio, self.store, CONFIG, self.log)

        file_id = StateStore.make_file_id(self.audio.name, self.audio.stat().st_mtime)
        record = self.store.get(file_id)
        self.assertEqual(record.status, FAILED)
        self.assertEqual(record.transcript, "逐字稿內容")
        self.assertEqual(mock_transcribe.call_count, 1)

        # Retry: Notion write now succeeds; transcription must NOT run again.
        with (
            patch.object(main_module, "transcribe_file") as mock_transcribe_retry,
            patch.object(main_module, "structure_note", return_value=FAKE_NOTE),
            patch.object(
                main_module,
                "create_notion_page",
                return_value=NotionWriteResult(success=True, page_id="page-123"),
            ),
        ):
            main_module.process_file(self.audio, self.store, CONFIG, self.log)

        mock_transcribe_retry.assert_not_called()
        self.assertTrue(self.store.is_processed(file_id))



class SupportedRecordingExtensionTests(unittest.TestCase):
    """Video Container Recording Support: a stable .mkv file reaches the same
    scan-transcribe-structure-write pipeline as audio files, while other
    video containers (e.g. .mov) remain excluded, matching the extension
    filter main() applies to watcher.get_files_to_process() output."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmpdir.name)
        self.snapshot_path = self.folder / "_snapshot.json"
        self.store = StateStore(self.folder / "_state.json")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _stable_supported_files(self):
        from watcher import get_files_to_process

        # Two passes: pass 1 establishes the baseline snapshot, pass 2 sees
        # unchanged size/mtime and reports the files as stable.
        get_files_to_process(self.folder, self.snapshot_path, self.store, max_retry_count=3)
        candidates = get_files_to_process(
            self.folder, self.snapshot_path, self.store, max_retry_count=3
        )
        return [p for p in candidates if p.suffix.lower() in main_module.AUDIO_EXTENSIONS]

    def test_stable_mkv_file_is_selected_for_processing(self):
        mkv = self.folder / "meeting.mkv"
        mkv.write_bytes(b"fake mkv container bytes")
        self.assertIn(mkv, self._stable_supported_files())

    def test_unsupported_video_container_is_excluded(self):
        mov = self.folder / "meeting.mov"
        mov.write_bytes(b"fake mov container bytes")
        self.assertNotIn(mov, self._stable_supported_files())


class PipelineLockTests(unittest.TestCase):
    """Single-instance lock: a second concurrent run must be refused while
    the first holds the lock, and the lock must be reusable after release."""

    def setUp(self):
        # Point the lock at a temp location so tests never touch real data/.
        self.tmpdir = tempfile.TemporaryDirectory()
        self._original = main_module.LOCK_PATH
        main_module.LOCK_PATH = Path(self.tmpdir.name) / "pipeline.lock"

    def tearDown(self):
        main_module.LOCK_PATH = self._original
        self.tmpdir.cleanup()

    def test_second_acquire_fails_until_released(self):
        self.assertTrue(main_module.acquire_pipeline_lock())
        self.assertFalse(main_module.acquire_pipeline_lock())
        main_module.release_pipeline_lock()
        self.assertTrue(main_module.acquire_pipeline_lock())
        main_module.release_pipeline_lock()

    def test_stale_lock_is_taken_over(self):
        self.assertTrue(main_module.acquire_pipeline_lock())
        import os as _os
        import time as _time
        stale_time = _time.time() - main_module.LOCK_STALE_SECONDS - 60
        _os.utime(main_module.LOCK_PATH, (stale_time, stale_time))
        self.assertTrue(main_module.acquire_pipeline_lock())
        main_module.release_pipeline_lock()

class ArchiveProcessedFileTests(unittest.TestCase):
    """Processed File Archiving: success moves the file into 已處理;
    failure leaves it in place; name collisions get numeric suffixes."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmpdir.name)
        self.audio = self.folder / "meeting.m4a"
        self.audio.write_bytes(b"fake audio")
        self.store = StateStore(self.folder / "state.json")
        import logging

        self.log = logging.getLogger("test_pipeline_silent")
        self.log.handlers = [logging.NullHandler()]
        self.log.propagate = False

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run_success(self):
        with (
            patch.object(
                main_module,
                "transcribe_file",
                return_value=TranscriptionResult(success=True, transcript="逐字稿"),
            ),
            patch.object(main_module, "structure_note", return_value=FAKE_NOTE),
            patch.object(
                main_module,
                "create_notion_page",
                return_value=NotionWriteResult(success=True, page_id="page-1"),
            ),
        ):
            main_module.process_file(self.audio, self.store, CONFIG, self.log)

    def test_success_moves_file_into_processed_subfolder(self):
        self._run_success()
        self.assertFalse(self.audio.exists())
        self.assertTrue((self.folder / "已處理" / "meeting.m4a").exists())

    def test_name_collision_gets_numeric_suffix(self):
        processed = self.folder / "已處理"
        processed.mkdir()
        (processed / "meeting.m4a").write_bytes(b"older archive")
        self._run_success()
        self.assertTrue((processed / "meeting_1.m4a").exists())
        self.assertEqual((processed / "meeting.m4a").read_bytes(), b"older archive")

    def test_success_moves_mkv_file_into_processed_subfolder(self):
        """Video Container Recording Support: a successfully processed .mkv
        recording is archived by the same generic, extension-agnostic rule
        as audio files."""
        mkv = self.folder / "recording.mkv"
        mkv.write_bytes(b"fake mkv container bytes")
        with (
            patch.object(
                main_module,
                "transcribe_file",
                return_value=TranscriptionResult(success=True, transcript="逐字稿"),
            ),
            patch.object(main_module, "structure_note", return_value=FAKE_NOTE),
            patch.object(
                main_module,
                "create_notion_page",
                return_value=NotionWriteResult(success=True, page_id="page-1"),
            ),
        ):
            main_module.process_file(mkv, self.store, CONFIG, self.log)
        self.assertFalse(mkv.exists())
        self.assertTrue((self.folder / "已處理" / "recording.mkv").exists())

    def test_failure_leaves_file_in_place(self):
        with (
            patch.object(
                main_module,
                "transcribe_file",
                return_value=TranscriptionResult(success=False, error="corrupt"),
            ),
        ):
            main_module.process_file(self.audio, self.store, CONFIG, self.log)
        self.assertTrue(self.audio.exists())
        self.assertFalse((self.folder / "已處理").exists())


if __name__ == "__main__":
    unittest.main()
