@echo off
rem Start the PS5 Remote window (no console). Logs go to logs\app.log.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Run setup.bat first.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m ps5remote.app
