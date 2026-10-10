# SPDX-License-Identifier: AGPL-3.0-only
# PyInstaller recipe; run build.bat.
#   Public build (default when there's no data\psn_client.json, or "build.bat public"):
#     key-free, one-folder (dist\KeyboardDS5\). pyremoteplay.keys, pyremoteplay.oauth and
#     pyps4-2ndscreen are left out; the app gets the PS5 key tables at first run
#     (ps5remote/support.py), and tools/check_keyfree.py verifies the output.
#   Personal build (PS5REMOTE_PERSONAL=1): one file, the full libraries plus
#     data\psn_client.json. Never distributed, and refused in CI.
# data\ is never bundled otherwise.
# -*- mode: python ; coding: utf-8 -*-
import os
import re

from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct,
                                                 StringTable, VarFileInfo, VarStruct, VSVersionInfo)

personal = os.environ.get("PS5REMOTE_PERSONAL") == "1"
if personal and (os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS")):
    raise SystemExit("Personal builds contain private sign-in values and are never made in CI.")

with open("ps5remote/__init__.py", encoding="utf-8") as f:
    VERSION = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)"', f.read()).groups()
name = "KeyboardDS5-personal" if personal else "KeyboardDS5"
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=(*map(int, VERSION), 0), prodvers=(*map(int, VERSION), 0)),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Tejas Shetty and contributors"),
            StringStruct("FileDescription", "Keyboard DS5"),
            StringStruct("FileVersion", ".".join(VERSION)),
            StringStruct("InternalName", name),
            StringStruct("LegalCopyright",
                         "Copyright (c) 2026 Tejas Shetty and contributors. AGPL-3.0-only."),
            StringStruct("OriginalFilename", f"{name}.exe"),
            StringStruct("ProductName", "Keyboard DS5"),
            StringStruct("ProductVersion", ".".join(VERSION)),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

datas = [
    ("ps5remote/app/web", "web"),
    ("app_maps.json", "."),
]
excludes = ["tkinter", "av", "PySide6", "pygame", "sounddevice", "OpenGL", "curses"]
runtime_hooks = []
if personal:
    datas += [
        ("data/psn_client.json", "."),          # Sony sign-in values (personal use only)
        ("build/PERSONAL_BUILD.txt", "."),      # makes the app show "personal build"
    ]
else:
    # Key-free: no Sony key tables, sign-in credentials or PS4 Second Screen key material.
    excludes += ["pyremoteplay.keys", "pyremoteplay.oauth", "pyremoteplay.__main__",
                 "pyps4_2ndscreen"]
    runtime_hooks += ["tools/pyi_rth_keyfree.py"]

a = Analysis(
    ["run_app.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=["ps5remote.app.server", "ps5remote.keyfree", "ps5remote.support",
                   "webview.platforms.edgechromium", "clr"],
    excludes=excludes,
    runtime_hooks=runtime_hooks,
    noarchive=False,
)
pyz = PYZ(a.pure)

common = dict(
    name=name,
    console=False,
    debug=False,
    upx=False,             # UPX-packed exes trigger antivirus false positives
    icon="assets/keyboardds5.ico",
    version=version_info,
)

if personal:
    # One file, as before.
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], runtime_tmpdir=None, **common)
else:
    # One folder: starts faster than one file (nothing unpacked to %TEMP% at each launch) and
    # is less likely to be flagged by antivirus heuristics. Zipped for release.
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="KeyboardDS5")
