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


def _diarization_device() -> str:
    """Pick the diarization pipeline's device. whisperx pulls in torch as a
    transitive dependency, so this import is only safe once diarization is
    actually enabled (see the deferred-import note on `diarize_segments`)."""
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _format_diarized_transcript(labeled_segments: list[dict]) -> str:
    """Turn whisperx/pyannote-labeled segments into the transcript text,
    prefixing each segment with a `[語者 X]` label. Speaker letters are
    assigned in the order each distinct diarization speaker id first
    appears, not from the (meaningless) numeric order of the ids themselves."""
    letter_by_speaker: dict[str, str] = {}
    lines: list[str] = []
    for segment in labeled_segments:
        speaker = segment.get("speaker") or "SPEAKER_UNKNOWN"
        if speaker not in letter_by_speaker:
            letter_by_speaker[speaker] = chr(ord("A") + len(letter_by_speaker))
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"[語者 {letter_by_speaker[speaker]}] {text}")
    return "\n".join(lines)


def _assemble_transcript(
    segment_records: list[dict],
    diarize_enabled: bool,
    audio_path: str,
    hf_token: str,
    device: str,
    progress_path: str | None,
    filename: str,
) -> tuple[str, str | None]:
    """Build the (not yet OpenCC-converted) transcript text from whisper's
    segments, optionally labeling it with speakers. Returns (transcript,
    diarization_warning): diarization_warning is set only when diarization
    was attempted and failed, in which case transcript is the plain
    (unlabeled) text -- diarization failure SHALL NOT propagate out of this
    function, per Diarization Failure Falls Back To Plain Transcript."""
    plain_text = "".join(record["text"] for record in segment_records).strip()

    if not diarize_enabled:
        return plain_text, None

    _write_progress(progress_path, {"phase": "diarizing", "file": filename, "percent": 0.0})
    try:
        labeled_segments = diarize_segments(audio_path, segment_records, hf_token=hf_token, device=device)
    except Exception as exc:
        return plain_text, str(exc)

    return _format_diarized_transcript(labeled_segments), None


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
    args = list(sys.argv[1:])
    # VAD silence skipping is on by default; --no-vad opts out (used when the
    # detector mistakes quiet speech for silence, e.g. far-field recordings).
    vad_filter = "--no-vad" not in args
    # Speaker diarization is off by default; --diarize opts in (SPEAKER_DIARIZATION_ENABLED
    # in .env). The Hugging Face token travels via an environment variable rather than a
    # command-line argument so it never appears in process listings or logged commands.
    diarize_enabled = "--diarize" in args
    args = [a for a in args if a not in ("--no-vad", "--diarize")]

    if len(args) < 2:
        print(json.dumps({"error": "usage: _transcribe_worker.py <audio_path> <model_size> [progress_file] [--no-vad] [--diarize]"}))
        return 1

    audio_path, model_size = args[0], args[1]
    progress_path = args[2] if len(args) > 2 else None
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
        transcript, diarization_warning = _assemble_transcript(
            segment_records, diarize_enabled, audio_path, hf_token, device, progress_path, filename
        )

        # Whisper's Chinese output script (simplified vs. traditional) is not
        # configurable and varies unpredictably between recordings even with
        # identical settings, so normalize to Taiwan-style traditional here
        # rather than storing whatever the model happened to decode. Applied
        # after diarization so the [語者 X] labels stay untouched (they are
        # already Traditional Chinese) while the spoken text is normalized.
        from opencc import OpenCC

        transcript = OpenCC("s2twp").convert(transcript)
    except Exception as exc:
        _write_progress(progress_path, {"phase": "failed", "file": filename, "error": str(exc)})
        print(json.dumps({"error": str(exc)}))
        return 1

    _write_progress(
        progress_path,
        {"phase": "done", "file": filename, "duration_sec": duration, "percent": 100.0},
    )
    result_payload: dict = {"transcript": transcript}
    if diarization_warning:
        result_payload["diarization_warning"] = diarization_warning
    print(json.dumps(result_payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
