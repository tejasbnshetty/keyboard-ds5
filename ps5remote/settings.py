# SPDX-License-Identifier: AGPL-3.0-only
"""Remote settings shown on the app's Settings screen, stored under "app" in data/config.json."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields

from . import config
from .gameinput import MouseSettings

_KEY_CODE = re.compile(r"^[A-Za-z0-9]{1,32}$")


@dataclass
class AppSettings:
    press_ms: int = 80
    idle_timeout_min: float = 2.0  # 0 = never
    safe_connect: bool = False
    repeat_delay_ms: int = 400
    repeat_interval_ms: int = 150
    profile_hotkey: str = "F2"     # a KeyboardEvent.code
    # Gaming
    mouse_toggle_key: str = "F1"   # captures / releases the mouse
    stick_hz: int = 120            # most stick updates per second sent to the PS5
    walk_tilt: float = 0.5         # left-stick tilt while the walk key is held
    light_trigger: float = 0.4     # L2/R2 press while the light-trigger key is held
    mouse_sens_x: float = 1.0
    mouse_sens_y: float = 1.0
    mouse_curve: str = "linear"
    mouse_outer_limit: float = 1.0
    mouse_anti_deadzone: float = 0.0
    mouse_smoothing_ms: int = 35
    mouse_invert_y: bool = False
    mouse_return_ms: int = 60

    LIMITS = {
        "press_ms": (20, 1000),
        "idle_timeout_min": (0, 120),
        "repeat_delay_ms": (100, 2000),
        "repeat_interval_ms": (50, 1000),
        "stick_hz": (30, 125),
        "walk_tilt": (0.1, 1.0),
        "light_trigger": (0.05, 1.0),
        "mouse_sens_x": (0.05, 20),
        "mouse_sens_y": (0.05, 20),
        "mouse_outer_limit": (0.2, 1.0),
        "mouse_anti_deadzone": (0, 0.6),
        "mouse_smoothing_ms": (20, 250),
        "mouse_return_ms": (0, 1000),
    }
    CHOICES = {"mouse_curve": ("linear", "exponential")}
    HOTKEYS = ("profile_hotkey", "mouse_toggle_key")

    @classmethod
    def load(cls) -> "AppSettings":
        saved = config.load().get("app", {})
        try:
            return cls.from_dict(saved)
        except ValueError:
            return cls()

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        """Validates untrusted input from the UI; raises ValueError with a readable message."""
        out = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            if f.type in ("int", "float"):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{f.name} must be a number")
                lo, hi = cls.LIMITS[f.name]
                if not lo <= value <= hi:
                    raise ValueError(f"{f.name} must be between {lo} and {hi}")
                value = int(value) if f.type == "int" else float(value)
            elif f.type == "bool":
                if not isinstance(value, bool):
                    raise ValueError(f"{f.name} must be true or false")
            elif f.name in cls.CHOICES:
                if value not in cls.CHOICES[f.name]:
                    raise ValueError(f"{f.name} must be one of: {', '.join(cls.CHOICES[f.name])}")
            elif f.type == "str":
                if not isinstance(value, str) or not _KEY_CODE.match(value):
                    raise ValueError(f"{f.name} must be a key name")
            setattr(out, f.name, value)
        if out.profile_hotkey == out.mouse_toggle_key:
            raise ValueError("The profile hotkey and the mouse capture key must be different keys.")
        if out.mouse_anti_deadzone >= out.mouse_outer_limit:
            raise ValueError("The anti-deadzone must be smaller than the outer limit.")
        return out

    def hotkeys(self) -> set[str]:
        """Keys the app keeps for itself: they can't be bound in a profile."""
        return {getattr(self, name) for name in self.HOTKEYS}

    def mouse(self) -> MouseSettings:
        return MouseSettings(
            sens_x=self.mouse_sens_x, sens_y=self.mouse_sens_y, curve=self.mouse_curve,
            outer_limit=self.mouse_outer_limit, anti_deadzone=self.mouse_anti_deadzone,
            smoothing_ms=self.mouse_smoothing_ms, invert_y=self.mouse_invert_y,
            return_ms=self.mouse_return_ms)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self) -> None:
        config.update(app=self.to_dict())
