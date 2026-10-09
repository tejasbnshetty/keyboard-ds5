@echo off
rem Build PS5Remote.exe into dist\. Run setup.bat first.
cd /d "%~dp0"
if not exist ".venv\Scripts\pyinstaller.exe" (
    echo Run setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --log-level WARN ps5remote.spec || goto :error
echo.
echo Built dist\PS5Remote.exe
echo The .exe reads its settings and pairing from a "data" folder next to it.
echo Either move PS5Remote.exe into this project folder, or copy the data folder next to it.
echo Never share the data folder: it contains your PS5 pairing keys.
exit /b 0

:error
echo Build failed - see the messages above.
pause
exit /b 1
