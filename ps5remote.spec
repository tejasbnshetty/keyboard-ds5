# SPDX-License-Identifier: AGPL-3.0-only
# PyInstaller recipe; run build.bat.
#   Public build (default when there's no data\psn_client.json, or "build.bat public"):
#     key-free. pyremoteplay.keys, pyremoteplay.oauth and pyps4-2ndscreen are left out; the app
#     gets the PS5 key tables from the support files at first run (ps5remote/support.py), and
#     tools/check_keyfree.py verifies the output.
#   Personal build (PS5REMOTE_PERSONAL=1): the full libraries plus data\psn_client.json. Never
#     distributed, and refused in CI.
# data\ is never bundled otherwise.
# -*- mode: python ; coding: utf-8 -*-
import os

personal = os.environ.get("PS5REMOTE_PERSONAL") == "1"
if personal and (os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS")):
    raise SystemExit("Personal builds contain private sign-in values and are never made in CI.")

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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="KeyboardDS5-personal" if personal else "KeyboardDS5",
    console=False,
    debug=False,
    upx=False,             # UPX-packed exes trigger antivirus false positives
    runtime_tmpdir=None,
)
