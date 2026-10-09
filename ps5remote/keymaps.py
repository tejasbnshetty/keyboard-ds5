# SPDX-License-Identifier: AGPL-3.0-only
"""Input profiles for the app: each profile binds keys, mouse buttons and the wheel to actions.

Inputs are browser KeyboardEvent.code values ("ArrowUp", "Enter", "KeyP"...), which name the
physical key regardless of keyboard layout, plus Mouse0-Mouse4 (left, middle, right, back,
forward) and WheelUp / WheelDown. Actions are in gameinput.ACTIONS. One input does one
action; an action can have several inputs. The captured mouse moves the right stick in every
profile. Stored in data/keymaps.json:

  {"version": 2, "active": "Menus", "profiles": {"Menus": {
      "hold_buttons": false,   # false: taps, D-pad repeats while held; true: held like a pad
      "bindings": {"ArrowUp": "up", ...}}}}

Version 1 files ({"profiles": {"Menus": {"up": "ArrowUp", ...}}}) are converted on load.
"""
from __future__ import annotations

import copy
import json
import os
import re

from . import config
from .gameinput import ACTIONS
from .remote import BUTTONS

VERSION = 2
MAX_PROFILES = 12
MAX_BINDINGS = 64
MOUSE_INPUTS = ("Mouse0", "Mouse1", "Mouse2", "Mouse3", "Mouse4")
WHEEL_INPUTS = ("WheelUp", "WheelDown")


def keymaps_file():
    return config.DATA_DIR / "keymaps.json"  # looked up each time: the data folder can change


_PROFILE_NAME = re.compile(r"^[\w .\-+&()]{1,24}$")
_INPUT = re.compile(r"^[A-Za-z0-9]{1,24}$")


def _profile(bindings: dict, hold_buttons=False) -> dict:
    return {"hold_buttons": hold_buttons, "bindings": bindings}


DEFAULTS = {
    "version": VERSION,
    "active": "Menus",
    "profiles": {
        "Menus": _profile({
            "ArrowUp": "up", "ArrowDown": "down", "ArrowLeft": "left", "ArrowRight": "right",
            "Enter": "cross", "Backspace": "circle", "KeyT": "triangle", "KeyS": "square",
            "KeyO": "options", "KeyP": "ps", "KeyQ": "l1", "KeyE": "r1", "KeyZ": "l2", "KeyC": "r2",
        }),
        "Gaming": _profile({
            "KeyW": "ls_up", "KeyS": "ls_down", "KeyA": "ls_left", "KeyD": "ls_right",
            "AltLeft": "walk",
            "ArrowUp": "up", "ArrowDown": "down", "ArrowLeft": "left", "ArrowRight": "right",
            "Space": "cross", "KeyC": "circle", "KeyE": "square", "KeyR": "triangle",
            "ShiftLeft": "l3", "KeyV": "r3", "KeyQ": "l1", "KeyF": "r1",
            "Tab": "touchpad", "Enter": "options",
            "Mouse0": "r2", "Mouse2": "l2", "WheelUp": "r1", "WheelDown": "l1",
        }, hold_buttons=True),
    },
}


def _from_v1(mapping: dict) -> dict:
    """{button: key} -> a v2 profile."""
    bindings = {}
    for button, key in mapping.items():
        if isinstance(key, str) and key and key not in bindings:
            bindings[key] = button
    return _profile(bindings)


def validate(data: dict, reserved: set[str]) -> dict:
    """Validates untrusted key maps from the UI or disk; returns a clean v2 copy or raises
    ValueError. Version 1 profiles are converted."""
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        raise ValueError("Key maps are malformed.")
    profiles = data["profiles"]
    if not 1 <= len(profiles) <= MAX_PROFILES:
        raise ValueError(f"Have between 1 and {MAX_PROFILES} profiles.")
    clean = {"version": VERSION, "active": data.get("active"), "profiles": {}}
    for name, profile in profiles.items():
        if not isinstance(name, str) or not _PROFILE_NAME.match(name):
            raise ValueError(f"Profile name '{name}' isn't allowed (letters, numbers, spaces, max 24).")
        if not isinstance(profile, dict):
            raise ValueError(f"Profile '{name}' is malformed.")
        if "bindings" not in profile:
            profile = _from_v1(profile)
        bindings = profile.get("bindings")
        if not isinstance(bindings, dict) or len(bindings) > MAX_BINDINGS:
            raise ValueError(f"Profile '{name}' is malformed.")
        out = {}
        for key, action in bindings.items():
            if not isinstance(key, str) or not _INPUT.match(key):
                raise ValueError(f"'{key}' isn't a valid key or mouse input.")
            if action not in ACTIONS:
                raise ValueError(f"'{action}' isn't something {key} can be bound to.")
            if key in reserved:
                raise ValueError(f"{key} is reserved (a hotkey) and can't be bound to {action}.")
            if key in WHEEL_INPUTS and action not in BUTTONS:
                raise ValueError(f"The mouse wheel can only press buttons, not {action}.")
            out[key] = action
        if not isinstance(profile.get("hold_buttons", False), bool):
            raise ValueError(f"Profile '{name}': hold_buttons must be true or false.")
        # (Older files may have "mouse_stick": the captured mouse now aims in every profile.)
        clean["profiles"][name] = _profile(out, profile.get("hold_buttons", False))
    if clean["active"] not in clean["profiles"]:
        clean["active"] = next(iter(clean["profiles"]))
    return clean


def load(reserved: set[str] = frozenset()) -> dict:
    try:
        with open(keymaps_file(), encoding="utf-8") as f:
            raw = json.load(f)
        clean = validate(raw, set(reserved))
    except (OSError, ValueError, json.JSONDecodeError):
        return defaults()
    if raw.get("version") != VERSION:
        # Upgraded from version 1: add the new Gaming profile if there's room for it.
        gaming = copy.deepcopy(DEFAULTS["profiles"]["Gaming"])
        if "Gaming" not in clean["profiles"] and len(clean["profiles"]) < MAX_PROFILES and \
                not set(gaming["bindings"]) & set(reserved):
            clean["profiles"]["Gaming"] = gaming
    return clean


def save(data: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = keymaps_file()
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def defaults() -> dict:
    return copy.deepcopy(DEFAULTS)
