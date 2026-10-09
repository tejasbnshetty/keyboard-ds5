# PyInstaller build recipe. Build with build.bat (personal) or "build.bat public".
#
# The .exe keeps its data (settings, key maps, pairing) and logs in %APPDATA%\PS5Remote.
# The data\ folder is never bundled - EXCEPT data\psn_client.json in a PERSONAL build
# (PS5REMOTE_PERSONAL=1, set by build.bat). A personal build must never be distributed.
# -*- mode: python ; coding: utf-8 -*-
import os

personal = os.environ.get("PS5REMOTE_PERSONAL") == "1"
datas = [
    ("ps5remote/app/web", "web"),
    ("app_maps.json", "."),
]
if personal:
    datas += [
        ("data/psn_client.json", "."),          # Sony sign-in values (personal use only)
        ("build/PERSONAL_BUILD.txt", "."),      # makes the app show "personal build"
    ]

a = Analysis(
    ["run_app.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=["ps5remote.app.server", "webview.platforms.edgechromium", "clr"],
    excludes=["tkinter", "av", "PySide6", "pygame", "sounddevice", "OpenGL", "curses"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PS5Remote-personal" if personal else "PS5Remote",
    console=False,         # no console window
    debug=False,
    upx=False,             # UPX-packed exes trigger antivirus false positives
    runtime_tmpdir=None,
)
