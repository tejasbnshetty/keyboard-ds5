@echo off
rem SPDX-License-Identifier: AGPL-3.0-only
rem Start the Keyboard DS5 window (no console). Logs go to logs\app.log.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Run setup.bat first.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m ps5remote.app
