import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import main as main_module
from interview_agent import InterviewNote
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

FAKE_INTERVIEW_NOTE = InterviewNote(
    summary="訪談摘要", pain_points=[], highlights=[], usage_habits=[]
)

CONFIG = {
    "transcribe_venv_python": "unused",
    "whisper_model_size": "tiny",
    "anthropic_api_key": "unused",
    "notion_api_key": "unused",
    "notion_database_id": "unused",
    "max_retry_count": 3,
    "vad_filter": True,
    "speaker_diarization_enabled": False,
    "hf_token": "",
    "interview_expected_speakers": None,
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


class MeetingDiarizationDisabledTests(unittest.TestCase):
    """Meeting recordings never need speaker diarization (unlike interviews);
    the meeting pipeline must not request it even when
    SPEAKER_DIARIZATION_ENABLED=true for the interview pipeline."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmpdir.name)
        self.audio = self.folder / "meeting.m4a"
        self.audio.write_bytes(b"fake audio")
        self.store = StateStore(self.folder / "state.json")
        self.log = logging.getLogger("test_pipeline_silent_meeting_diarization")
        self.log.handlers = [logging.NullHandler()]
        self.log.propagate = False

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_process_file_never_requests_diarization_even_when_enabled_in_config(self):
        config = {**CONFIG, "speaker_diarization_enabled": True, "hf_token": "hf_test_token"}
        with (
            patch.object(
                main_module,
                "transcribe_file",
                return_value=TranscriptionResult(success=True, transcript="逐字稿內容"),
            ) as mock_transcribe,
            patch.object(main_module, "structure_note", return_value=FAKE_NOTE),
            patch.object(
                main_module, "create_notion_page", return_value=NotionWriteResult(success=True, page_id="p1")
            ),
        ):
            main_module.process_file(self.audio, self.store, config, self.log)

        self.assertFalse(mock_transcribe.call_args.kwargs.get("diarization_enabled", False))


class DiarizationConfigTests(unittest.TestCase):
    """Local Speaker Diarization: enabling diarization without a Hugging
    Face token is a configuration error, raised at startup before any
    recording is processed; leaving diarization off (the default) does not
    require the token at all."""

    BASE_ENV = {
        "WATCH_FOLDER_PATH": "C:/watch",
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "NOTION_API_KEY": "ntn-test",
        "NOTION_DATABASE_ID": "db-test",
    }

    def test_enabled_without_token_raises_configuration_error(self):
        env = {**self.BASE_ENV, "SPEAKER_DIARIZATION_ENABLED": "true"}
        with patch.object(main_module, "load_dotenv"), patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SystemExit):
                main_module._load_config()

    def test_enabled_with_token_loads_successfully(self):
        env = {
            **self.BASE_ENV,
            "SPEAKER_DIARIZATION_ENABLED": "true",
            "HUGGINGFACE_TOKEN": "hf_test_token",
        }
        with patch.object(main_module, "load_dotenv"), patch.dict(os.environ, env, clear=True):
            config = main_module._load_config()
        self.assertTrue(config["speaker_diarization_enabled"])
        self.assertEqual(config["hf_token"], "hf_test_token")

    def test_disabled_by_default_does_not_require_token(self):
        with patch.object(main_module, "load_dotenv"), patch.dict(os.environ, self.BASE_ENV, clear=True):
            config = main_module._load_config()
        self.assertFalse(config["speaker_diarization_enabled"])


class InterviewWatchFolderConfigTests(unittest.TestCase):
    """Independently Configured Interview Watch Folder: the interview watch
    folder is optional and independent from the meeting watch folder; the two
    paths must never be configured identically."""

    BASE_ENV = {
        "WATCH_FOLDER_PATH": "C:/watch",
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "NOTION_API_KEY": "ntn-test",
        "NOTION_DATABASE_ID": "db-test",
    }

    def test_not_configured_leaves_interview_watch_folder_none(self):
        with patch.object(main_module, "load_dotenv"), patch.dict(os.environ, self.BASE_ENV, clear=True):
            config = main_module._load_config()
        self.assertIsNone(config["interview_watch_folder"])

    def test_configured_to_same_path_as_meeting_folder_raises_configuration_error(self):
        env = {**self.BASE_ENV, "INTERVIEW_WATCH_FOLDER_PATH": "C:/watch"}
        with patch.object(main_module, "load_dotenv"), patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SystemExit):
                main_module._load_config()

    def test_configured_to_different_path_is_loaded(self):
        env = {**self.BASE_ENV, "INTERVIEW_WATCH_FOLDER_PATH": "C:/interviews"}
        with patch.object(main_module, "load_dotenv"), patch.dict(os.environ, env, clear=True):
            config = main_module._load_config()
        self.assertEqual(config["interview_watch_folder"], "C:/interviews")

    def test_expected_speakers_not_configured_defaults_to_none(self):
        with patch.object(main_module, "load_dotenv"), patch.dict(os.environ, self.BASE_ENV, clear=True):
            config = main_module._load_config()
        self.assertIsNone(config["interview_expected_speakers"])

    def test_expected_speakers_configured_is_parsed_as_int(self):
        env = {**self.BASE_ENV, "INTERVIEW_EXPECTED_SPEAKERS": "2"}
        with patch.object(main_module, "load_dotenv"), patch.dict(os.environ, env, clear=True):
            config = main_module._load_config()
        self.assertEqual(config["interview_expected_speakers"], 2)


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


class InterviewFolderSupportedExtensionTests(unittest.TestCase):
    """Interview folder file selection reuses the exact same
    AUDIO_EXTENSIONS whitelist as the meeting folder -- there is no
    interview-specific extension list; the folder path alone decides
    meeting vs. interview."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _stable_supported_files(self):
        snapshot_path = self.folder / "_snapshot.json"
        store = StateStore(self.folder / "_state.json")
        from watcher import get_files_to_process

        get_files_to_process(self.folder, snapshot_path, store, max_retry_count=3)
        candidates = get_files_to_process(self.folder, snapshot_path, store, max_retry_count=3)
        return main_module.filter_supported_extensions(candidates)

    def test_interview_folder_mp4_is_included(self):
        mp4 = self.folder / "interview.mp4"
        mp4.write_bytes(b"fake interview mp4 bytes")
        self.assertIn(mp4, self._stable_supported_files())

    def test_interview_folder_unsupported_extension_is_excluded(self):
        txt = self.folder / "notes.txt"
        txt.write_bytes(b"not a recording")
        self.assertNotIn(txt, self._stable_supported_files())


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


class ProcessInterviewFileTests(unittest.TestCase):
    """Interview files route through structure_interview/create_interview_page,
    never through the meeting pipeline's structure_note/create_notion_page --
    and Notion Write Failure Handling applies the same way: the timestamped
    transcript is preserved so a retry does not require re-transcription."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmpdir.name)
        self.video = self.folder / "interview.mp4"
        self.video.write_bytes(b"fake mp4 bytes")
        self.store = StateStore(self.folder / "state.json")
        self.log = logging.getLogger("test_pipeline_silent")
        self.log.handlers = [logging.NullHandler()]
        self.log.propagate = False

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_success_calls_interview_specific_functions(self):
        file_id = StateStore.make_file_id(self.video.name, self.video.stat().st_mtime)
        with (
            patch.object(
                main_module,
                "transcribe_file",
                return_value=TranscriptionResult(
                    success=True,
                    transcript="哈囉大家好我們開始訪談",
                    segments=[{"start": 0.0, "end": 2.0, "text": "哈囉大家好我們開始訪談"}],
                ),
            ) as mock_transcribe,
            patch.object(
                main_module, "structure_interview", return_value=FAKE_INTERVIEW_NOTE
            ) as mock_structure_interview,
            patch.object(main_module, "structure_note") as mock_structure_note,
            patch.object(
                main_module,
                "create_interview_page",
                return_value=NotionWriteResult(success=True, page_id="page-interview-1"),
            ) as mock_create_interview_page,
            patch.object(main_module, "create_notion_page") as mock_create_notion_page,
        ):
            main_module.process_interview_file(self.video, self.store, CONFIG, self.log)

        mock_transcribe.assert_called_once()
        self.assertTrue(mock_transcribe.call_args.kwargs["preserve_segments"])
        self.assertIsNone(mock_transcribe.call_args.kwargs.get("num_speakers"))
        mock_structure_interview.assert_called_once()
        mock_create_interview_page.assert_called_once()
        mock_structure_note.assert_not_called()
        mock_create_notion_page.assert_not_called()

        self.assertTrue(self.store.is_processed(file_id))

    def test_expected_speakers_config_is_forwarded_to_transcribe(self):
        """Expected Speaker Count Hint: when INTERVIEW_EXPECTED_SPEAKERS is
        configured, process_interview_file passes it through to
        transcribe_file so diarization can be constrained instead of
        auto-detecting (and potentially over-segmenting) the speaker count."""
        config_with_hint = {**CONFIG, "interview_expected_speakers": 2}
        with (
            patch.object(
                main_module,
                "transcribe_file",
                return_value=TranscriptionResult(
                    success=True,
                    transcript="逐字稿",
                    segments=[{"start": 0.0, "end": 1.0, "text": "逐字稿"}],
                ),
            ) as mock_transcribe,
            patch.object(main_module, "structure_interview", return_value=FAKE_INTERVIEW_NOTE),
            patch.object(
                main_module,
                "create_interview_page",
                return_value=NotionWriteResult(success=True, page_id="page-interview-hint"),
            ),
        ):
            main_module.process_interview_file(self.video, self.store, config_with_hint, self.log)

        self.assertEqual(mock_transcribe.call_args.kwargs.get("num_speakers"), 2)

    def test_write_failure_preserves_transcript_and_retry_skips_transcription(self):
        with (
            patch.object(
                main_module,
                "transcribe_file",
                return_value=TranscriptionResult(
                    success=True,
                    transcript="逐字稿",
                    segments=[{"start": 0.0, "end": 1.0, "text": "逐字稿"}],
                ),
            ) as mock_transcribe,
            patch.object(main_module, "structure_interview", return_value=FAKE_INTERVIEW_NOTE),
            patch.object(
                main_module,
                "create_interview_page",
                return_value=NotionWriteResult(success=False, error="invalid database id"),
            ),
        ):
            main_module.process_interview_file(self.video, self.store, CONFIG, self.log)

        file_id = StateStore.make_file_id(self.video.name, self.video.stat().st_mtime)
        record = self.store.get(file_id)
        self.assertEqual(record.status, FAILED)
        self.assertIsNotNone(record.transcript)
        self.assertEqual(mock_transcribe.call_count, 1)

        with (
            patch.object(main_module, "transcribe_file") as mock_transcribe_retry,
            patch.object(main_module, "structure_interview", return_value=FAKE_INTERVIEW_NOTE),
            patch.object(
                main_module,
                "create_interview_page",
                return_value=NotionWriteResult(success=True, page_id="page-interview-2"),
            ),
        ):
            main_module.process_interview_file(self.video, self.store, CONFIG, self.log)

        mock_transcribe_retry.assert_not_called()
        self.assertTrue(self.store.is_processed(file_id))


class InterviewBatchLoggingTests(unittest.TestCase):
    """Batch Interview Detection Logging: a distinct "N 篇訪談待分析" line
    appears only when 2+ interview files are pending; a single pending file
    uses the same general scan-log format as the meeting pipeline, and an
    unconfigured interview folder logs that interview mode is not enabled."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmpdir.name)
        self._original_state_path = main_module.INTERVIEW_STATE_PATH
        main_module.INTERVIEW_STATE_PATH = self.folder / "interview_state.json"

    def tearDown(self):
        main_module.INTERVIEW_STATE_PATH = self._original_state_path
        self.tmpdir.cleanup()

    def _run_with_fake_pending(self, filenames):
        fake_paths = [self.folder / name for name in filenames]
        for path in fake_paths:
            path.write_bytes(b"x")
        config = {**CONFIG, "interview_watch_folder": str(self.folder)}
        log = logging.getLogger("test_pipeline_batch_log")
        log.propagate = True
        with (
            patch.object(main_module, "get_files_to_process", return_value=fake_paths),
            patch.object(main_module, "process_interview_file") as mock_process,
            self.assertLogs(log, level="INFO") as captured,
        ):
            main_module._run_interview_pipeline(config, log)
        return captured.output, mock_process

    def test_not_configured_logs_not_enabled(self):
        config = {**CONFIG, "interview_watch_folder": None}
        log = logging.getLogger("test_pipeline_batch_log_unset")
        log.propagate = True
        with (
            patch.object(main_module, "process_interview_file") as mock_process,
            self.assertLogs(log, level="INFO") as captured,
        ):
            main_module._run_interview_pipeline(config, log)
        self.assertTrue(any("未啟用" in line for line in captured.output))
        mock_process.assert_not_called()

    def test_single_pending_file_uses_general_log_format_not_batch_wording(self):
        output, mock_process = self._run_with_fake_pending(["interview.mp4"])
        self.assertTrue(any("1" in line and "訪談" in line for line in output))
        self.assertFalse(any("待分析" in line for line in output))
        mock_process.assert_called_once()

    def test_multiple_pending_files_logs_batch_count(self):
        output, mock_process = self._run_with_fake_pending(["a.mp4", "b.mp4", "c.mp4"])
        self.assertTrue(any("3" in line and "待分析" in line for line in output))
        self.assertEqual(mock_process.call_count, 3)


if __name__ == "__main__":
    unittest.main()
