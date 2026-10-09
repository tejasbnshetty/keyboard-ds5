# SPDX-License-Identifier: AGPL-3.0-only
"""Watch mode: control a playing video without holding a Remote Play session open.

While a session is open, a streaming app's picture goes black on the TV (tested in Apple TV),
so every action here is a short burst: connect, press, disconnect. Shared by the command line
and the future Windows app.

- Collect window: after the first press, wait COLLECT_MS for more so quick taps share one
  connection. Presses arriving while a burst is connected join it.
- The PS5 refuses new sessions for ~9 s after one ends. Actions in that window wait with a
  countdown. Pressing play/pause again before it's sent cancels both.
- Smart play: resuming from "paused" skips back first, because ~3 s of video goes by while
  the picture comes back after a burst.

Events go to on_event(kind, message):
  "queued"    an action was accepted (message describes it)
  "cancelled" pending actions cancelled each other out
  "countdown" waiting for the PS5 ("sending in N s")
  "burst"     a burst finished; message is the timing breakdown
  "state"     best-guess playing/paused state changed
  "app"       the button map in use
  "mode"      message "browse": the caller should switch to Browse mode (after Home)
  "error"     a burst failed
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import asdict, dataclass
from typing import Callable

from . import config, ps5
from .appmaps import AppMap, load_app_maps, pick_app_map  # noqa: F401 (re-exported)
from .remote import Remote

_LOGGER = logging.getLogger(__name__)

BUSY_RETRY_S = 1.0      # if the PS5 still refuses after the predicted gap, retry this often
BUSY_GIVE_UP_S = 30.0

PLAYING, PAUSED, UNKNOWN = "playing", "paused", "unknown"


# ---- settings --------------------------------------------------------------------------------

@dataclass
class WatchSettings:
    smart_play_s: int = 10    # skip back this much when resuming from paused: 0 (off), 10, 20
    smart_pause_s: int = 0    # skip back this much right after pausing: 0 (off), 10, 20
    collect_ms: int = 300     # wait for more presses before connecting
    post_wait_ms: int = 300   # keep the session open this long after the last press
    gap_ms: int = 150         # pause between presses inside one burst
    app: str = "auto"         # "auto" (from the running app) or a key in app_maps.json

    @classmethod
    def load(cls) -> "WatchSettings":
        saved = config.load().get("watch", {})
        known = {k: v for k, v in saved.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self) -> None:
        config.update(watch=asdict(self))


# ---- actions ---------------------------------------------------------------------------------

@dataclass
class Action:
    label: str
    buttons: list[str]
    toggle: bool = False            # play/pause: two pending toggles cancel out
    prev_state: str = UNKNOWN       # play state before this toggle, to undo on cancel
    then_browse: bool = False       # switch to Browse mode after it's sent


class WatchMode:
    def __init__(self, remote: Remote, settings: WatchSettings,
                 on_event: Callable[[str, str], None] | None = None):
        self.remote = remote
        self.settings = settings
        self._on_event = on_event or (lambda kind, msg: None)
        self.app: AppMap | None = None
        self.play_state = PLAYING   # entering Watch mode means a video is playing
        self._pending: list[Action] = []
        self._task: asyncio.Task | None = None
        self._connected_burst = False

    def _emit(self, kind: str, message: str) -> None:
        _LOGGER.debug("%s: %s", kind, message)
        try:
            self._on_event(kind, message)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("on_event callback failed")

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    async def enter(self) -> None:
        """Call when switching into Watch mode (after the live session was closed)."""
        self.play_state = PLAYING
        status = await ps5.async_get_status(self.remote.host)
        self.app, why = pick_app_map(self.settings.app, status)
        unverified = [k for k, ok in self.app.verified.items() if not ok]
        note = f" - unverified: {', '.join(unverified)}" if unverified else ""
        self._emit("app", f"Button map: {self.app.name} ({why}){note}")

    # ---- building actions ----

    def play_pause(self) -> None:
        a = self.app
        prev = self.play_state
        if prev == PAUSED:
            back = [a.back] * a.seek_presses(self.settings.smart_play_s) if self.settings.smart_play_s else []
            label = f"play (skip back {self.settings.smart_play_s} s first)" if back else "play"
            action = Action(label, back + [a.play_pause], toggle=True, prev_state=prev)
            self.play_state = PLAYING
        else:
            back = [a.back] * a.seek_presses(self.settings.smart_pause_s) if self.settings.smart_pause_s else []
            label = "pause" + (f" (then skip back {self.settings.smart_pause_s} s)" if back else "")
            if prev == UNKNOWN:
                label = "play/pause"
            action = Action(label, [a.play_pause] + back, toggle=True, prev_state=prev)
            self.play_state = PAUSED if prev == PLAYING else UNKNOWN
        self._add(action)

    def seek(self, seconds: int) -> None:
        a = self.app
        button = a.back if seconds < 0 else a.forward
        n = a.seek_presses(abs(seconds))
        word = "back" if seconds < 0 else "forward"
        self._add(Action(f"{word} {n * a.seek_seconds} s", [button] * n))

    def home(self) -> None:
        self._add(Action("home (PS button)", [self.app.home], then_browse=True))

    def _add(self, action: Action) -> None:
        if action.toggle and not self._connected_burst:
            pending = next((p for p in self._pending if p.toggle), None)
            if pending:
                # e.g. pause then play before anything was sent: net effect is nothing.
                self._pending.remove(pending)
                self.play_state = pending.prev_state
                self._emit("cancelled", f"'{pending.label}' and '{action.label}' cancel out - not sent")
                self._emit("state", self.play_state)
                if not self._pending and self.busy:
                    self._task.cancel()
                return
        self._pending.append(action)
        self._emit("queued", action.label)
        if action.toggle:
            self._emit("state", self.play_state)
        if not self.busy:
            self._task = asyncio.create_task(self._run())

    # ---- the burst ----

    async def _run(self) -> None:
        t_first = time.monotonic()
        then_browse = False
        try:
            await asyncio.sleep(self.settings.collect_ms / 1000)
            t_conn_start, t_connected = await self._connect()
            self._connected_burst = True
            presses = 0
            t_pressing = time.monotonic()
            press_time = 0.0
            post_wait = self.settings.post_wait_ms / 1000
            while self._pending:
                action = self._pending.pop(0)
                then_browse |= action.then_browse
                for button in action.buttons:
                    if presses:
                        await asyncio.sleep(self.settings.gap_ms / 1000)
                    t = time.monotonic()
                    await self.remote.press(button)
                    press_time += time.monotonic() - t
                    presses += 1
                if not self._pending:
                    # Presses that arrive during the post-press wait join this burst.
                    await asyncio.sleep(post_wait)
            t_pressed = time.monotonic()
            self._connected_burst = False
            self.remote.end_burst()
            t_done = time.monotonic()
            self._emit("burst", (
                f"waited {t_conn_start - t_first:.2f}s | connect {t_connected - t_conn_start:.2f}s | "
                f"{presses} press{'es' if presses != 1 else ''} {t_pressed - t_pressing - post_wait:.2f}s "
                f"| post-wait {post_wait:.2f}s | disconnect {t_done - t_pressed:.2f}s | "
                f"total {t_done - t_first:.2f}s"))
        except asyncio.CancelledError:
            self.remote.end_burst()
            raise
        except ps5.PS5Error as err:
            self.remote.end_burst()
            self._pending.clear()
            self._emit("error", f"Burst failed: {err}")
        finally:
            self._connected_burst = False
            self._task = None
        if then_browse:
            self._emit("mode", "browse")
        elif self._pending:  # arrived just after we disconnected
            self._task = asyncio.create_task(self._run())

    async def _connect(self) -> tuple[float, float]:
        """Wait until the PS5 should accept a session (countdown), then connect.
        Returns (time connecting started, time connected)."""
        last_shown = None
        give_up = time.monotonic() + BUSY_GIVE_UP_S
        while True:
            left = self.remote.free_in
            if left > 0:
                if math.ceil(left) != last_shown:
                    last_shown = math.ceil(left)
                    self._emit("countdown", f"PS5 is still closing the last session - sending in {last_shown} s")
                await asyncio.sleep(min(0.25, left))
                continue
            t0 = time.monotonic()
            try:
                await self.remote.open_burst()
                return t0, time.monotonic()
            except ps5.SessionBusy:
                if time.monotonic() > give_up:
                    raise
                self._emit("countdown", "PS5 not ready yet - retrying in 1 s")
                await asyncio.sleep(BUSY_RETRY_S)

    async def stop(self) -> None:
        """Drop anything pending and disconnect (when leaving Watch mode or quitting)."""
        self._pending.clear()
        task, self._task = self._task, None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.remote.end_burst()


# ---- post-press wait test --------------------------------------------------------------------

POST_WAIT_TEST_VALUES = [600, 400, 250, 150, 80, 0]


async def post_wait_test(remote: Remote, settings: WatchSettings, button: str,
                         ask: Callable[[str], str], say: Callable[[str], None]) -> int | None:
    """Send `button` in single-press bursts with shrinking post-press waits, asking after
    each whether the PS5 reacted. Returns the shortest wait that worked with every longer
    value also working, or None."""
    results: dict[int, bool] = {}
    for wait_ms in POST_WAIT_TEST_VALUES:
        reply = ask(f"\nNext: post-wait {wait_ms} ms. Press Enter to send '{button}' (s = stop): ")
        if reply.strip().lower() == "s":
            break
        while (left := remote.free_in) > 0:
            say(f"  waiting for the PS5: {math.ceil(left)} s")
            await asyncio.sleep(min(1.0, left))
        try:
            t0 = time.monotonic()
            await remote.open_burst()
            t1 = time.monotonic()
            await remote.press(button)
            await asyncio.sleep(wait_ms / 1000)
        finally:
            remote.end_burst()
        say(f"  sent: connect {t1 - t0:.2f}s, press {remote.press_s:.2f}s, post-wait {wait_ms / 1000:.2f}s")
        answer = ask("  Did the PS5 react (e.g. video paused / resumed)? [y/n]: ").strip().lower()
        results[wait_ms] = answer.startswith("y")
    best = None
    for wait_ms in POST_WAIT_TEST_VALUES:  # longest to shortest
        if wait_ms not in results or not results[wait_ms]:
            break
        best = wait_ms
    say("\nResults: " + ", ".join(f"{w} ms {'OK' if ok else 'missed'}" for w, ok in results.items()))
    return best
