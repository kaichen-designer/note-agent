"""One-shot pipeline health check.

Answers "why is nothing being transcribed right now" without having to read
pipeline.log by hand: lock ownership (and whether it's orphaned by a dead
process), current transcription progress, the tail of the log, and any file
stuck in a failed / needs-manual-intervention state. Launch via
diagnose.bat or: .venv\\Scripts\\python.exe src\\diagnose.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    # Force UTF-8 regardless of the invoking console's codepage: Windows
    # falls back to a legacy codepage (mangling the Chinese log output)
    # whenever stdout isn't attached to a real chcp 65001 console, e.g.
    # when piped/captured by another tool.
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from show_progress import read_status  # noqa: E402
from state_store import FAILED, NEEDS_MANUAL_INTERVENTION, StateStore  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOCK_PATH = DATA_DIR / "pipeline.lock"
LOG_PATH = DATA_DIR / "pipeline.log"
STATE_PATH = DATA_DIR / "state.json"

# Keep in sync with LOCK_STALE_SECONDS in main.py: the pipeline only takes
# over a lock on its own after this long, so anything younger than this
# needs a human to confirm it's actually orphaned before deleting it.
LOCK_STALE_SECONDS = 4 * 60 * 60

LOG_TAIL_LINES = 20


def _pid_alive(pid: int) -> bool:
    """Check whether a PID is a live process on Windows via tasklist, since
    os.kill's signal-0 liveness check isn't available on this platform."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return True  # can't determine -> assume alive, don't suggest deleting
    return str(pid) in out


def _format_age(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} 分鐘"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小時 {minutes} 分鐘"


def check_lock() -> str:
    if not LOCK_PATH.exists():
        return "[鎖檔] 沒有鎖檔,目前沒有實例在執行"

    age = time.time() - LOCK_PATH.stat().st_mtime
    raw_pid = LOCK_PATH.read_text(encoding="utf-8").strip()
    try:
        pid = int(raw_pid)
    except ValueError:
        return f"[鎖檔] 鎖檔內容無法解析為 PID(內容: {raw_pid!r}),已存在 {_format_age(age)}"

    if _pid_alive(pid):
        return f"[鎖檔] 使用中,PID {pid} 存活中(正常執行,已持續 {_format_age(age)})"

    remaining = LOCK_STALE_SECONDS - age
    auto_note = (
        f"還要 {_format_age(remaining)} 才會被自動判定為過期並接管"
        if remaining > 0
        else "已超過 4 小時,下一輪排程會自動接管"
    )
    return (
        f"[鎖檔] ⚠️ 孤兒鎖!PID {pid} 已不存在,鎖已存在 {_format_age(age)}。\n"
        f"       這代表上次執行意外中斷(例如視窗被關閉),排程會一直判定「另一個實例正在處理」而跳過。\n"
        f"       {auto_note}。可安全刪除 data/pipeline.lock 讓排程立即恢復。"
    )


def check_progress() -> str:
    return f"[轉錄進度] {read_status()}"


def check_log_tail() -> str:
    if not LOG_PATH.exists():
        return "[最近日誌] 尚無日誌"
    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-LOG_TAIL_LINES:]
    return "[最近日誌]\n" + "\n".join(f"  {line}" for line in tail)


def check_problem_files() -> str:
    if not STATE_PATH.exists():
        return "[需要留意的檔案] 無(尚無狀態紀錄)"
    store = StateStore(STATE_PATH)
    problems = [
        record
        for record in store.all_records()
        if record.status in (FAILED, NEEDS_MANUAL_INTERVENTION)
    ]
    if not problems:
        return "[需要留意的檔案] 無"
    lines = ["[需要留意的檔案]"]
    for record in problems:
        label = "需人工介入" if record.status == NEEDS_MANUAL_INTERVENTION else "失敗(將自動重試)"
        lines.append(
            f"  - {record.file_id}: {label},重試 {record.retry_count} 次"
            f"\n    原因: {record.failure_reason or '未知'}"
        )
    return "\n".join(lines)


def main() -> int:
    sections = [check_lock(), check_progress(), check_problem_files(), check_log_tail()]
    print("=== 錄音筆記 Agent 診斷 ===\n")
    print("\n\n".join(sections))
    return 0


if __name__ == "__main__":
    sys.exit(main())
