@echo off
rem SPDX-License-Identifier: AGPL-3.0-only
rem One-time setup: creates the virtual environment and installs pinned dependencies.
cd /d "%~dp0"

py -3.11 --version >nul 2>&1
if errorlevel 1 (
    echo Python 3.11 was not found. Install it with:
    echo     winget install -e --id Python.Python.3.11
    echo then open a new PowerShell window and run setup.bat again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment in .venv ...
    py -3.11 -m venv .venv || goto :error
)

echo Installing dependencies ...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip || goto :error
".venv\Scripts\python.exe" -m pip install --quiet --no-deps --prefer-binary -r requirements.txt || goto :error
".venv\Scripts\python.exe" -m pip install --quiet --prefer-binary -r requirements-app.txt || goto :error

echo.
echo Setup complete. Next:  .\ps5.bat discover   (then app.bat for the window)
exit /b 0

:error
echo.
echo Setup failed - see the messages above.
pause
exit /b 1
