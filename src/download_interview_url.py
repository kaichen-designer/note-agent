"""Download an interview video from a URL directly into the interview watch
folder, so the existing scan-transcribe-structure-Notion pipeline picks it
up on its next run exactly like a manually-dropped file -- no changes to
main.py's watch-folder logic are needed.

Supports whatever yt-dlp supports (YouTube, Vimeo including private
share-hash links, and many other hosts). Deferred `import yt_dlp` (not at
module top-level): yt-dlp is an optional dependency only needed by this
script, not the rest of the pipeline, so importing this module must not
require it to be installed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_ydl_opts(interview_folder: str, cookies_file: str | None = None) -> dict:
    """Build yt-dlp options that save the downloaded video directly into
    the interview watch folder, named after the video's title, as a single
    merged mp4 file (matching the extensions main.py's AUDIO_EXTENSIONS
    already recognizes).

    cookies_file is optional: some hosts (e.g. a private Vimeo share link)
    require a logged-in session. Passing a cookies.txt file (exported via a
    browser extension, since yt-dlp cannot read a browser's cookie database
    while that browser is running on Windows) lets yt-dlp authenticate as
    that user without ever handling a password."""
    opts: dict = {
        "outtmpl": str(Path(interview_folder) / "%(title)s.%(ext)s"),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
    }
    if cookies_file:
        opts["cookiefile"] = cookies_file
    return opts


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python src/download_interview_url.py <影片網址>")
        return 1

    url = sys.argv[1]
    load_dotenv(PROJECT_ROOT / ".env")
    interview_folder = os.environ.get("INTERVIEW_WATCH_FOLDER_PATH", "").strip()
    if not interview_folder:
        print(
            "尚未設定 INTERVIEW_WATCH_FOLDER_PATH,請先在 .env 設定訪談資料夾路徑"
            "(參考 config/.env.example)。"
        )
        return 1

    cookies_file = os.environ.get("YT_DLP_COOKIES_FILE", "").strip() or None

    import yt_dlp

    with yt_dlp.YoutubeDL(build_ydl_opts(interview_folder, cookies_file)) as ydl:
        ydl.download([url])

    print("下載完成,已存入訪談資料夾;下次執行 run_now.bat 或排程任務時會自動分析。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
