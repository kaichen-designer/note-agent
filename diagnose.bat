@echo off
rem One-shot pipeline health check: lock status, progress, failed files, recent log.
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" "src\diagnose.py"
pause
