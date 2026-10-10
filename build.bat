@echo off
rem SPDX-License-Identifier: AGPL-3.0-only
rem Build the app into dist\.
rem   build.bat          personal build if data\psn_client.json exists: the full libraries plus
rem                      your sign-in values. For your own PC only; never distribute it.
rem   build.bat public   key-free public build in dist\KeyboardDS5\ (one folder), packaged by
rem                      tools\package_release.py: licences and notices added, checked for Sony
rem                      key material (tools\check_keyfree.py), zipped with a SHA-256.
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
    echo No data\psn_client.json found - making the key-free PUBLIC build.
    goto build
)
set PS5REMOTE_PERSONAL=1
echo Personal build: contains private PSN sign-in values. Do not distribute.> build\PERSONAL_BUILD.txt
echo.
echo ************************************************************************
echo *  PERSONAL BUILD - DO NOT DISTRIBUTE                                  *
echo *  dist\KeyboardDS5-personal.exe will contain the Sony sign-in values  *
echo *  from data\psn_client.json and the Remote Play key tables. Keep it   *
echo *  on your own PC. Never upload it, share it, or commit it.            *
echo ************************************************************************
echo.

:build
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --log-level WARN ps5remote.spec || goto :error
if exist build\PERSONAL_BUILD.txt del build\PERSONAL_BUILD.txt
echo.
if "%PS5REMOTE_PERSONAL%"=="1" (
    echo Built dist\KeyboardDS5-personal.exe   ^<-- PERSONAL, DO NOT DISTRIBUTE
    goto done
)
echo Adding licences and notices, checking for Sony key material, and zipping...
".venv\Scripts\python.exe" tools\package_release.py dist\KeyboardDS5 --out dist || goto :error
echo Built dist\KeyboardDS5\ and its release zip in dist\   ^(public, key-free^)

:done
echo The app keeps its data in %%APPDATA%%\KeyboardDS5. On first run it asks before copying
echo older data (%%APPDATA%%\PS5Remote, or a data folder next to the .exe or one folder up).
exit /b 0

:error
if exist build\PERSONAL_BUILD.txt del build\PERSONAL_BUILD.txt
echo Build failed - see the messages above.
pause
exit /b 1
