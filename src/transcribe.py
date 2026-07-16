"""Local speech-to-text via a subprocess call into the transcription venv.

The main pipeline runs in one Python environment (see requirements.txt) while
faster-whisper runs in a separate, older-Python virtual environment (see
requirements-transcribe.txt / .venv-transcribe) because faster-whisper's
compiled dependencies may not yet support the main environment's Python
version. This module never imports faster-whisper directly; it shells out to
_transcribe_worker.py and never raises on transcription failure so the caller
can record the failure and keep processing other files.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

_WORKER_SCRIPT = Path(__file__).parent / "_transcribe_worker.py"


@dataclass
class TranscriptionResult:
    success: bool
    transcript: str | None = None
    error: str | None = None


def build_worker_command(
    venv_python: str,
    audio_path: str | Path,
    model_size: str,
    progress_path: str | Path | None,
    vad_filter: bool,
) -> list[str]:
    """Assemble the worker command line. VAD is the worker's default; only
    the opt-out flag is passed so older invocations stay compatible."""
    command = [venv_python, str(_WORKER_SCRIPT), str(audio_path), model_size]
    if progress_path is not None:
        command.append(str(progress_path))
    if not vad_filter:
        command.append("--no-vad")
    return command


def transcribe_file(
    audio_path: str | Path,
    venv_python: str | Path,
    model_size: str,
    timeout_seconds: int = 3600,
    progress_path: str | Path | None = None,
    vad_filter: bool = True,
) -> TranscriptionResult:
    """Transcribe an audio file using the local faster-whisper worker.

    Never raises: any subprocess failure, timeout, or malformed output is
    converted into a TranscriptionResult(success=False, error=...) so the
    caller can mark the file failed and continue processing other files.
    When progress_path is given, the worker writes live progress there for
    the progress viewer. VAD silence skipping is on by default; pass
    vad_filter=False to transcribe the full audio including silence.
    """
    resolved_venv_python = str(Path(venv_python).resolve())
    command = build_worker_command(
        resolved_venv_python, audio_path, model_size, progress_path, vad_filter
    )
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return TranscriptionResult(success=False, error=f"transcription timed out after {timeout_seconds}s")
    except OSError as exc:
        return TranscriptionResult(success=False, error=f"failed to launch transcription venv: {exc}")

    stdout = completed.stdout.strip()
    if not stdout:
        return TranscriptionResult(
            success=False,
            error=f"transcription worker produced no output (exit code {completed.returncode}): {completed.stderr.strip()}",
        )

    try:
        payload = json.loads(stdout.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return TranscriptionResult(success=False, error=f"could not parse worker output: {stdout}")

    if completed.returncode != 0 or "error" in payload:
        return TranscriptionResult(success=False, error=payload.get("error", "unknown transcription error"))

    return TranscriptionResult(success=True, transcript=payload.get("transcript", ""))
