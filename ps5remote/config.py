# SPDX-License-Identifier: AGPL-3.0-only
"""Local settings and secrets.

Data folder: <project>/data from source, %APPDATA%\\KeyboardDS5\\data as the .exe, or
set_data_dir() / env PS5REMOTE_DATA_DIR. It holds config.json (PS5 address, user, settings),
profiles.json (account ID and pairing keys), keymaps.json and optionally psn_client.json.
The .exe used %APPDATA%\\PS5Remote before the rename: it offers to copy that (never moves it).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyremoteplay.profile import Profiles

# pyremoteplay is imported lazily (in profiles()): the key-free build must install its import
# finder (keyfree.install) after reading the data folder here, before pyremoteplay loads.

FROZEN = bool(getattr(sys, "frozen", False))
APPDATA = Path(os.environ.get("APPDATA", Path.home()))
LEGACY_USER_DIR = APPDATA / "PS5Remote"   # the .exe's folder before the rename
if FROZEN:
    # PyInstaller .exe: bundled files are unpacked to _MEIPASS.
    ROOT = Path(sys.executable).resolve().parent
    RESOURCES = Path(getattr(sys, "_MEIPASS", ROOT))
    USER_DIR = APPDATA / "KeyboardDS5"
    SOURCE_DATA_DIR: Path | None = None
else:
    ROOT = Path(__file__).resolve().parent.parent
    RESOURCES = ROOT
    USER_DIR = ROOT
    SOURCE_DATA_DIR = ROOT / "data"   # also read for psn_client.json, so --data-dir runs sign in

DATA_DIR: Path
LOG_DIR: Path
CONFIG_FILE: Path
PROFILES_FILE: Path
CUSTOM_DATA_DIR = False


def set_data_dir(path: str | Path | None = None) -> None:
    """Use another data folder (e.g. a temporary one for testing)."""
    global DATA_DIR, LOG_DIR, CONFIG_FILE, PROFILES_FILE, CUSTOM_DATA_DIR  # pylint: disable=global-statement
    if path:
        DATA_DIR = Path(path).resolve()
        LOG_DIR = DATA_DIR / "logs"
        CUSTOM_DATA_DIR = True
    else:
        DATA_DIR = USER_DIR / "data"
        LOG_DIR = USER_DIR / "logs"
        CUSTOM_DATA_DIR = False
    CONFIG_FILE = DATA_DIR / "config.json"
    PROFILES_FILE = DATA_DIR / "profiles.json"


set_data_dir(os.environ.get("PS5REMOTE_DATA_DIR") or None)


def resource(name: str) -> Path:
    """A file the user may edit (e.g. app_maps.json): prefer their own copy."""
    local = USER_DIR / name
    return local if local.exists() else RESOURCES / name


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load() -> dict:
    if not CONFIG_FILE.is_file():
        return {}
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def save(cfg: dict) -> None:
    _ensure_dir()
    tmp = CONFIG_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_FILE)


def update(**values) -> dict:
    cfg = load()
    cfg.update(values)
    save(cfg)
    return cfg


def remove_keys(*keys: str) -> None:
    cfg = load()
    for key in keys:
        cfg.pop(key, None)
    save(cfg)


def profiles() -> Profiles:
    """pyremoteplay profiles from our data folder, not the library's default."""
    from pyremoteplay.profile import Profiles  # pylint: disable=import-outside-toplevel
    _ensure_dir()
    Profiles.set_default_path(str(PROFILES_FILE))
    return Profiles.load(str(PROFILES_FILE))


def save_profiles(p: Profiles) -> None:
    # Always pass the path: Profiles.save() without one writes to ~/.pyremoteplay instead.
    _ensure_dir()
    p.save(str(PROFILES_FILE))


def is_paired() -> bool:
    """A PS5 address, a signed-in user, and pairing keys for that user."""
    cfg = load()
    user = cfg.get("psn_user")
    if not cfg.get("ps5_host") or not user or not PROFILES_FILE.is_file():
        return False
    try:
        data = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(data.get(user, {}).get("hosts"))


MIGRATE_FILES = ("config.json", "profiles.json", "keymaps.json", "psn_client.json")
_DECLINED = "migration-declined"


def migration_candidates() -> tuple[Path, ...]:
    """Where an older data folder may be, most likely first: the pre-rename %APPDATA% folder,
    then next to the .exe, one folder up, or two up (the one-folder build is
    dist\\KeyboardDS5\\KeyboardDS5.exe inside the project, whose data\\ is two levels up)."""
    return (LEGACY_USER_DIR / "data", ROOT / "data", ROOT.parent / "data",
            ROOT.parent.parent / "data")


def migration_source() -> Path | None:
    """An older data folder for the .exe to offer copying. The user is always asked first."""
    if not FROZEN or CUSTOM_DATA_DIR or PROFILES_FILE.exists() or (DATA_DIR / _DECLINED).exists():
        return None
    for candidate in migration_candidates():
        if (candidate / "profiles.json").is_file() and candidate.resolve() != DATA_DIR:
            return candidate
    return None


def migrate_from(source: Path) -> list[str]:
    """Copies (doesn't move) the known files."""
    _ensure_dir()
    copied = []
    for name in MIGRATE_FILES:
        if (source / name).is_file():
            shutil.copy2(source / name, DATA_DIR / name)
            copied.append(name)
    return copied


def decline_migration() -> None:
    _ensure_dir()
    (DATA_DIR / _DECLINED).write_text("The user chose not to copy an older data folder.\n")
