@echo off
rem Live transcription progress viewer. Close window or Ctrl+C to exit.
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" "src\show_progress.py"
pause
