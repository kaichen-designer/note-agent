"""Live transcription progress viewer.

Reads data/transcribe_progress.json (written by _transcribe_worker.py) every
couple of seconds and renders a progress bar. Works no matter how the
pipeline was triggered (scheduled windowless run or manual run_now.bat),
because progress flows through the file, not the console. Launch via
progress.bat or: .venv\\Scripts\\python.exe src\\show_progress.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROGRESS_PATH = Path(__file__).resolve().parent.parent / "data" / "transcribe_progress.json"

# A progress file not updated for this long means no transcription is
# running (finished, crashed, or the machine rebooted mid-run).
FRESH_SECONDS = 120

BAR_WIDTH = 30


def _format_time(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


def _render(payload: dict) -> str:
    phase = payload.get("phase")
    filename = payload.get("file", "?")
    if phase == "loading_model":
        return f"載入模型中... ({filename})"
    if phase == "transcribing":
        percent = payload.get("percent", 0.0)
        done = payload.get("processed_sec", 0.0)
        total = payload.get("duration_sec", 0.0)
        filled = int(BAR_WIDTH * percent / 100)
        bar = "#" * filled + "-" * (BAR_WIDTH - filled)
        return (
            f"轉錄中: {filename}\n"
            f"進度: [{bar}] {percent:.1f}%  ({_format_time(done)} / {_format_time(total)})"
        )
    if phase == "done":
        return f"轉錄完成: {filename}(接續結構化與寫入 Notion)"
    if phase == "failed":
        return f"轉錄失敗: {filename}\n原因: {payload.get('error', '未知')}"
    return "狀態不明"


def read_status() -> str:
    """Return the current status line(s) for display."""
    if not PROGRESS_PATH.exists():
        return "目前沒有進行中的轉錄"
    try:
        payload = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "目前沒有進行中的轉錄"
    updated_at = payload.get("updated_at", 0)
    if payload.get("phase") in ("done", "failed"):
        # Terminal states stay meaningful a bit longer than in-flight ones.
        if time.time() - updated_at > FRESH_SECONDS * 5:
            return "目前沒有進行中的轉錄"
    elif time.time() - updated_at > FRESH_SECONDS:
        return "目前沒有進行中的轉錄(上次進度已過期)"
    return _render(payload)


def main() -> int:
    if "--once" in sys.argv:
        print(read_status())
        return 0
    print("轉錄進度監看中,按 Ctrl+C 離開\n")
    try:
        while True:
            status = read_status()
            # \x1b[2J\x1b[H clears the console between refreshes.
            print("\x1b[2J\x1b[H轉錄進度監看中,按 Ctrl+C 離開\n\n" + status, flush=True)
            time.sleep(2)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
