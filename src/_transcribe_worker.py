"""Worker script executed inside the local transcription virtual environment.

Runs in a Python 3.11 venv where faster-whisper is installed (see
requirements-transcribe.txt). Takes an audio file path, a model size, and an
optional progress file path; prints a single JSON object to stdout, and exits
non-zero on failure so the calling process (transcribe.py, running in the
main venv) can distinguish success from failure without depending on
faster-whisper itself. While transcribing, it periodically writes progress
(phase, seconds processed, percent) to the progress file so a separate
viewer can display live status even for windowless scheduled runs.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from diarize import diarize_segments

if hasattr(sys.stdout, "reconfigure"):
    # Force UTF-8 regardless of the invoking console's codepage. This process
    # is normally launched with its stdout piped to the parent (not a real
    # console), so Windows falls back to the system's legacy codepage (e.g.
    # cp950 on Traditional Chinese Windows), which can't encode every
    # character Whisper may transcribe (e.g. simplified Chinese), crashing
    # this script before it can print its JSON result.
    sys.stdout.reconfigure(encoding="utf-8")


def _register_cuda_dll_dirs() -> None:
    """Make the pip-installed nvidia-cublas-cu12/nvidia-cudnn-cu12 DLLs
    discoverable. These packages ship their DLLs under site-packages/nvidia/*
    /bin instead of a system-wide location. ctranslate2's CUDA loading happens
    deep inside a compiled extension that does not honor os.add_dll_directory
    registrations made from Python, so the directories must be prepended to
    the PATH environment variable instead, which the OS-level DLL loader
    always respects. Uses sys.prefix so this works regardless of where this
    venv is located on disk."""
    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    bin_dirs = [str(d) for d in site_packages.glob("nvidia/*/bin")]
    if bin_dirs:
        os.environ["PATH"] = os.pathsep.join(bin_dirs) + os.pathsep + os.environ.get("PATH", "")


# Refresh cadence for the heartbeat thread. Must stay well under the
# viewer's FRESH_SECONDS (show_progress.py) so a live worker is never
# mistaken for a dead one.
HEARTBEAT_SECONDS = 5

# Last payload written, shared with the heartbeat thread. The lock also
# serializes the file writes themselves so the viewer never reads a
# torn/interleaved JSON document.
_progress_lock = threading.Lock()
_latest_progress: dict | None = None


def _write_progress(progress_path: str | None, payload: dict) -> None:
    """Best-effort progress write; progress must never break transcription."""
    global _latest_progress
    if not progress_path:
        return
    with _progress_lock:
        _latest_progress = dict(payload)
        try:
            payload["updated_at"] = time.time()
            Path(progress_path).write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass


@dataclass
class WorkerArgs:
    audio_path: str
    model_size: str
    progress_path: str | None
    vad_filter: bool
    diarize_enabled: bool
    keep_segments: bool
    num_speakers: int | None = None


def _parse_worker_args(argv: list[str]) -> WorkerArgs | None:
    """Parse the worker's command line: <audio_path> <model_size>
    [progress_file] [--no-vad] [--diarize] [--keep-segments]
    [--num-speakers=N]. Returns None when the required positional arguments
    are missing, so the caller can print the usage error and exit non-zero."""
    num_speakers: int | None = None
    args: list[str] = []
    for a in argv:
        if a in ("--no-vad", "--diarize", "--keep-segments"):
            continue
        if a.startswith("--num-speakers="):
            num_speakers = int(a.split("=", 1)[1])
            continue
        args.append(a)
    if len(args) < 2:
        return None
    return WorkerArgs(
        audio_path=args[0],
        model_size=args[1],
        progress_path=args[2] if len(args) > 2 else None,
        vad_filter="--no-vad" not in argv,
        diarize_enabled="--diarize" in argv,
        keep_segments="--keep-segments" in argv,
        num_speakers=num_speakers,
    )


def _apply_text_conversion(segments: list[dict], convert) -> list[dict]:
    """Run each segment's `text` through `convert` (e.g. OpenCC's
    simplified->traditional normalizer), preserving every other key
    unchanged. Applied to the --keep-segments payload so interview mode's
    quotes/timestamps -- which read segment text directly, never the joined
    transcript string -- get the same script normalization the transcript
    already receives."""
    return [{**segment, "text": convert(segment["text"])} for segment in segments]


