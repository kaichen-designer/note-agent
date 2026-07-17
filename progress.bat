@echo off
rem Live transcription progress viewer. Close window or Ctrl+C to exit.
rem ASCII only, no chcp: see the docstring in src\run_now.py for why.
cd /d "%~dp0"
".venv\Scripts\python.exe" "src\show_progress.py"
pause
