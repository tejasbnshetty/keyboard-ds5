# SPDX-License-Identifier: AGPL-3.0-only
"""Gaming input: turns held keys / mouse buttons and mouse movement into controller state.

Actions (what a key, mouse button or wheel step can be bound to):
- a button name from remote.BUTTONS: held down while the input is held (in a gaming profile)
- "ls_up" / "ls_down" / "ls_left" / "ls_right" (and "rs_..."): push a stick fully that way;
  two directions together give a normalised diagonal
- "walk": while held, the left stick only tilts by walk_tilt
- "light_trigger": while held, L2/R2 press only by light_trigger

Mouse movement (while captured) drives the right stick: speed, not position, sets the tilt.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass

from .gamepad import ANALOG, CENTRE, Stick
from .remote import BUTTONS

STICK_DIRS = {
    "ls_up": ("left", 0, -1), "ls_down": ("left", 0, 1),
    "ls_left": ("left", -1, 0), "ls_right": ("left", 1, 0),
    "rs_up": ("right", 0, -1), "rs_down": ("right", 0, 1),
    "rs_left": ("right", -1, 0), "rs_right": ("right", 1, 0),
}
MODIFIERS = ("walk", "light_trigger")
ACTIONS = tuple(BUTTONS) + tuple(STICK_DIRS) + MODIFIERS

FULL_TILT_SPEED = 2000.0   # mouse counts per second for full tilt at sensitivity 1.0
EXPO = 2.0                 # "exponential" curve: tilt = speed ** EXPO (on 0..1)


@dataclass
class MouseSettings:
    sens_x: float = 1.0
    sens_y: float = 1.0
    curve: str = "linear"          # or "exponential"
    outer_limit: float = 1.0       # most the stick ever tilts (0..1)
    anti_deadzone: float = 0.0     # least tilt for any movement (0..1)
    smoothing_ms: float = 35.0     # movement is averaged over this long
    invert_y: bool = False
    return_ms: float = 60.0        # time to fall back to centre once the mouse stops


def key_stick(dirs: set[tuple[int, int]], scale: float = 1.0) -> Stick:
    """Held directions -> stick position; diagonals have length 1 (times scale)."""
    x = sum(d[0] for d in dirs)
    y = sum(d[1] for d in dirs)
    x, y = max(-1, min(1, x)), max(-1, min(1, y))
    length = math.hypot(x, y)
    if not length:
        return CENTRE
    return (x / length * scale, y / length * scale)


class MouseStick:
    """Mouse movement -> right-stick tilt.

    Each mouse report is spread over the time since the previous one. Speed is the movement
    in the smoothing_ms before the latest report, divided by smoothing_ms, so a steady hand
    gives a steady tilt even though reports (~60/s) and stick updates (~120/s) don't line
    up. That speed (per-axis sensitivity) is shaped by the curve, then mapped into
    [anti_deadzone, outer_limit] keeping its direction. Once reports stop for longer than
    the window, the tilt falls to centre over return_ms."""

    MIN_WINDOW = 0.02     # browsers report movement ~60 times a second: don't average less
    FIRST_SPAN = 1 / 60   # a report after a pause is taken to cover one typical interval
    MAX_SPAN = 0.05       # longer gaps than this are a pause, not slow movement

    def __init__(self, settings: MouseSettings | None = None):
        self.settings = settings or MouseSettings()
        self._moves: deque[tuple[float, float, float, float]] = deque()  # (start, end, dx, dy)
        self._last: float | None = None
        self.value: Stick = CENTRE

    def add(self, dx: float, dy: float, now: float) -> None:
        if not (dx or dy):
            return
        prev = self._moves[-1][1] if self._moves else None
        start = prev if prev is not None and 0 < now - prev <= self.MAX_SPAN else now - self.FIRST_SPAN
        self._moves.append((start, now, dx, dy))

    def reset(self) -> None:
        self._moves.clear()
        self.value = CENTRE

    def tick(self, now: float) -> Stick:
        s = self.settings
        dt = 0.0 if self._last is None else max(0.0, now - self._last)
        self._last = now
        window = max(self.MIN_WINDOW, s.smoothing_ms / 1000)
        while self._moves and self._moves[0][1] < now - window - self.MAX_SPAN:
            self._moves.popleft()
        if not self._moves or now - self._moves[-1][1] > window:
            self.value = self._fall(dt)
            return self.value
        end = self._moves[-1][1]
        begin = end - window
        dx = dy = 0.0
        for start, stop, mx, my in self._moves:
            overlap = min(stop, end) - max(start, begin)
            if overlap > 0:
                part = overlap / (stop - start)
                dx += mx * part
                dy += my * part
        self.value = self._shape(dx / window, dy / window)
        return self.value

    def _shape(self, vx: float, vy: float) -> Stick:
        s = self.settings
        tx = vx * s.sens_x / FULL_TILT_SPEED
        ty = vy * s.sens_y / FULL_TILT_SPEED * (-1 if s.invert_y else 1)
        size = math.hypot(tx, ty)
        if size < 1e-6:
            return CENTRE
        m = min(1.0, size)
        if s.curve == "exponential":
            m = m ** EXPO
        out = s.anti_deadzone + (s.outer_limit - s.anti_deadzone) * m
        return (tx / size * out, ty / size * out)

    def _fall(self, dt: float) -> Stick:
        x, y = self.value
        size = math.hypot(x, y)
        if not size:
            return CENTRE
        if self.settings.return_ms <= 0:
            return CENTRE
        new = size - dt / (self.settings.return_ms / 1000)
        if new <= 0:
            return CENTRE
        return (x / size * new, y / size * new)


class GameInput:
    """Held actions + mouse -> (buttons, left stick, right stick)."""

    def __init__(self, mouse: MouseSettings | None = None, walk_tilt: float = 0.5,
                 light_trigger: float = 0.4):
        self.mouse = MouseStick(mouse)
        self.walk_tilt = walk_tilt
        self.light_trigger = light_trigger
        self.held: dict[str, int] = {}  # action -> how many inputs hold it
        self.captured = False

    def set(self, action: str, down: bool) -> None:
        if action not in ACTIONS:
            raise ValueError(f"Unknown action {action!r}")
        count = self.held.get(action, 0) + (1 if down else -1)
        if count > 0:
            self.held[action] = count
        else:
            self.held.pop(action, None)

    def add_mouse(self, dx: float, dy: float, now: float | None = None) -> None:
        if self.captured:
            self.mouse.add(dx, dy, time.monotonic() if now is None else now)

    def set_captured(self, on: bool) -> None:
        self.captured = on
        if not on:
            self.mouse.reset()

    def neutral(self) -> None:
        """Release everything and centre both sticks."""
        self.held.clear()
        self.mouse.reset()

    def tick(self, now: float | None = None) -> None:
        self.mouse.tick(time.monotonic() if now is None else now)

    def buttons(self) -> dict[str, int]:
        light = "light_trigger" in self.held
        out = {}
        for action in self.held:
            if action in BUTTONS:
                out[action] = round(255 * self.light_trigger) if light and action in ANALOG else 255
        return out

    def sticks(self) -> tuple[Stick, Stick]:
        dirs = {"left": set(), "right": set()}
        for action in self.held:
            if action in STICK_DIRS:
                stick, x, y = STICK_DIRS[action]
                dirs[stick].add((x, y))
        left = key_stick(dirs["left"], self.walk_tilt if "walk" in self.held else 1.0)
        right = key_stick(dirs["right"])
        if right == CENTRE:
            right = self.mouse.value
        return left, right

    @property
    def is_neutral(self) -> bool:
        return not self.held and self.mouse.value == CENTRE
