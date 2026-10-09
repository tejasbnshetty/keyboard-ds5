@echo off
rem SPDX-License-Identifier: AGPL-3.0-only
rem Build the app into dist\.
rem   build.bat          personal build: bundles data\psn_client.json (Sony sign-in values)
rem   build.bat public   no sign-in values bundled (users supply their own psn_client.json)
cd /d "%~dp0"
if not exist ".venv\Scripts\pyinstaller.exe" (
    echo Run setup.bat first.
    pause
    exit /b 1
)
if not exist build mkdir build

set PS5REMOTE_PERSONAL=0
if /i "%~1"=="public" goto build
if not exist "data\psn_client.json" (
    echo No data\psn_client.json found - making a PUBLIC build without sign-in values.
    goto build
)
set PS5REMOTE_PERSONAL=1
echo Personal build: contains private PSN sign-in values. Do not distribute.> build\PERSONAL_BUILD.txt
echo.
echo ************************************************************************
echo *  PERSONAL BUILD - DO NOT DISTRIBUTE                                  *
echo *  dist\PS5Remote-personal.exe will contain the Sony sign-in values     *
echo *  from data\psn_client.json. Keep it on your own PC. Never upload it,  *
echo *  share it, or commit it.                                              *
echo ************************************************************************
echo.

:build
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --log-level WARN ps5remote.spec || goto :error
if exist build\PERSONAL_BUILD.txt del build\PERSONAL_BUILD.txt
echo.
if "%PS5REMOTE_PERSONAL%"=="1" (
    echo Built dist\PS5Remote-personal.exe   ^<-- PERSONAL, DO NOT DISTRIBUTE
) else (
    echo Built dist\PS5Remote.exe   ^(public: no sign-in values inside^)
)
echo The app keeps its data in %%APPDATA%%\PS5Remote. On first run it offers to copy an
echo existing data folder found next to the .exe or one folder up.
exit /b 0

:error
if exist build\PERSONAL_BUILD.txt del build\PERSONAL_BUILD.txt
echo Build failed - see the messages above.
pause
exit /b 1
