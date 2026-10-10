# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import time

import pytest

from ps5remote import ps5, remote as remote_mod
from ps5remote.remote import Remote, check_button

from .fakes import ASLEEP, FakePS5


@pytest.fixture
def fake(monkeypatch, paired):
    return FakePS5(monkeypatch)


@pytest.fixture
def events():
    return []


@pytest.fixture
def remote(fake, events):
    return Remote(press_ms=1, on_event=lambda kind, msg: events.append((kind, msg)))


def run(coro):
    return asyncio.run(coro)


async def connect_then_close(r: Remote) -> None:
    """close() runs inside the event loop, as it always does in the app."""
    await r.connect()
    r.close()


@pytest.fixture
def ticking_clock(monkeypatch):
    """remote.py's clock moves 1 s per reading (Windows' clock barely moves under fast_sleep)."""
    class Clock:
        now = 1000.0

        @classmethod
        def monotonic(cls):
            cls.now += 1
            return cls.now

    monkeypatch.setattr(remote_mod, "time", Clock)


def test_needs_setup():
    with pytest.raises(ps5.PS5Error, match="discover"):
        Remote()


def test_check_button():
    assert check_button("CROSS") == "cross"
    with pytest.raises(ps5.PS5Error, match="Unknown button"):
        check_button("jump")


def test_tap_connects_once_and_releases(remote, fake):
    async def go():
        await remote.tap("cross")
        await remote.tap("ps")
        return remote.connected

    assert run(go())
    assert fake.opens == 1
    assert fake.presses == [("CROSS", "press"), ("CROSS", "release"),
                            ("PS", "press"), ("PS", "release")]


def test_tap_wakes_a_sleeping_ps5(remote, fake, events, fast_sleep):
    fake.status = ASLEEP
    run(remote.tap("ps"))
    assert fake.wakes == 1
    assert remote.last_wake_s is not None
    assert any("waking" in m for _, m in events)


def test_unreachable_ps5(remote, fake):
    fake.status = {}
    with pytest.raises(ps5.PS5Error, match="No PS5 answered"):
        run(remote.tap("cross"))
    assert fake.opens == 0


def test_asleep_without_wake(remote, fake):
    fake.status = ASLEEP
    with pytest.raises(ps5.PS5Error, match="rest mode"):
        run(remote.connect(wake=False))


def test_fatal_refusal_is_not_retried(remote, fake, fast_sleep):
    fake.open_errors = [ps5.PS5Error(f"refused {0x80108B12}")]
    with pytest.raises(ps5.PS5Error):
        run(remote.connect())
    assert fake.opens == 1


def test_ordinary_failure_retried_once(remote, fake, fast_sleep, ticking_clock):
    fake.open_errors = [ps5.PS5Error("x"), ps5.PS5Error("y"), ps5.PS5Error("z")]
    with pytest.raises(ps5.PS5Error, match="y"):
        run(remote.connect())
    assert fake.opens == 2


def test_busy_refusal_is_retried_patiently(remote, fake, fast_sleep):
    fake.open_errors = [ps5.SessionBusy("busy")] * 4
    run(remote.connect())
    assert fake.opens == 5 and remote.connected


def test_teardown_starts_the_reuse_countdown(remote, fake):
    async def go():
        await remote.connect()
        assert remote.free_in == 0
        remote.close()

    run(go())
    assert fake.devices[0].disconnected
    assert 0 < remote.free_in <= remote.reuse_delay


def test_free_in_counts_down(remote):
    remote.last_session_end = time.monotonic() - 5
    assert remote.reuse_delay - 5.1 < remote.free_in < remote.reuse_delay - 4.9
    remote.last_session_end = time.monotonic() - 60
    assert remote.free_in == 0


def test_connect_waits_out_the_reuse_gap(remote, fake, events, fast_sleep):
    remote.last_session_end = time.monotonic()
    remote.reuse_delay = 0.05
    run(remote.connect())
    assert any("still closing" in m for _, m in events)
    assert remote.connected


def test_close_reports_disconnect_once(remote, events):
    async def go():
        await connect_then_close(remote)
        remote.close()

    run(go())
    assert [k for k, _ in events].count("disconnected") == 1


