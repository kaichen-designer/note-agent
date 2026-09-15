"""Local speaker diarization via whisperx/pyannote.

Deferred `import whisperx` (not at module top-level): whisperx and its
torch/pyannote.audio dependencies only live in .venv-transcribe, not the
main environment that runs this project's test suite, so importing this
module must not require whisperx to be installed. See
src/_transcribe_worker.py's identical pattern for `faster_whisper`.

whisperx's diarization/assignment step is used without a preceding
whisperx.align() forced-alignment pass: assign_word_speakers() falls back to
assigning one speaker per segment (by start/end overlap with diarization
turns) when the segments carry no word-level timestamps, which avoids
pulling in a second, per-language alignment model on top of the diarization
model.

Never swallows errors: any failure (missing/invalid Hugging Face token,
model download failure, pipeline runtime error) propagates to the caller,
which decides whether/how to degrade -- see the "Diarization Failure Falls
Back To Plain Transcript" requirement in
openspec/changes/add-speaker-diarization/specs/speaker-diarization/spec.md.
"""
from __future__ import annotations


def diarize_segments(
    audio_path: str, segments: list[dict], *, hf_token: str, device: str
) -> list[dict]:
    """Label each segment with a `speaker` field.

    `segments` is a list of dicts with at least `start`/`end`/`text` keys
    (as produced by faster-whisper). Returns the equivalent list with a
    `speaker` key added to each segment (e.g. "SPEAKER_00"), in the same
    order as the input.
    """
    import whisperx

    diarize_model = whisperx.diarize.DiarizationPipeline(use_auth_token=hf_token, device=device)
    diarization = diarize_model(audio_path)
    result = whisperx.assign_word_speakers(diarization, {"segments": segments})
    return result["segments"]
