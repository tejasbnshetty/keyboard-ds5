# SPDX-License-Identifier: AGPL-3.0-only
"""Remote settings shown on the app's Settings screen, stored under "app" in data/config.json."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields

from . import config


@dataclass
class AppSettings:
    press_ms: int = 80
    idle_timeout_min: float = 2.0  # 0 = never
    safe_connect: bool = False
    repeat_delay_ms: int = 400
    repeat_interval_ms: int = 150
    profile_hotkey: str = "F2"     # a KeyboardEvent.code

    LIMITS = {
        "press_ms": (20, 1000),
        "idle_timeout_min": (0, 120),
        "repeat_delay_ms": (100, 2000),
        "repeat_interval_ms": (50, 1000),
    }

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
            elif f.type == "str":
                if not isinstance(value, str) or not 1 <= len(value) <= 32:
                    raise ValueError(f"{f.name} must be a key name")
            setattr(out, f.name, value)
        return out

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self) -> None:
        config.update(app=self.to_dict())
