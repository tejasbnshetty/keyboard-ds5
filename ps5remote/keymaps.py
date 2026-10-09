"""Keyboard profiles for the app: each profile maps PS5 buttons to keys.

Keys are browser KeyboardEvent.code values ("ArrowUp", "Enter", "KeyP"...), which name the
physical key regardless of keyboard layout. Stored in data/keymaps.json:
  {"active": "Menus", "profiles": {"Menus": {"up": "ArrowUp", ...}, "Games": {...}}}
"""
from __future__ import annotations

import copy
import json
import os
import re

from . import config
from .remote import BUTTONS

MAX_PROFILES = 12


def keymaps_file():
    return config.DATA_DIR / "keymaps.json"  # looked up each time: the data folder can change
_PROFILE_NAME = re.compile(r"^[\w .\-+&()]{1,24}$")
_KEY_CODE = re.compile(r"^[A-Za-z0-9]{1,24}$")

DEFAULTS = {
    "active": "Menus",
    "profiles": {
        # Same keys as the command-line remote.
        "Menus": {
            "up": "ArrowUp", "down": "ArrowDown", "left": "ArrowLeft", "right": "ArrowRight",
            "cross": "Enter", "circle": "Backspace", "triangle": "KeyT", "square": "KeyS",
            "options": "KeyO", "ps": "KeyP", "l1": "KeyQ", "r1": "KeyE", "l2": "KeyZ", "r2": "KeyC",
        },
        # Left hand on WASD, right hand on IJKL for the face buttons.
        "Games": {
            "up": "KeyW", "down": "KeyS", "left": "KeyA", "right": "KeyD",
            "cross": "KeyK", "circle": "KeyL", "triangle": "KeyI", "square": "KeyJ",
            "options": "Enter", "ps": "Escape", "l1": "KeyQ", "r1": "KeyE", "l2": "Digit1", "r2": "Digit3",
        },
    },
}


def conflicts(profile: dict[str, str]) -> dict[str, list[str]]:
    """Keys bound to more than one button: {key: [buttons]}."""
    by_key: dict[str, list[str]] = {}
    for button, key in profile.items():
        if key:
            by_key.setdefault(key, []).append(button)
    return {k: v for k, v in by_key.items() if len(v) > 1}


def validate(data: dict, reserved: set[str]) -> dict:
    """Check untrusted keymaps from the UI. Returns a clean copy or raises ValueError."""
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        raise ValueError("Key maps are malformed.")
    profiles = data["profiles"]
    if not 1 <= len(profiles) <= MAX_PROFILES:
        raise ValueError(f"Have between 1 and {MAX_PROFILES} profiles.")
    clean = {"active": data.get("active"), "profiles": {}}
    for name, mapping in profiles.items():
        if not isinstance(name, str) or not _PROFILE_NAME.match(name):
            raise ValueError(f"Profile name '{name}' isn't allowed (letters, numbers, spaces, max 24).")
        if not isinstance(mapping, dict):
            raise ValueError(f"Profile '{name}' is malformed.")
        out = {}
        for button in BUTTONS:
            key = mapping.get(button, "")
            if key and (not isinstance(key, str) or not _KEY_CODE.match(key)):
                raise ValueError(f"'{key}' isn't a valid key for {button}.")
            if key in reserved:
                raise ValueError(f"{key} is reserved (profile hotkey) and can't be bound to {button}.")
            out[button] = key
        clash = conflicts(out)
        if clash:
            key, buttons = next(iter(clash.items()))
            raise ValueError(f"In '{name}', {key} is bound to both {' and '.join(buttons)}.")
        clean["profiles"][name] = out
    if clean["active"] not in clean["profiles"]:
        clean["active"] = next(iter(clean["profiles"]))
    return clean


def load(reserved: set[str] = frozenset()) -> dict:
    try:
        with open(keymaps_file(), encoding="utf-8") as f:
            return validate(json.load(f), set(reserved))
    except (OSError, ValueError, json.JSONDecodeError):
        return defaults()


def save(data: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = keymaps_file()
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def defaults() -> dict:
    return copy.deepcopy(DEFAULTS)
