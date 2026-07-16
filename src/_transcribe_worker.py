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
import time
from pathlib import Path

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


def _write_progress(progress_path: str | None, payload: dict) -> None:
    """Best-effort progress write; progress must never break transcription."""
    if not progress_path:
        return
    try:
        payload["updated_at"] = time.time()
        Path(progress_path).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def main() -> int:
    _register_cuda_dll_dirs()
    args = list(sys.argv[1:])
    # VAD silence skipping is on by default; --no-vad opts out (used when the
    # detector mistakes quiet speech for silence, e.g. far-field recordings).
    vad_filter = "--no-vad" not in args
    args = [a for a in args if a != "--no-vad"]

    if len(args) < 2:
        print(json.dumps({"error": "usage: _transcribe_worker.py <audio_path> <model_size> [progress_file] [--no-vad]"}))
        return 1

    audio_path, model_size = args[0], args[1]
    progress_path = args[2] if len(args) > 2 else None
    filename = Path(audio_path).name

    try:
        from faster_whisper import WhisperModel
    except Exception as exc:  # pragma: no cover - environment misconfiguration
        print(json.dumps({"error": f"faster-whisper unavailable: {exc}"}))
        return 1

    _write_progress(progress_path, {"phase": "loading_model", "file": filename, "percent": 0.0})

    try:
        model = WhisperModel(model_size, device="auto", compute_type="auto")
        segments, info = model.transcribe(audio_path, vad_filter=vad_filter)
        duration = float(info.duration or 0)

        parts: list[str] = []
        last_write = 0.0
        for segment in segments:
            parts.append(segment.text)
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
        transcript = "".join(parts).strip()

        # Whisper's Chinese output script (simplified vs. traditional) is not
        # configurable and varies unpredictably between recordings even with
        # identical settings, so normalize to Taiwan-style traditional here
        # rather than storing whatever the model happened to decode.
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
    print(json.dumps({"transcript": transcript}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
