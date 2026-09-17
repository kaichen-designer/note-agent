import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _install_fake_whisperx(diarization_pipeline_factory, assign_word_speakers):
    """Build a fake `whisperx` module tree and register it in sys.modules so
    `diarize_segments()`'s deferred `import whisperx` (kept out of module
    top-level because whisperx is only installed in .venv-transcribe, not the
    venv this test suite runs in) picks up the fake instead of the real
    package."""
    fake_diarize_submodule = types.ModuleType("whisperx.diarize")
    fake_diarize_submodule.DiarizationPipeline = diarization_pipeline_factory
    fake_whisperx = types.ModuleType("whisperx")
    fake_whisperx.diarize = fake_diarize_submodule
    fake_whisperx.assign_word_speakers = assign_word_speakers
    return patch.dict(
        sys.modules, {"whisperx": fake_whisperx, "whisperx.diarize": fake_diarize_submodule}
    )


class DiarizeSegmentsSuccessTests(unittest.TestCase):
    """Local Speaker Diarization: diarize_segments() labels each input
    segment with a `speaker` field derived from the underlying whisperx/
    pyannote diarization pipeline."""

    def test_segments_are_labeled_with_speaker_field(self):
        labeled = [
            {"start": 0.0, "end": 1.0, "text": "請問你對這個題目的想法是?", "speaker": "SPEAKER_00"},
            {"start": 1.0, "end": 2.0, "text": "我覺得這個方向不錯。", "speaker": "SPEAKER_01"},
        ]
        mock_pipeline_instance = MagicMock(return_value="diarize_df_sentinel")
        mock_pipeline_factory = MagicMock(return_value=mock_pipeline_instance)
        mock_assign_word_speakers = MagicMock(return_value={"segments": labeled})

        with _install_fake_whisperx(mock_pipeline_factory, mock_assign_word_speakers):
            from diarize import diarize_segments

            result = diarize_segments(
                "interview.wav",
                [
                    {"start": 0.0, "end": 1.0, "text": "請問你對這個題目的想法是?"},
                    {"start": 1.0, "end": 2.0, "text": "我覺得這個方向不錯。"},
                ],
                hf_token="hf_test_token",
                device="cpu",
            )

        self.assertEqual(result[0]["speaker"], "SPEAKER_00")
        self.assertEqual(result[1]["speaker"], "SPEAKER_01")
        mock_pipeline_factory.assert_called_once_with(
            model_name="pyannote/speaker-diarization-3.1", token="hf_test_token", device="cpu"
        )
        mock_pipeline_instance.assert_called_once_with("interview.wav", num_speakers=None)

    def test_num_speakers_hint_is_forwarded_to_pipeline_call(self):
        """Expected Speaker Count Hint: when the caller knows how many
        speakers are actually in the recording (e.g. a 1-on-1 interview),
        passing num_speakers constrains the diarization pipeline instead of
        letting it auto-detect and potentially over-segment one speaker's
        voice into multiple speaker labels."""
        labeled = [{"start": 0.0, "end": 1.0, "text": "hi", "speaker": "SPEAKER_00"}]
        mock_pipeline_instance = MagicMock(return_value="diarize_df_sentinel")
        mock_pipeline_factory = MagicMock(return_value=mock_pipeline_instance)
        mock_assign_word_speakers = MagicMock(return_value={"segments": labeled})

        with _install_fake_whisperx(mock_pipeline_factory, mock_assign_word_speakers):
            from diarize import diarize_segments

            diarize_segments(
                "interview.wav",
                [{"start": 0.0, "end": 1.0, "text": "hi"}],
                hf_token="hf_test_token",
                device="cpu",
                num_speakers=2,
            )

        mock_pipeline_instance.assert_called_once_with("interview.wav", num_speakers=2)


class DiarizeSegmentsFailureTests(unittest.TestCase):
    """Diarization Failure Falls Back To Plain Transcript: diarize_segments()
    must not swallow errors from the underlying pipeline -- the caller
    (_transcribe_worker.py) decides how to degrade, so the exception has to
    propagate out of this function."""

    def test_pipeline_error_propagates(self):
        mock_pipeline_factory = MagicMock(side_effect=RuntimeError("model download failed"))
        mock_assign_word_speakers = MagicMock()

        with _install_fake_whisperx(mock_pipeline_factory, mock_assign_word_speakers):
            from diarize import diarize_segments

            with self.assertRaises(RuntimeError):
                diarize_segments(
                    "interview.wav",
                    [{"start": 0.0, "end": 1.0, "text": "hi"}],
                    hf_token="hf_test_token",
                    device="cpu",
                )

        mock_assign_word_speakers.assert_not_called()


if __name__ == "__main__":
    unittest.main()
