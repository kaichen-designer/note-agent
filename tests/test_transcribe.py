import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from transcribe import transcribe_file

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TranscribeWrapperTests(unittest.TestCase):
    """Covers the transcribe.py subprocess wrapper's error handling contract.

    The end-to-end success/failure paths against the real faster-whisper
    worker (GPU transcription of a known speech sample, and a corrupted audio
    file) were verified manually against .venv-transcribe with the "tiny"
    model per task 3.1/3.2 acceptance criteria. Video Container Recording
    Support (support-mkv-recordings task 2.1) was verified the same way:
    fixtures/test_speech.wav re-muxed into fixtures/test_speech.mkv via
    `ffmpeg -i test_speech.wav -c:a copy test_speech.mkv` produced an
    identical transcript to the original wav when run through
    _transcribe_worker.py, confirming faster-whisper decodes the mkv
    container's audio track directly with no extraction step needed. This
    test covers the wrapper logic that does not require the transcription
    venv or a model download.
    """

    def test_missing_venv_python_does_not_raise(self):
        result = transcribe_file(
            FIXTURES / "test_speech.wav",
            venv_python="does-not-exist/python.exe",
            model_size="tiny",
        )
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)
        self.assertIsNone(result.transcript)


class WorkerCommandTests(unittest.TestCase):
    """Silence Skipping Via Voice Activity Detection: the worker command
    carries the opt-out flag only when VAD is disabled."""

    def test_vad_enabled_by_default_no_flag(self):
        from transcribe import build_worker_command

        cmd = build_worker_command("py.exe", "a.m4a", "large-v3", "prog.json", vad_filter=True)
        self.assertNotIn("--no-vad", cmd)
        self.assertIn("prog.json", cmd)

    def test_vad_disabled_appends_no_vad_flag(self):
        from transcribe import build_worker_command

        cmd = build_worker_command("py.exe", "a.m4a", "large-v3", None, vad_filter=False)
        self.assertIn("--no-vad", cmd)
        self.assertEqual(cmd[-1], "--no-vad")


if __name__ == "__main__":
    unittest.main()
