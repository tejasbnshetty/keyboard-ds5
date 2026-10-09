"""Remote settings shown on the app's Settings screen, stored under "app" in data/config.json."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields

from . import config


@dataclass
class AppSettings:
    press_ms: int = 80             # how long a tap holds the button down
    idle_timeout_min: float = 2.0  # disconnect after this long without a press (0 = never)
    safe_connect: bool = False     # wait for the PS5's own session ID (~1.5 s slower)
    repeat_delay_ms: int = 400     # hold-to-repeat: first repeat after this
    repeat_interval_ms: int = 150  # hold-to-repeat: then one press every this
    profile_hotkey: str = "F2"     # KeyboardEvent.code that cycles key-map profiles

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
        """Validate untrusted input (from the UI). Raises ValueError with a readable message."""
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
