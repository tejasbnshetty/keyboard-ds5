# SPDX-License-Identifier: AGPL-3.0-only
"""Controller wire format (as chiaki-ng) and what gets sent when."""
import pytest
from pyremoteplay.stream_packets import FeedbackHeader, FeedbackPacket

from ps5remote import gamepad
from ps5remote.gamepad import PadSender, encode_event
from ps5remote.remote import BUTTONS


@pytest.mark.parametrize("button, value, expected", [
    ("cross", 255, "80 88 ff"),
    ("cross", 0, "80 88 00"),
    ("cross", 7, "80 88 ff"),      # digital buttons are all or nothing
    ("up", 255, "80 80 ff"),
    ("square", 255, "80 8a ff"),
    ("l2", 102, "80 86 66"),       # analog trigger
    ("r2", 255, "80 87 ff"),
    ("r2", 0, "80 87 00"),
    ("options", 255, "80 ac"),     # two-byte buttons: id + 0x20 while pressed
    ("options", 0, "80 8c"),
    ("ps", 255, "80 ae"),
    ("ps", 0, "80 8e"),
    ("l3", 255, "80 af"),
    ("l3", 0, "80 8f"),
    ("r3", 255, "80 b0"),
    ("r3", 0, "80 90"),
    ("touchpad", 255, "80 b1"),
    ("touchpad", 0, "80 91"),
])
def test_encode_event(button, value, expected):
    assert encode_event(button, value).hex(" ") == expected


def test_every_remote_button_can_be_encoded():
    for button in BUTTONS:
        assert encode_event(button, 255)[0] == 0x80


def test_unknown_button():
    with pytest.raises(ValueError):
        encode_event("jump", 255)


class Recorder:
    def __init__(self):
        self.events: list[tuple[int, bytes]] = []
        self.states: list[tuple[int, tuple, tuple]] = []

    def __call__(self, kind, seq, data=b"", state=None):
        # Must also be a valid pyremoteplay packet.
        FeedbackPacket(kind, sequence=seq, data=data, state=state, host_type="PS5").bytes()
        if kind == FeedbackHeader.Type.EVENT:
            self.events.append((seq, data))
        else:
            self.states.append((seq, (state.left.x, state.left.y), (state.right.x, state.right.y)))


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def out():
    rec, clock = Recorder(), Clock()
    return PadSender(rec, clock), rec, clock


C = gamepad.CENTRE


def test_first_sync_sends_neutral_state(out):
    sender, rec, _ = out
    sender.sync({}, C, C)
    assert rec.events == []
    assert rec.states == [(0, (0, 0), (0, 0))]


def test_press_and_release_send_one_event_each(out):
    sender, rec, _ = out
    sender.sync({"cross": 255}, C, C)
    sender.sync({"cross": 255}, C, C)   # unchanged: nothing new
    sender.sync({}, C, C)
    assert [d.hex(" ") for _, d in rec.events] == ["80 88 ff", "80 88 00 80 88 ff"]
    assert [s for s, _ in rec.events] == [0, 1]


def test_history_is_newest_first_and_capped(out):
    sender, rec, _ = out
    for i in range(20):
        sender.sync({"cross": 255} if i % 2 == 0 else {}, C, C)
    last = rec.events[-1][1]
    assert len(last) == 3 * gamepad.HISTORY
    assert last[:3].hex(" ") == "80 88 00"


def test_trigger_value_change_is_sent(out):
    sender, rec, _ = out
    sender.sync({"r2": 102}, C, C)
    sender.sync({"r2": 255}, C, C)
    assert [d[:3].hex(" ") for _, d in rec.events] == ["80 87 66", "80 87 ff"]


def test_mixed_two_and_three_byte_history(out):
    sender, rec, _ = out
    sender.sync({"l3": 255}, C, C)
    sender.sync({"l3": 255, "cross": 255}, C, C)
    assert rec.events[-1][1].hex(" ") == "80 88 ff 80 af"


def test_sticks_are_scaled_and_clamped(out):
    sender, rec, clock = out
    sender.sync({}, (1.0, -0.5), (2.0, -3.0))
    assert rec.states[-1][1:] == ((32767, -16383), (32767, -32767))


def test_stick_changes_are_rate_limited(out):
    sender, rec, clock = out
    sender.sync({}, C, C)
    clock.now += 0.004
    sender.sync({}, (0.5, 0), C)            # too soon: held back
    assert len(rec.states) == 1
    clock.now += 0.005
    sender.sync({}, (0.5, 0), C)            # 9 ms after the last: sent
    assert len(rec.states) == 2
    clock.now += 0.005
    sender.sync({}, (0.5, 0), C, min_interval=1 / 60)
    assert len(rec.states) == 2


def test_buttons_are_never_rate_limited(out):
    sender, rec, clock = out
    sender.sync({}, C, C)
    sender.sync({"cross": 255}, C, C)
    sender.sync({}, C, C)
    assert len(rec.events) == 2


def test_unchanged_state_is_resent_every_200ms(out):
    sender, rec, clock = out
    sender.sync({}, (0.3, 0), C)
    clock.now += 0.15
    sender.sync({}, (0.3, 0), C)
    assert len(rec.states) == 1
    clock.now += 0.06
    sender.sync({}, (0.3, 0), C)
    assert len(rec.states) == 2


def test_sequences_wrap_at_16_bits(out):
    sender, rec, clock = out
    sender._seq_event = 0xFFFF
    sender.sync({"cross": 255}, C, C)
    sender.sync({}, C, C)
    assert [s for s, _ in rec.events] == [0xFFFF, 0]


def test_sent_state_is_reported(out):
    sender, _, _ = out
    sender.sync({"r2": 255}, (0.5, 0.5), C)
    assert sender.sent_buttons == {"r2": 255}
    assert sender.sent_sticks == ((0.5, 0.5), C)
