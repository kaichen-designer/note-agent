import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import _transcribe_worker as worker
import show_progress


class WorkerHeartbeatTests(unittest.TestCase):
    """Transcription Progress Reporting: the worker must keep the progress
    file fresh even during long silent phases (model load, audio decode,
    VAD scan of a multi-GB recording produce no segments for many minutes),
    so the viewer's staleness check only fires when the worker truly died."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.progress = Path(self.tmpdir.name) / "progress.json"
        self.stop = None

    def tearDown(self):
        if self.stop is not None:
            self.stop.set()
        self.tmpdir.cleanup()

    def test_heartbeat_refreshes_updated_at_without_phase_change(self):
        worker._write_progress(
            str(self.progress),
            {"phase": "loading_model", "file": "a.mkv", "percent": 0.0},
        )
        first = json.loads(self.progress.read_text(encoding="utf-8"))

        self.stop = worker._start_heartbeat(str(self.progress), interval=0.05)
        time.sleep(0.3)

        second = json.loads(self.progress.read_text(encoding="utf-8"))
        self.assertGreater(second["updated_at"], first["updated_at"])
        self.assertEqual(second["phase"], "loading_model")
        self.assertEqual(second["file"], "a.mkv")

    def test_heartbeat_without_any_payload_writes_nothing(self):
        with patch.object(worker, "_latest_progress", None):
            self.stop = worker._start_heartbeat(str(self.progress), interval=0.05)
            time.sleep(0.2)
            self.assertFalse(self.progress.exists())


class TranscriptAssemblyTests(unittest.TestCase):
    """Local Speaker Diarization / Diarization Failure Falls Back To Plain
    Transcript / Diarization Progress Reporting: worker._assemble_transcript()
    assembles the final transcript with or without speaker prefixes, and a
    diarization failure never propagates out -- it degrades to the plain
    transcript with a warning message instead."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.progress = Path(self.tmpdir.name) / "progress.json"
        self.segments = [
            {"start": 0.0, "end": 1.0, "text": "請問你對這個題目的想法是?"},
            {"start": 1.0, "end": 2.0, "text": "我覺得這個方向不錯。"},
        ]

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_diarization_enabled_success_produces_speaker_prefixed_transcript(self):
        labeled = [
            {**self.segments[0], "speaker": "SPEAKER_00"},
            {**self.segments[1], "speaker": "SPEAKER_01"},
        ]
        with patch.object(worker, "diarize_segments", return_value=labeled) as mock_diarize:
            transcript, warning = worker._assemble_transcript(
                self.segments,
                diarize_enabled=True,
                audio_path="interview.wav",
                hf_token="hf_test_token",
                device="cpu",
                progress_path=str(self.progress),
                filename="interview.wav",
            )

        self.assertIsNone(warning)
        self.assertEqual(
            transcript,
            "[語者 A] 請問你對這個題目的想法是?\n[語者 B] 我覺得這個方向不錯。",
        )
        mock_diarize.assert_called_once_with(
            "interview.wav", self.segments, hf_token="hf_test_token", device="cpu"
        )
        progress_payload = json.loads(self.progress.read_text(encoding="utf-8"))
        self.assertEqual(progress_payload["phase"], "diarizing")

    def test_diarization_disabled_preserves_plain_transcript(self):
        transcript, warning = worker._assemble_transcript(
            self.segments,
            diarize_enabled=False,
            audio_path="interview.wav",
            hf_token="",
            device="cpu",
            progress_path=str(self.progress),
            filename="interview.wav",
        )
        self.assertIsNone(warning)
        self.assertEqual(transcript, "請問你對這個題目的想法是?我覺得這個方向不錯。")
        self.assertFalse(self.progress.exists())

    def test_diarization_failure_falls_back_to_plain_transcript(self):
        with patch.object(worker, "diarize_segments", side_effect=RuntimeError("no token")):
            transcript, warning = worker._assemble_transcript(
                self.segments,
                diarize_enabled=True,
                audio_path="interview.wav",
                hf_token="",
                device="cpu",
                progress_path=str(self.progress),
                filename="interview.wav",
            )
        self.assertEqual(warning, "no token")
        self.assertEqual(transcript, "請問你對這個題目的想法是?我覺得這個方向不錯。")


class ViewerStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.progress = Path(self.tmpdir.name) / "progress.json"
        patcher = patch.object(show_progress, "PROGRESS_PATH", self.progress)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write(self, payload: dict) -> None:
        self.progress.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def test_fresh_transcribing_progress_is_shown(self):
        self._write(
            {
                "phase": "transcribing",
                "file": "a.mkv",
                "duration_sec": 100.0,
                "processed_sec": 50.0,
                "percent": 50.0,
                "updated_at": time.time(),
            }
        )
        status = show_progress.read_status()
        self.assertIn("a.mkv", status)
        self.assertIn("50.0%", status)

    def test_diarizing_phase_renders_status_instead_of_unknown(self):
        self._write(
            {
                "phase": "diarizing",
                "file": "interview.m4a",
                "percent": 0.0,
                "updated_at": time.time(),
            }
        )
        status = show_progress.read_status()
        self.assertIn("interview.m4a", status)
        self.assertNotIn("狀態不明", status)

    def test_preparing_audio_phase_renders_explanation(self):
        self._write(
            {
                "phase": "preparing_audio",
                "file": "big.mkv",
                "percent": 0.0,
                "updated_at": time.time(),
            }
        )
        status = show_progress.read_status()
        self.assertIn("big.mkv", status)
        self.assertNotIn("狀態不明", status)
        self.assertNotIn("過期", status)

    def test_stale_in_flight_progress_reports_expired(self):
        self._write(
            {
                "phase": "loading_model",
                "file": "a.mkv",
                "percent": 0.0,
                "updated_at": time.time() - show_progress.FRESH_SECONDS - 10,
            }
        )
        self.assertIn("過期", show_progress.read_status())


if __name__ == "__main__":
    unittest.main()
