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
