# SPDX-License-Identifier: AGPL-3.0-only
"""Stand-ins for a PS5 session, so Remote can be tested without one."""
from __future__ import annotations

from pyremoteplay.stream_packets import FeedbackHeader

from ps5remote import ps5
from ps5remote.gamepad import BUTTON_IDS, SHORT_BUTTON_IDS
from ps5remote.remote import Remote

AWAKE = {"status-code": 200, "host-type": "PS5", "host-name": "PS5-TEST"}
ASLEEP = {"status-code": 620, "host-type": "PS5", "host-name": "PS5-TEST"}

_IDS = {v: k for k, v in BUTTON_IDS.items()}
_SHORT = {v: k for k, v in SHORT_BUTTON_IDS.items()}


def decode_newest(data: bytes) -> tuple[str, int]:
    """The newest event in an event packet: (button, value)."""
    if data[1] in _IDS:
        return _IDS[data[1]], data[2]
    if data[1] in _SHORT:
        return _SHORT[data[1]], 0
    return _SHORT[data[1] - 0x20], 255


class FakeStream:
    """Records what the PS5 would receive.

    presses: (BUTTON, "press"/"release") per button event. values: (button, value) per
    event. states: (left, right) per stick-state packet, as -32767..32767 ints."""

    def __init__(self, presses: list):
        self.presses = presses
        self.values: list[tuple[str, int]] = []
        self.packets: list[bytes] = []
        self.states: list[tuple[tuple[int, int], tuple[int, int]]] = []

    def send_feedback(self, feedback_type, sequence, data=b"", state=None):
        if feedback_type == FeedbackHeader.Type.EVENT:
            self.packets.append(data)
            button, value = decode_newest(data)
            self.values.append((button, value))
            self.presses.append((button.upper(), "press" if value else "release"))
        else:
            self.states.append(((state.left.x, state.left.y), (state.right.x, state.right.y)))


class FakeController:
    def disconnect(self):
        pass


class FakeSession:
    def __init__(self, presses: list):
        self.is_ready = True
        self.is_stopped = False
        self.error = ""
        self.protected_content = None
        self.stream = FakeStream(presses)


class FakeDevice:
    def __init__(self, log: list):
        self.controller = FakeController()
        self.session = FakeSession(log)
        self.disconnected = False

    def disconnect(self):
        self.disconnected = True
        self.session.is_ready = False
        self.session.is_stopped = True


class FakePS5:
    """Patches ps5 status checks and Remote._open_session.

    status: what the next status check returns. open_errors: exceptions raised by the next
    connect attempts, in order. presses: every (button, action) the PS5 received."""

    def __init__(self, monkeypatch, status=AWAKE):
        self.status = status
        self.open_errors: list[Exception] = []
        self.opens = 0
        self.presses: list[tuple[str, str]] = []
        self.devices: list[FakeDevice] = []
        self.wakes = 0
        fake = self

        async def get_status(_host):
            return dict(fake.status)

        def send_wake():
            fake.wakes += 1
            fake.status = AWAKE
            return True

        async def open_session(remote: Remote):
            fake.opens += 1
            if fake.open_errors:
                raise fake.open_errors.pop(0)
            device = FakeDevice(fake.presses)
            fake.devices.append(device)
            remote._device = device
            remote._session_live = True

        monkeypatch.setattr(ps5, "async_get_status", get_status)
        monkeypatch.setattr(ps5, "send_wake", send_wake)
        monkeypatch.setattr(Remote, "_open_session", open_session)

    def drop(self):
        """The PS5 ends the session on its own."""
        self.devices[-1].session.is_stopped = True
        self.devices[-1].session.is_ready = False
