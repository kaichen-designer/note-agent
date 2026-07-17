"""Manual trigger launcher invoked by run_now.bat.

The .bat files in this project must stay pure ASCII with no chcp call:
on DBCS-locale Windows (e.g. Traditional Chinese, cp950), cmd.exe
mis-seeks its read position in a batch file after the codepage changes
mid-run, and resumes parsing from the middle of lines -- every line
after `chcp 65001` then errors out as garbage commands. All user-facing
(Chinese) text therefore lives here in Python, which writes to the
console via the Unicode API and is immune to the codepage entirely.

Launches src/main.py under pythonw.exe (windowless, detached) so that
closing the console window cannot interrupt a transcription in
progress -- same behavior the old all-in-bat version had.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    # UTF-8 when stdout is piped/captured; no effect on a real console,
    # which Python drives through the Unicode console API anyway.
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHONW = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
MAIN_SCRIPT = PROJECT_ROOT / "src" / "main.py"


def build_command() -> list[str]:
    return [str(PYTHONW), str(MAIN_SCRIPT)]


def main() -> int:
    if not PYTHONW.exists():
        print(f"找不到 {PYTHONW}")
        print("請確認主虛擬環境 .venv 已建立(參考 README 的安裝步驟)。")
        return 1

    subprocess.Popen(
        build_command(),
        cwd=str(PROJECT_ROOT),
        creationflags=subprocess.DETACHED_PROCESS,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("已在背景啟動,此視窗現在可以直接關閉,不會中斷執行。")
    print("請用 progress.bat 看即時進度,或 diagnose.bat 看整體狀態。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
