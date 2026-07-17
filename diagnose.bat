@echo off
rem One-shot pipeline health check: lock status, progress, failed files, recent log.
rem ASCII only, no chcp: see the docstring in src\run_now.py for why.
cd /d "%~dp0"
".venv\Scripts\python.exe" "src\diagnose.py"
pause
