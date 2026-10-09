@echo off
rem SPDX-License-Identifier: AGPL-3.0-only
rem Command-line tool. Examples:  ps5.bat discover   ps5.bat status   ps5.bat wake
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.bat first.
    exit /b 1
)
".venv\Scripts\python.exe" -m ps5remote %*