def test_hold_repeats_until_released(remote, fake):
    remote.repeat_delay = 0.02
    remote.repeat_interval = 0.01

    async def go():
        await remote.hold("down")
        await asyncio.sleep(0.15)
        await remote.stop_hold()
        count = len(fake.presses)
        await asyncio.sleep(0.05)
        return count

    count = run(go())
    assert count == len(fake.presses)  # nothing after release
    presses = [p for p in fake.presses if p[1] == "press"]
    assert len(presses) >= 3 and all(p == ("DOWN", "press") for p in presses)
    assert fake.presses[-1] == ("DOWN", "release")


def test_watchdog_reports_a_dropped_session(remote, fake, events, monkeypatch):
    monkeypatch.setattr(remote_mod, "WATCH_INTERVAL", 0.01)

    async def go():
        await remote.connect()
        fake.drop()
        await asyncio.sleep(0.1)

    run(go())
    assert any(k == "dropped" for k, _ in events)
    assert not remote.connected
    assert remote._dropped_recently


def test_watchdog_notices_rest_mode(remote, fake, events, monkeypatch):
    monkeypatch.setattr(remote_mod, "WATCH_INTERVAL", 0.01)

    async def go():
        await remote.connect()
        fake.status = ASLEEP
        await asyncio.sleep(0.1)

    run(go())
    assert any(k == "dropped" and "rest mode" in m for k, m in events)


def test_idle_timeout_disconnects(remote, fake, events, monkeypatch):
    monkeypatch.setattr(remote_mod, "WATCH_INTERVAL", 0.01)
    remote.idle_timeout = 0.02

    async def go():
        await remote.connect()
        await asyncio.sleep(0.15)

    run(go())
    assert any(k == "disconnected" and "Idle" in m for k, m in events)
    assert not remote.connected


def test_wake_when_already_awake(remote, fake):
    assert run(remote.wake()) is False
    assert fake.wakes == 0


def test_burst_does_not_wake(remote, fake):
    fake.status = ASLEEP
    with pytest.raises(ps5.PS5Error, match="rest mode"):
        run(remote.open_burst())
    assert fake.wakes == 0


def test_burst_press_needs_a_session(remote):
    with pytest.raises(ps5.PS5Error, match="lost"):
        run(remote.press("cross"))


def test_burst_cycle(remote, fake):
    async def go():
        await remote.open_burst()
        await remote.press("cross")
        remote.end_burst()

    run(go())
    assert fake.presses == [("CROSS", "press"), ("CROSS", "release")]
    assert not remote.connected and remote.free_in > 0


def test_protected_content_passthrough(remote, fake):
    assert remote.protected_content is None
    run(remote.connect())
    fake.devices[0].session.protected_content = True
    assert remote.protected_content is True


def test_event_callback_errors_are_contained(fake):
    def boom(kind, msg):
        raise RuntimeError("callback bug")

    run(connect_then_close(Remote(on_event=boom)))  # must not raise


def test_new_buttons_tap(remote, fake):
    async def go():
        for button in ("l3", "r3", "touchpad"):
            await remote.tap(button)

    run(go())
    assert fake.presses == [("L3", "press"), ("L3", "release"), ("R3", "press"),
                            ("R3", "release"), ("TOUCHPAD", "press"), ("TOUCHPAD", "release")]


def test_set_game_holds_buttons_and_moves_sticks(remote, fake):
    async def go():
        await remote.connect()
        remote.set_game({"r2": 102, "cross": 255}, (0.0, -1.0), (0.5, 0.0))
        await asyncio.sleep(0.02)
        remote.set_game({"r2": 102}, (0.0, -1.0), (0.5, 0.0))

    run(go())
    stream = fake.devices[0].session.stream
    assert stream.values == [("cross", 255), ("r2", 102), ("cross", 0)]
    assert stream.states[-1] == ((0, -32767), (16383, 0))


def test_game_state_set_before_connecting_is_sent_on_connect(remote, fake):
    async def go():
        remote.set_game({"cross": 255}, (1.0, 0.0), (0, 0))
        await remote.connect()

    run(go())
    stream = fake.devices[0].session.stream
    assert stream.values == [("cross", 255)]
    assert stream.states[0] == ((32767, 0), (0, 0))


