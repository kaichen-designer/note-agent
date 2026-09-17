import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_num_speakers_not_given_omits_flag(self):
        from transcribe import build_worker_command

        cmd = build_worker_command("py.exe", "a.m4a", "large-v3", "prog.json", vad_filter=True)
        self.assertFalse(any(arg.startswith("--num-speakers=") for arg in cmd))

    def test_num_speakers_given_appends_flag(self):
        from transcribe import build_worker_command

        cmd = build_worker_command(
            "py.exe", "a.m4a", "large-v3", "prog.json", vad_filter=True, num_speakers=2
        )
        self.assertIn("--num-speakers=2", cmd)

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

    def test_diarization_disabled_by_default_no_flag(self):
        from transcribe import build_worker_command

        cmd = build_worker_command("py.exe", "a.m4a", "large-v3", "prog.json", vad_filter=True)
        self.assertNotIn("--diarize", cmd)

    def test_diarization_enabled_appends_diarize_flag(self):
        from transcribe import build_worker_command

        cmd = build_worker_command(
            "py.exe", "a.m4a", "large-v3", "prog.json", vad_filter=True, diarization_enabled=True
        )
        self.assertIn("--diarize", cmd)


class _FakeCompletedProcess:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


class SegmentTimestampPreservationTests(unittest.TestCase):
    """Segment Timestamp Preservation On Request: preserve_segments is an
    opt-in flag that, when set, carries per-segment start/end timestamps
    through to the caller; when unset, behavior (including the worker
    command line) is unchanged from before this flag existed."""

    def test_preserve_segments_appends_keep_segments_flag(self):
        from transcribe import build_worker_command

        cmd = build_worker_command(
            "py.exe", "a.m4a", "large-v3", "prog.json", vad_filter=True, preserve_segments=True
        )
        self.assertIn("--keep-segments", cmd)

    def test_preserve_segments_not_requested_omits_flag(self):
        from transcribe import build_worker_command

        cmd = build_worker_command("py.exe", "a.m4a", "large-v3", "prog.json", vad_filter=True)
        self.assertNotIn("--keep-segments", cmd)

    def test_segments_requested_are_parsed_into_result(self):
        def fake_run(command, **kwargs):
            return _FakeCompletedProcess(
                '{"transcript": "ok", "segments": '
                '[{"start": 0.0, "end": 1.5, "text": "hello"}, '
                '{"start": 1.5, "end": 3.2, "text": "world"}]}'
            )

        with patch("transcribe.subprocess.run", side_effect=fake_run):
            result = transcribe_file(
                "a.m4a", venv_python="py.exe", model_size="large-v3", preserve_segments=True
            )

        self.assertTrue(result.success)
        self.assertEqual(
            result.segments,
            [{"start": 0.0, "end": 1.5, "text": "hello"}, {"start": 1.5, "end": 3.2, "text": "world"}],
        )

    def test_segments_not_requested_result_has_none(self):
        def fake_run(command, **kwargs):
            return _FakeCompletedProcess('{"transcript": "ok"}')

        with patch("transcribe.subprocess.run", side_effect=fake_run):
            result = transcribe_file("a.m4a", venv_python="py.exe", model_size="large-v3")

        self.assertTrue(result.success)
        self.assertIsNone(result.segments)


class DiarizationPassthroughTests(unittest.TestCase):
    """`src/transcribe.py`'s `transcribe_file()` new `diarization_enabled`/
    `hf_token` parameters: the Hugging Face token travels to the worker via
    an environment variable, not argv (Local Speaker Diarization design
    decision: never let the token appear in a process command line)."""

    def test_diarization_enabled_passes_diarize_flag_and_token_via_env(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["env"] = kwargs.get("env")
            return _FakeCompletedProcess('{"transcript": "ok"}')

        with patch("transcribe.subprocess.run", side_effect=fake_run):
            result = transcribe_file(
                "a.m4a",
                venv_python="py.exe",
                model_size="large-v3",
                diarization_enabled=True,
                hf_token="hf_secret_token",
            )

        self.assertTrue(result.success)
        self.assertIn("--diarize", captured["command"])
        self.assertNotIn("hf_secret_token", captured["command"])
        self.assertEqual(captured["env"]["HUGGINGFACE_TOKEN"], "hf_secret_token")

    def test_diarization_disabled_does_not_override_env(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured["env"] = kwargs.get("env")
            return _FakeCompletedProcess('{"transcript": "ok"}')

        with patch("transcribe.subprocess.run", side_effect=fake_run):
            transcribe_file("a.m4a", venv_python="py.exe", model_size="large-v3")

        self.assertIsNone(captured["env"])

    def test_diarization_warning_in_worker_output_is_parsed_into_result(self):
        def fake_run(command, **kwargs):
            return _FakeCompletedProcess(
                '{"transcript": "ok", "diarization_warning": "no token"}'
            )

        with patch("transcribe.subprocess.run", side_effect=fake_run):
            result = transcribe_file(
                "a.m4a",
                venv_python="py.exe",
                model_size="large-v3",
                diarization_enabled=True,
                hf_token="hf_secret_token",
            )

        self.assertTrue(result.success)
        self.assertEqual(result.diarization_warning, "no token")

    def test_no_diarization_warning_defaults_to_none(self):
        def fake_run(command, **kwargs):
            return _FakeCompletedProcess('{"transcript": "ok"}')

        with patch("transcribe.subprocess.run", side_effect=fake_run):
            result = transcribe_file("a.m4a", venv_python="py.exe", model_size="large-v3")

        self.assertIsNone(result.diarization_warning)


if __name__ == "__main__":
    unittest.main()
