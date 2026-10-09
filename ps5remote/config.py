"""Local settings and secrets, stored in the gitignored data/ folder.

data/config.json   - PS5 address, chosen PSN user, server settings
data/profiles.json - pyremoteplay profiles: PSN account ID and PS5 pairing keys

Nothing in here is ever printed or logged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from pyremoteplay.profile import Profiles

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_FILE = DATA_DIR / "config.json"
PROFILES_FILE = DATA_DIR / "profiles.json"


def _ensure_dir() -> None:
    DATA_DIR.mkdir(exist_ok=True)


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


def profiles() -> Profiles:
    """Load pyremoteplay profiles from data/ instead of the library's default (~/.pyremoteplay)."""
    _ensure_dir()
    Profiles.set_default_path(str(PROFILES_FILE))
    return Profiles.load(str(PROFILES_FILE))


def save_profiles(p: Profiles) -> None:
    # Always pass the path: Profiles.save() without one writes to ~/.pyremoteplay instead.
    _ensure_dir()
    p.save(str(PROFILES_FILE))
