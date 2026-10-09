"""Where local settings and secrets live, and reading/writing them.

Data folder:
  running from source:  <project>/data            logs: <project>/logs
  running as the .exe:  %APPDATA%\\PS5Remote\\data  logs: %APPDATA%\\PS5Remote\\logs
  override (testing):   set_data_dir(path) or env PS5REMOTE_DATA_DIR   logs: <path>/logs

Files in the data folder:
  config.json      PS5 address, chosen PSN user, app settings
  profiles.json    pyremoteplay profiles: PSN account ID and PS5 pairing keys
  keymaps.json     keyboard profiles
  psn_client.json  Sony sign-in values (optional, see psn.py; never committed or published)

Nothing in here is ever printed or logged.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from pyremoteplay.profile import Profiles

FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    # PyInstaller .exe: bundled files are unpacked to _MEIPASS.
    ROOT = Path(sys.executable).resolve().parent
    RESOURCES = Path(getattr(sys, "_MEIPASS", ROOT))
    USER_DIR = Path(os.environ.get("APPDATA", Path.home())) / "PS5Remote"
else:
    ROOT = Path(__file__).resolve().parent.parent
    RESOURCES = ROOT
    USER_DIR = ROOT
SOURCE_DATA_DIR = ROOT / "data"   # the data folder when running from source

DATA_DIR: Path
LOG_DIR: Path
CONFIG_FILE: Path
PROFILES_FILE: Path
CUSTOM_DATA_DIR = False


def set_data_dir(path: str | Path | None = None) -> None:
    """Point everything at another data folder (e.g. a temporary one for testing setup)."""
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
    """Load pyremoteplay profiles from our data folder instead of the library's default."""
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


# ---- moving an old data folder into %APPDATA% (first run of the .exe) ----------------------

MIGRATE_FILES = ("config.json", "profiles.json", "keymaps.json", "psn_client.json")
_DECLINED = "migration-declined"


def migration_source() -> Path | None:
    """An older data folder the .exe could copy from, if we don't have pairing data yet.
    Looks next to the .exe, and one folder up (dist\\ inside the project)."""
    if not FROZEN or CUSTOM_DATA_DIR or PROFILES_FILE.exists() or (DATA_DIR / _DECLINED).exists():
        return None
    for candidate in (ROOT / "data", ROOT.parent / "data"):
        if (candidate / "profiles.json").is_file() and candidate.resolve() != DATA_DIR:
            return candidate
    return None


def migrate_from(source: Path) -> list[str]:
    """Copy (not move) the known files. Returns the names copied."""
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
