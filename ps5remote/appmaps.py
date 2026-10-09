# SPDX-License-Identifier: AGPL-3.0-only
"""Per-app information from app_maps.json: Watch-mode button maps (benched) and the list of
streaming apps, used by the Windows app to warn that connecting blacks out their video."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

from . import config, ps5
from .remote import check_button


@dataclass
class AppMap:
    key: str
    name: str
    play_pause: str
    back: str
    forward: str
    home: str
    seek_seconds: int
    match: list[str] = field(default_factory=list)
    title_ids: list[str] = field(default_factory=list)
    verified: dict = field(default_factory=dict)

    def seek_presses(self, seconds: int) -> int:
        return max(1, math.ceil(seconds / self.seek_seconds))

    def matches(self, running_name: str, title_id: str = "") -> bool:
        if title_id and title_id in self.title_ids:
            return True
        return bool(running_name) and any(
            re.search(rf"\b{re.escape(t)}\b", running_name, re.I) for t in self.match)


def load_app_maps() -> tuple[dict[str, AppMap], str]:
    with open(config.resource("app_maps.json"), encoding="utf-8") as f:
        raw = json.load(f)
    maps = {}
    for key, entry in raw["apps"].items():
        m = AppMap(key=key, name=entry.get("name", key),
                   play_pause=entry["play_pause"], back=entry["back"],
                   forward=entry["forward"], home=entry.get("home", "ps"),
                   seek_seconds=int(entry.get("seek_seconds", 10)),
                   match=entry.get("match", []), title_ids=entry.get("title_ids", []),
                   verified=entry.get("verified", {}))
        for button in (m.play_pause, m.back, m.forward, m.home):
            check_button(button)
        maps[key] = m
    default = raw.get("default", next(iter(maps)))
    return maps, default


def find_streaming_app(status: dict) -> AppMap | None:
    """The app_maps.json entry matching the PS5's running app, or None."""
    running = (status.get("running-app-name") or "").strip()
    title_id = (status.get("running-app-titleid") or "").strip()
    if not running and not title_id:
        return None
    maps, _ = load_app_maps()
    return next((m for m in maps.values() if m.matches(running, title_id)), None)


def pick_app_map(setting: str, status: dict) -> tuple[AppMap, str]:
    """Return (map, how it was chosen) for Watch mode."""
    maps, default = load_app_maps()
    if setting != "auto":
        if setting not in maps:
            raise ps5.PS5Error(f"No app map called '{setting}'. Choose from: {', '.join(maps)}")
        return maps[setting], "set in settings"
    found = find_streaming_app(status)
    running = (status.get("running-app-name") or "").strip()
    if found:
        return found, f"running app '{running or status.get('running-app-titleid')}'"
    reason = f"running app '{running}' not recognised" if running else "no running app reported"
    return maps[default], f"{reason}, using default"
