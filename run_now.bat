@echo off
rem Manual trigger: run one full scan-transcribe-structure-notion cycle.
rem Uses the same src\main.py and state store as the scheduled task.
rem
rem Runs via pythonw.exe (no console attached), same as the scheduled task,
rem so closing this window mid-run can no longer kill the transcription --
rem it used to, because python.exe shares this console and gets torn down
rem with it. Watch progress.bat or diagnose.bat instead of this window.
chcp 65001 >nul
cd /d "%~dp0"
start "" /B ".venv\Scripts\pythonw.exe" "src\main.py"
echo 已在背景啟動,此視窗現在可以直接關閉,不會中斷執行。
echo 請用 progress.bat 看即時進度,或 diagnose.bat 看整體狀態。
echo.
pause