def test_close_sends_neutral_first(remote, fake):
    async def go():
        await remote.connect()
        remote.set_game({"r2": 255, "l3": 255}, (1.0, 0.0), (0.0, 1.0))
        await asyncio.sleep(0.01)
        remote.close()

    run(go())
    stream = fake.devices[0].session.stream
    assert set(stream.values[-2:]) == {("l3", 0), ("r2", 0)}
    assert stream.states[-1] == ((0, 0), (0, 0))
    assert not remote.game_active


def test_neutral_is_sent_even_right_after_a_stick_update(remote, fake):
    """The rate limit must never hold back the neutral state sent before disconnecting."""
    remote.stick_hz = 1   # a stick update was just sent: the next one would wait a second

    async def go():
        await remote.connect()
        remote.set_game({}, (1.0, 0.0), (0.0, 1.0))
        remote.close()     # immediately

    run(go())
    assert fake.devices[0].session.stream.states[-1] == ((0, 0), (0, 0))


def test_dropped_session_clears_game_state(remote, fake, monkeypatch):
    monkeypatch.setattr(remote_mod, "WATCH_INTERVAL", 0.01)

    async def go():
        await remote.connect()
        remote.set_game({"cross": 255}, (1.0, 0.0), (0, 0))
        fake.drop()
        await asyncio.sleep(0.1)

    run(go())
    assert not remote.game_active


def test_held_game_input_is_not_idle(remote, fake, events, monkeypatch):
    monkeypatch.setattr(remote_mod, "WATCH_INTERVAL", 0.01)
    remote.idle_timeout = 0.02

    async def go():
        await remote.connect()
        remote.set_game({}, (1.0, 0.0), (0, 0))
        remote._last_activity -= 10
        await asyncio.sleep(0.1)
        return remote.connected

    assert run(go())
    assert not any(k == "disconnected" for k, _ in events)


def test_unchanged_held_state_is_resent(remote, fake, monkeypatch):
    async def go():
        await remote.connect()
        remote.set_game({}, (0.5, 0.0), (0, 0))
        await asyncio.sleep(0.5)

    run(go())
    assert len(fake.devices[0].session.stream.states) >= 3   # every 200 ms


def test_stick_rate_limit(remote, fake, monkeypatch):
    remote.stick_hz = 50

    async def go():
        await remote.connect()
        start = time.monotonic()
        for i in range(200):
            remote.set_game({}, (i / 200, 0.0), (0, 0))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        return time.monotonic() - start

    elapsed = run(go())
    states = fake.devices[0].session.stream.states
    assert len(states) <= 2 + elapsed * 50   # 200 changes, at most 50 a second sent


def test_session_that_never_starts_mentions_a_possible_protocol_change(paired, monkeypatch, fast_sleep):
    """The real _open_session (not the fake): the console accepts, then never gets ready."""
    torn_down = []

    class Session:
        error = ""
        is_ready = False
        is_stopped = False
        on_protected_change = None

    class Device:
        def __init__(self, host):
            self.session = Session()
            self.is_on = True
            self.controller = type("C", (), {"disconnect": lambda self: None})()

        async def async_get_status(self):
            return {"status-code": 200}

        def get_users(self, profiles=None):
            return ["tester"]

        def create_session(self, user, profiles=None):
            return self.session

        async def connect(self):
            return True

        async def async_wait_for_session(self, timeout):
            return False

        def disconnect(self):
            torn_down.append(True)

    async def status(_host):
        return {"status-code": 200}

    monkeypatch.setattr(ps5, "Device", Device)
    monkeypatch.setattr(ps5, "async_get_status", status)
    r = Remote()
    with pytest.raises(ps5.PS5Error) as err:
        run(r.connect())
    text = str(err.value)
    assert "never finished starting" in text and "system update" in text
    assert "Close any other Remote Play app" in text
    assert torn_down   # the half-open session was closed


def test_standby(remote, fake):
    calls = []

    async def standby():
        calls.append(1)
        fake.devices[-1].session.is_stopped = True

    async def go():
        await remote.connect()
        fake.devices[-1].session.async_standby = standby
        return await remote.standby()

    assert run(go()) is True
    assert calls == [1]
    assert not remote.connected


def test_standby_when_already_asleep(remote, fake):
    fake.status = ASLEEP
    assert run(remote.standby()) is False
