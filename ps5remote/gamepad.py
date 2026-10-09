# SPDX-License-Identifier: AGPL-3.0-only
"""Sends controller state to the PS5: buttons (with analog L2/R2) and both sticks.

Replaces pyremoteplay's Controller for sending (its worker thread would share the stream
cipher with our event-loop sends, and it can only press L2/R2 fully). Everything here runs
on the event loop.

Wire format, looked up in chiaki-ng feedback.c / feedbacksender.c:
- Button event: 0x80, id, value (0-255; L2/R2 analog). Options, Share, PS, L3, R3 and
  Touchpad are two bytes: 0x80, id (+0x20 while pressed).
- Each event packet carries the most recent events, newest first, so a lost packet is
  recovered by the next one.
- Stick state is sent when it changes (at most every MIN_STATE_INTERVAL) and resent at
  least every MAX_STATE_INTERVAL.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable

from pyremoteplay.stream_packets import ControllerState, FeedbackHeader

BUTTON_IDS = {
    "up": 0x80, "down": 0x81, "left": 0x82, "right": 0x83,
    "l1": 0x84, "r1": 0x85, "l2": 0x86, "r2": 0x87,
    "cross": 0x88, "circle": 0x89, "square": 0x8A, "triangle": 0x8B,
}
SHORT_BUTTON_IDS = {"options": 0x8C, "share": 0x8D, "ps": 0x8E, "l3": 0x8F, "r3": 0x90, "touchpad": 0x91}
ANALOG = {"l2", "r2"}
HISTORY = 16
MIN_STATE_INTERVAL = 0.008   # ~125 Hz
MAX_STATE_INTERVAL = 0.200

Stick = tuple[float, float]
CENTRE: Stick = (0.0, 0.0)


def encode_event(button: str, value: int) -> bytes:
    """value: 0 released, 1-255 pressed (only L2/R2 use values below 255)."""
    if button in SHORT_BUTTON_IDS:
        return bytes([0x80, SHORT_BUTTON_IDS[button] + (0x20 if value else 0)])
    if button not in BUTTON_IDS:
        raise ValueError(f"Unknown button {button!r}")
    if button not in ANALOG and value:
        value = 0xFF
    return bytes([0x80, BUTTON_IDS[button], max(0, min(0xFF, value))])


def clamp_stick(stick: Stick) -> Stick:
    return (max(-1.0, min(1.0, float(stick[0]))), max(-1.0, min(1.0, float(stick[1]))))


class PadSender:
    """Diffs the wanted controller state against what the PS5 last got, and sends the change.

    send_feedback(type, sequence, data=..., state=...) is pyremoteplay's
    RPStream.send_feedback (or a test double)."""

    def __init__(self, send_feedback: Callable, clock: Callable[[], float] = time.monotonic):
        self._send = send_feedback
        self._clock = clock
        self._history: deque[bytes] = deque(maxlen=HISTORY)
        self._seq_event = 0
        self._seq_state = 0
        self._sent_buttons: dict[str, int] = {}
        self._sent_sticks: tuple[Stick, Stick] = (CENTRE, CENTRE)
        self._state_at: float | None = None

    def sync(self, buttons: dict[str, int], left: Stick, right: Stick,
             min_interval: float = MIN_STATE_INTERVAL) -> None:
        """buttons: {name: value} for every pressed button; absent means released."""
        for name in sorted(set(self._sent_buttons) | set(buttons)):
            value = buttons.get(name, 0)
            if self._sent_buttons.get(name, 0) != value:
                self._event(name, value)
                if value:
                    self._sent_buttons[name] = value
                else:
                    self._sent_buttons.pop(name, None)
        sticks = (clamp_stick(left), clamp_stick(right))
        now = self._clock()
        since = None if self._state_at is None else now - self._state_at
        changed = sticks != self._sent_sticks
        if (changed and (since is None or since >= min_interval)) or (
                since is None or since >= MAX_STATE_INTERVAL):
            self._send(FeedbackHeader.Type.STATE, self._seq_state,
                       state=ControllerState(left=sticks[0], right=sticks[1]))
            self._seq_state = (self._seq_state + 1) & 0xFFFF
            self._sent_sticks = sticks
            self._state_at = now

    def _event(self, button: str, value: int) -> None:
        self._history.appendleft(encode_event(button, value))
        self._send(FeedbackHeader.Type.EVENT, self._seq_event, data=b"".join(self._history))
        self._seq_event = (self._seq_event + 1) & 0xFFFF

    @property
    def sent_buttons(self) -> dict[str, int]:
        return dict(self._sent_buttons)

    @property
    def sent_sticks(self) -> tuple[Stick, Stick]:
        return self._sent_sticks
