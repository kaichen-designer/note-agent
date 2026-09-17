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
    audio_path: str,
    segments: list[dict],
    *,
    hf_token: str,
    device: str,
    num_speakers: int | None = None,
) -> list[dict]:
    """Label each segment with a `speaker` field.

    `segments` is a list of dicts with at least `start`/`end`/`text` keys
    (as produced by faster-whisper). Returns the equivalent list with a
    `speaker` key added to each segment (e.g. "SPEAKER_00"), in the same
    order as the input.

    num_speakers is an optional hint for how many distinct speakers are
    actually in the recording (e.g. 2 for a 1-on-1 interview). Without it,
    pyannote auto-detects the speaker count, which can over-segment a single
    speaker's voice into multiple labels when tone/background noise varies
    (observed in production). Passing the known count constrains the
    pipeline instead.
    """
    import whisperx
    import whisperx.diarize  # newer whisperx does not expose `diarize` as a `whisperx` attribute via plain `import whisperx`

    # Pin the pipeline explicitly: whisperx's own default model has changed
    # between versions (observed: newer releases default to
    # pyannote/speaker-diarization-community-1, a separately-gated model),
    # so relying on the library's default silently breaks access for anyone
    # who only accepted the license for speaker-diarization-3.1 (the model
    # README.md/.env.example instruct users to accept).
    diarize_model = whisperx.diarize.DiarizationPipeline(
        model_name="pyannote/speaker-diarization-3.1", token=hf_token, device=device
    )
    diarization = diarize_model(audio_path, num_speakers=num_speakers)
    result = whisperx.assign_word_speakers(diarization, {"segments": segments})
    return result["segments"]