def _build_result_payload(
    transcript: str,
    diarization_warning: str | None,
    segment_records: list[dict],
    keep_segments: bool,
) -> dict:
    """Assemble the JSON payload printed to stdout. segment_records are
    included verbatim (same start/end/text as faster-whisper produced, on
    the original audio timeline) only when the caller opted in via
    --keep-segments; the default shape is unchanged from before this flag
    existed."""
    payload: dict = {"transcript": transcript}
    if diarization_warning:
        payload["diarization_warning"] = diarization_warning
    if keep_segments:
        payload["segments"] = segment_records
    return payload


def _diarization_device() -> str:
    """Pick the diarization pipeline's device. whisperx pulls in torch as a
    transitive dependency, so this import is only safe once diarization is
    actually enabled (see the deferred-import note on `diarize_segments`)."""
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _assign_speaker_letters(labeled_segments: list[dict]) -> list[dict]:
    """Convert each segment's raw diarization speaker id (e.g. SPEAKER_00)
    into a letter label (A, B, C, ...) assigned in the order each distinct
    id first appears, not from the (meaningless) numeric order of the ids
    themselves. Returns new segment dicts with `speaker` replaced by the
    letter, preserving `start`/`end`/`text`. This is the single source of
    the letter assignment, reused both for the plain-text `[語者 X]` prefixes
    and for any segments carrying a speaker label kept via --keep-segments,
    so the two never disagree on which letter means which speaker."""
    letter_by_speaker: dict[str, str] = {}
    lettered: list[dict] = []
    for segment in labeled_segments:
        speaker = segment.get("speaker") or "SPEAKER_UNKNOWN"
        if speaker not in letter_by_speaker:
            letter_by_speaker[speaker] = chr(ord("A") + len(letter_by_speaker))
        lettered.append({**segment, "speaker": letter_by_speaker[speaker]})
    return lettered


def _format_diarized_transcript(lettered_segments: list[dict]) -> str:
    """Turn letter-labeled segments (see _assign_speaker_letters) into the
    transcript text, prefixing each segment with its `[語者 X]` label."""
    lines: list[str] = []
    for segment in lettered_segments:
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"[語者 {segment['speaker']}] {text}")
    return "\n".join(lines)


def _assemble_transcript(
    segment_records: list[dict],
    diarize_enabled: bool,
    audio_path: str,
    hf_token: str,
    device: str,
    progress_path: str | None,
    filename: str,
    num_speakers: int | None = None,
) -> tuple[str, str | None, list[dict] | None]:
    """Build the (not yet OpenCC-converted) transcript text from whisper's
    segments, optionally labeling it with speakers. Returns (transcript,
    diarization_warning, lettered_segments): diarization_warning is set only
    when diarization was attempted and failed, in which case transcript is
    the plain (unlabeled) text -- diarization failure SHALL NOT propagate
    out of this function, per Diarization Failure Falls Back To Plain
    Transcript. lettered_segments is the letter-labeled segment list (see
    _assign_speaker_letters) when diarization succeeded, or None when
    diarization was not enabled or failed."""
    plain_text = "".join(record["text"] for record in segment_records).strip()

    if not diarize_enabled:
        return plain_text, None, None

    _write_progress(progress_path, {"phase": "diarizing", "file": filename, "percent": 0.0})
    try:
        labeled_segments = diarize_segments(
            audio_path, segment_records, hf_token=hf_token, device=device, num_speakers=num_speakers
        )
    except Exception as exc:
        return plain_text, str(exc), None

    lettered_segments = _assign_speaker_letters(labeled_segments)
    return _format_diarized_transcript(lettered_segments), None, lettered_segments


def _start_heartbeat(
    progress_path: str, interval: float = HEARTBEAT_SECONDS
) -> threading.Event:
    """Keep re-stamping updated_at on the last progress payload so the file
    only goes stale when this process is actually gone. Model loading and
    model.transcribe()'s eager audio decode + VAD scan can stay silent for
    many minutes on multi-GB recordings; without a heartbeat the viewer
    cannot tell that from a crashed worker. Daemon thread: it dies with the
    process, which is exactly what makes staleness meaningful. Returns a
    stop event (used by tests; production just lets it run to exit)."""

    def _beat() -> None:
        while not stop.wait(interval):
            with _progress_lock:
                if _latest_progress is None:
                    continue
                payload = dict(_latest_progress)
                payload["updated_at"] = time.time()
                try:
                    Path(progress_path).write_text(
                        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                    )
                except OSError:
                    pass

    stop = threading.Event()
    threading.Thread(target=_beat, daemon=True).start()
    return stop


