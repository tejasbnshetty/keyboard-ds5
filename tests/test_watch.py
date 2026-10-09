# SPDX-License-Identifier: AGPL-3.0-only
"""Watch mode is benched, but its logic is kept working."""
import asyncio

import pytest

from ps5remote import config, ps5, watch
from ps5remote.watch import PAUSED, PLAYING, UNKNOWN, WatchMode, WatchSettings

from .fakes import FakePS5


class FakeRemote:
    """Records bursts: each burst is the list of buttons sent in it."""

    host = "192.168.1.50"
    press_s = 0.0

    def __init__(self):
        self.bursts: list[list[str]] = []
        self.free_in = 0.0
        self.busy_refusals = 0
        self._open = False

    async def open_burst(self):
        if self.busy_refusals:
            self.busy_refusals -= 1
            raise ps5.SessionBusy("busy")
        self._open = True
        self.bursts.append([])
        return 0.0

    async def press(self, button):
        assert self._open
        self.bursts[-1].append(button)

    def end_burst(self):
        self._open = False


@pytest.fixture
def setup(monkeypatch, paired):
    FakePS5(monkeypatch, status={"status-code": 200, "running-app-name": "Apple TV"})
    remote = FakeRemote()
    events = []
    settings = WatchSettings(collect_ms=0, post_wait_ms=0, gap_ms=0, smart_play_s=10)
    mode = WatchMode(remote, settings, on_event=lambda k, m: events.append((k, m)))
    return mode, remote, events


async def settle(mode):
    for _ in range(50):
        await asyncio.sleep(0)
        if not mode.busy:
            return


def test_settings_round_trip():
    s = WatchSettings(smart_play_s=20, post_wait_ms=150)
    s.save()
    assert WatchSettings.load() == s


def test_settings_ignore_unknown_saved_fields():
    config.update(watch={"post_wait_ms": 99, "removed_option": 1})
    assert WatchSettings.load().post_wait_ms == 99


def test_enter_picks_the_running_app(setup):
    mode, _, events = setup
    asyncio.run(mode.enter())
    assert mode.app.key == "appletv"
    assert mode.play_state == PLAYING
    assert any(k == "app" and "Apple TV" in m for k, m in events)


def test_pause_then_play_with_smart_play(setup):
    mode, remote, _ = setup

    async def go():
        await mode.enter()
        mode.play_pause()
        await settle(mode)
        assert mode.play_state == PAUSED
        mode.play_pause()
        await settle(mode)

    asyncio.run(go())
    assert remote.bursts == [["cross"], ["left", "cross"]]
    assert mode.play_state == PLAYING


def test_two_toggles_before_sending_cancel_out(setup):
    mode, remote, events = setup

    async def go():
        await mode.enter()
        mode.play_pause()
        mode.play_pause()
        await settle(mode)

    asyncio.run(go())
    assert remote.bursts == []
    assert mode.play_state == PLAYING
    assert any(k == "cancelled" for k, _ in events)


def test_seeks_are_batched_into_one_burst(setup):
    mode, remote, _ = setup

    async def go():
        await mode.enter()
        mode.seek(-30)
        mode.seek(10)
        await settle(mode)

    asyncio.run(go())
    assert remote.bursts == [["left", "left", "left", "right"]]


def test_home_switches_back_to_browse(setup):
    mode, remote, events = setup

    async def go():
        await mode.enter()
        mode.home()
        await settle(mode)

    asyncio.run(go())
    assert remote.bursts == [["ps"]]
    assert ("mode", "browse") in events


def test_unknown_state_toggle(setup):
    mode, _, events = setup

    async def go():
        await mode.enter()
        mode.play_state = UNKNOWN
        mode.play_pause()
        await settle(mode)

    asyncio.run(go())
    assert ("queued", "play/pause") in events
    assert mode.play_state == UNKNOWN


def test_busy_ps5_is_retried(setup, fast_sleep):
    mode, remote, events = setup
    remote.busy_refusals = 2

    async def go():
        await mode.enter()
        mode.seek(10)
        await settle(mode)

    asyncio.run(go())
    assert remote.bursts == [["right"]]
    assert sum(1 for k, _ in events if k == "countdown") == 2


def test_stop_drops_pending_actions(setup):
    mode, remote, _ = setup
    mode.settings.collect_ms = 10_000

    async def go():
        await mode.enter()
        mode.seek(10)
        await asyncio.sleep(0)
        await mode.stop()

    asyncio.run(go())
    assert remote.bursts == [] and not mode.busy


@pytest.mark.parametrize("answers, best", [
    (["", "y"] * 6, 0),
    (["", "y", "", "y", "", "n", "", "y", "", "y", "", "y"], 400),
    (["", "n"] + ["", "y"] * 5, None),
    (["s"], None),
    (["", "y", "s"], 600),
])
def test_post_wait_test_finds_shortest_reliable_wait(answers, best):
    remote = FakeRemote()
    replies = iter(answers)
    said = []
    result = asyncio.run(watch.post_wait_test(
        remote, WatchSettings(), "cross", ask=lambda _q: next(replies), say=said.append))
    assert result == best
