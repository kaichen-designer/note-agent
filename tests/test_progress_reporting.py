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
            transcript, warning, lettered_segments = worker._assemble_transcript(
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
            "interview.wav", self.segments, hf_token="hf_test_token", device="cpu", num_speakers=None
        )
        progress_payload = json.loads(self.progress.read_text(encoding="utf-8"))
        self.assertEqual(progress_payload["phase"], "diarizing")

        # Segment Speaker Labels When Diarization Enabled: the returned
        # lettered segments use the same A/B letters as the plain-text
        # [語者 X] prefixes, keeping the two consistent.
        self.assertEqual(lettered_segments[0]["speaker"], "A")
        self.assertEqual(lettered_segments[1]["speaker"], "B")
        self.assertEqual(lettered_segments[0]["start"], 0.0)
        self.assertEqual(lettered_segments[0]["text"], "請問你對這個題目的想法是?")

    def test_num_speakers_hint_is_forwarded_to_diarize_segments(self):
        """Expected Speaker Count Hint: when the caller knows the recording
        has a fixed number of speakers (e.g. 2 for a 1-on-1 interview),
        _assemble_transcript passes it through to diarize_segments instead
        of always letting pyannote auto-detect the count."""
        labeled = [
            {**self.segments[0], "speaker": "SPEAKER_00"},
            {**self.segments[1], "speaker": "SPEAKER_01"},
        ]
        with patch.object(worker, "diarize_segments", return_value=labeled) as mock_diarize:
            worker._assemble_transcript(
                self.segments,
                diarize_enabled=True,
                audio_path="interview.wav",
                hf_token="hf_test_token",
                device="cpu",
                progress_path=str(self.progress),
                filename="interview.wav",
                num_speakers=2,
            )

        mock_diarize.assert_called_once_with(
            "interview.wav", self.segments, hf_token="hf_test_token", device="cpu", num_speakers=2
        )

    def test_diarization_disabled_preserves_plain_transcript(self):
        transcript, warning, lettered_segments = worker._assemble_transcript(
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
        self.assertIsNone(lettered_segments)
        self.assertFalse(self.progress.exists())

    def test_diarization_failure_falls_back_to_plain_transcript(self):
        with patch.object(worker, "diarize_segments", side_effect=RuntimeError("no token")):
            transcript, warning, lettered_segments = worker._assemble_transcript(
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
        self.assertIsNone(lettered_segments)


class SpeakerLetterAssignmentTests(unittest.TestCase):
    """Speaker letters (語者 A/B/...) are assigned in first-appearance order
    of the raw diarization speaker id, and the same assignment must be
    reusable to label segments (not just to build the plain-text prefix)."""

    def test_letters_assigned_in_first_appearance_order(self):
        labeled = [
            {"start": 0.0, "end": 1.0, "text": "a", "speaker": "SPEAKER_01"},
            {"start": 1.0, "end": 2.0, "text": "b", "speaker": "SPEAKER_00"},
            {"start": 2.0, "end": 3.0, "text": "c", "speaker": "SPEAKER_01"},
        ]
        lettered = worker._assign_speaker_letters(labeled)
        self.assertEqual([s["speaker"] for s in lettered], ["A", "B", "A"])

    def test_missing_speaker_id_becomes_unknown_bucket(self):
        labeled = [{"start": 0.0, "end": 1.0, "text": "a", "speaker": None}]
        lettered = worker._assign_speaker_letters(labeled)
        self.assertEqual(lettered[0]["speaker"], "A")

    def test_original_start_end_text_preserved(self):
        labeled = [{"start": 5.0, "end": 6.0, "text": "hi", "speaker": "SPEAKER_00"}]
        lettered = worker._assign_speaker_letters(labeled)
        self.assertEqual(lettered[0]["start"], 5.0)
        self.assertEqual(lettered[0]["end"], 6.0)
        self.assertEqual(lettered[0]["text"], "hi")


class WorkerArgParsingTests(unittest.TestCase):
    """Segment Timestamp Preservation On Request: --keep-segments is parsed
    and stripped from argv the same way --no-vad and --diarize already are,
    and is off by default so existing invocations are unaffected."""

    def test_keep_segments_flag_is_recognized_and_stripped(self):
        parsed = worker._parse_worker_args(
            ["a.m4a", "large-v3", "prog.json", "--keep-segments"]
        )
        self.assertTrue(parsed.keep_segments)
        self.assertEqual(parsed.audio_path, "a.m4a")
        self.assertEqual(parsed.progress_path, "prog.json")

    def test_keep_segments_not_present_defaults_to_false(self):
        parsed = worker._parse_worker_args(["a.m4a", "large-v3"])
        self.assertFalse(parsed.keep_segments)

    def test_keep_segments_combines_with_no_vad_and_diarize(self):
        parsed = worker._parse_worker_args(
            ["a.m4a", "large-v3", "prog.json", "--no-vad", "--diarize", "--keep-segments"]
        )
        self.assertFalse(parsed.vad_filter)
        self.assertTrue(parsed.diarize_enabled)
        self.assertTrue(parsed.keep_segments)

    def test_num_speakers_flag_is_parsed_as_int_and_stripped_from_positionals(self):
        parsed = worker._parse_worker_args(
            ["a.m4a", "large-v3", "prog.json", "--diarize", "--num-speakers=2"]
        )
        self.assertEqual(parsed.num_speakers, 2)
        self.assertEqual(parsed.audio_path, "a.m4a")
        self.assertEqual(parsed.progress_path, "prog.json")

    def test_num_speakers_not_present_defaults_to_none(self):
        parsed = worker._parse_worker_args(["a.m4a", "large-v3"])
        self.assertIsNone(parsed.num_speakers)


class SegmentTextConversionTests(unittest.TestCase):
    """Regression: OpenCC simplified->traditional normalization was only
    ever applied to the joined transcript string, never to each segment's
    own text -- so interview mode (which uses --keep-segments' segment list,
    not the joined transcript, per main.py's process_interview_file) could
    silently carry whatever script whisper happened to decode. Every
    segment's text must go through the same conversion the transcript does."""

    def test_each_segment_text_is_converted(self):
        segments = [
            {"start": 0.0, "end": 1.0, "text": "simplified-a"},
            {"start": 1.0, "end": 2.0, "text": "simplified-b"},
        ]
        converted = worker._apply_text_conversion(segments, convert=str.upper)
        self.assertEqual(converted[0]["text"], "SIMPLIFIED-A")
        self.assertEqual(converted[1]["text"], "SIMPLIFIED-B")

    def test_start_end_and_other_keys_are_preserved(self):
        segments = [{"start": 5.0, "end": 6.0, "text": "x", "speaker": "A"}]
        converted = worker._apply_text_conversion(segments, convert=str.upper)
        self.assertEqual(converted[0]["start"], 5.0)
        self.assertEqual(converted[0]["end"], 6.0)
        self.assertEqual(converted[0]["speaker"], "A")

    def test_empty_list_returns_empty_list(self):
        self.assertEqual(worker._apply_text_conversion([], convert=str.upper), [])


class WorkerResultPayloadTests(unittest.TestCase):
    """Segment Timestamp Preservation On Request: the result payload carries
    each segment's start/end/text unmodified -- on the original audio
    timeline, exactly as faster-whisper produced them -- only when the
    caller opted in; the default payload shape is unchanged."""

    def setUp(self):
        self.segment_records = [
            {"start": 0.0, "end": 1.5, "text": "請問你對這個題目的想法是?"},
            {"start": 1.5, "end": 3.2, "text": "我覺得這個方向不錯。"},
        ]

    def test_keep_segments_true_includes_segments_verbatim(self):
        payload = worker._build_result_payload(
            transcript="請問你對這個題目的想法是?我覺得這個方向不錯。",
            diarization_warning=None,
            segment_records=self.segment_records,
            keep_segments=True,
        )
        self.assertEqual(payload["segments"], self.segment_records)

    def test_keep_segments_false_omits_segments_key(self):
        payload = worker._build_result_payload(
            transcript="ok",
            diarization_warning=None,
            segment_records=self.segment_records,
            keep_segments=False,
        )
        self.assertNotIn("segments", payload)

    def test_diarization_warning_still_included_alongside_segments(self):
        payload = worker._build_result_payload(
            transcript="ok",
            diarization_warning="no token",
            segment_records=self.segment_records,
            keep_segments=True,
        )
        self.assertEqual(payload["diarization_warning"], "no token")
        self.assertEqual(payload["segments"], self.segment_records)


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
