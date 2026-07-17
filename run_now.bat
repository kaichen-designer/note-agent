@echo off
rem Manual trigger: run one full scan-transcribe-structure-notion cycle.
rem Thin ASCII-only launcher: all real work and all user-facing messages
rem live in src\run_now.py. Keep this file free of chcp and non-ASCII
rem text -- changing the codepage mid-batch makes cmd.exe on DBCS
rem locales (cp950 etc.) lose its read position and garble every
rem following line. See the docstring in src\run_now.py.
cd /d "%~dp0"
".venv\Scripts\python.exe" "src\run_now.py"
pause
