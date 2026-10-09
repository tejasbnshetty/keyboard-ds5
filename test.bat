@echo off
rem SPDX-License-Identifier: AGPL-3.0-only
rem Run the offline test suite (no PS5 or network needed). Extra arguments go to pytest.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.bat first.
    exit /b 1
)
".venv\Scripts\python.exe" -m pytest %*