def main() -> int:
    _register_cuda_dll_dirs()
    # VAD silence skipping is on by default; --no-vad opts out (used when the
    # detector mistakes quiet speech for silence, e.g. far-field recordings).
    # Speaker diarization is off by default; --diarize opts in (SPEAKER_DIARIZATION_ENABLED
    # in .env). The Hugging Face token travels via an environment variable rather than a
    # command-line argument so it never appears in process listings or logged commands.
    # --keep-segments is off by default; only the interview pipeline passes it.
    parsed_args = _parse_worker_args(sys.argv[1:])
    if parsed_args is None:
        print(json.dumps({"error": "usage: _transcribe_worker.py <audio_path> <model_size> [progress_file] [--no-vad] [--diarize] [--keep-segments] [--num-speakers=N]"}))
        return 1

    audio_path = parsed_args.audio_path
    model_size = parsed_args.model_size
    progress_path = parsed_args.progress_path
    vad_filter = parsed_args.vad_filter
    diarize_enabled = parsed_args.diarize_enabled
    keep_segments = parsed_args.keep_segments
    num_speakers = parsed_args.num_speakers
    filename = Path(audio_path).name

    try:
        from faster_whisper import WhisperModel
    except Exception as exc:  # pragma: no cover - environment misconfiguration
        print(json.dumps({"error": f"faster-whisper unavailable: {exc}"}))
        return 1

    if progress_path:
        _start_heartbeat(progress_path)
    _write_progress(progress_path, {"phase": "loading_model", "file": filename, "percent": 0.0})

    try:
        model = WhisperModel(model_size, device="auto", compute_type="auto")
        # transcribe() eagerly decodes the audio and runs VAD before yielding
        # any segment -- on multi-GB recordings this is the longest silent
        # stretch, so give the viewer a phase of its own for it.
        _write_progress(progress_path, {"phase": "preparing_audio", "file": filename, "percent": 0.0})
        segments, info = model.transcribe(audio_path, vad_filter=vad_filter)
        duration = float(info.duration or 0)

        segment_records: list[dict] = []
        last_write = 0.0
        for segment in segments:
            segment_records.append({"start": segment.start, "end": segment.end, "text": segment.text})
            now = time.monotonic()
            if now - last_write >= 2:
                last_write = now
                percent = (segment.end / duration * 100) if duration else 0.0
                _write_progress(
                    progress_path,
                    {
                        "phase": "transcribing",
                        "file": filename,
                        "duration_sec": duration,
                        "processed_sec": segment.end,
                        "percent": round(min(percent, 100.0), 1),
                    },
                )

        hf_token = os.environ.get("HUGGINGFACE_TOKEN", "") if diarize_enabled else ""
        device = _diarization_device() if diarize_enabled else "cpu"
        transcript, diarization_warning, lettered_segments = _assemble_transcript(
            segment_records,
            diarize_enabled,
            audio_path,
            hf_token,
            device,
            progress_path,
            filename,
            num_speakers=num_speakers,
        )
        # Prefer the speaker-labeled segments (when diarization succeeded)
        # for --keep-segments output, so interview timestamps carry the same
        # [語者 X] letters as the plain-text transcript; fall back to the
        # unlabeled segments when diarization was off or failed.
        payload_segments = lettered_segments if lettered_segments is not None else segment_records

        # Whisper's Chinese output script (simplified vs. traditional) is not
        # configurable and varies unpredictably between recordings even with
        # identical settings, so normalize to Taiwan-style traditional here
        # rather than storing whatever the model happened to decode. Applied
        # after diarization so the [語者 X] labels stay untouched (they are
        # already Traditional Chinese) while the spoken text is normalized.
        # Segment text is converted separately from the joined transcript
        # string because interview mode reads segments directly (see
        # main.py's process_interview_file), never the joined transcript.
        from opencc import OpenCC

        converter = OpenCC("s2twp")
        transcript = converter.convert(transcript)
        if payload_segments:
            payload_segments = _apply_text_conversion(payload_segments, converter.convert)
    except Exception as exc:
        _write_progress(progress_path, {"phase": "failed", "file": filename, "error": str(exc)})
        print(json.dumps({"error": str(exc)}))
        return 1

    _write_progress(
        progress_path,
        {"phase": "done", "file": filename, "duration_sec": duration, "percent": 100.0},
    )
    result_payload = _build_result_payload(
        transcript, diarization_warning, payload_segments, keep_segments
    )
    print(json.dumps(result_payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
