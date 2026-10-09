# PyInstaller build recipe for PS5Remote.exe. Build with build.bat.
# The .exe keeps its data (data\ folder: settings, key maps, pairing) and logs next to itself.
# Never put the data\ folder inside the build: it holds your pairing keys.
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["run_app.py"],
    pathex=["."],
    datas=[
        ("ps5remote/app/web", "web"),
        ("app_maps.json", "."),
    ],
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
    name="PS5Remote",
    console=False,         # no console window
    debug=False,
    upx=False,             # UPX-packed exes trigger antivirus false positives
    runtime_tmpdir=None,
)
