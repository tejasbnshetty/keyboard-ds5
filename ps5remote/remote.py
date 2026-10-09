# SPDX-License-Identifier: AGPL-3.0-only
"""A Remote Play session for sending controller buttons (no video is decoded).

Events are reported through on_event(kind, message), where kind is one of:
  "progress"      something slow is happening (waking, connecting, retrying)
  "connected"     session ready; message says how long it took
  "dropped"       session lost unexpectedly; the next press reconnects
  "disconnected"  closed on purpose
  "error"         a background action (e.g. hold-to-repeat) failed
  "display"       the PS5 switched to/from protected content (see protected_content)

Live use: tap()/hold() connect on demand and keep the session open. Burst use (watch.py):
open_burst(), press(), end_burst(). Gaming: set_game() holds buttons and sets the sticks.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from . import config, ps5
from .gamepad import CENTRE, PadSender, Stick

_LOGGER = logging.getLogger(__name__)

# Our button names -> display names (as pyremoteplay's FeedbackEvent.Type names them).
BUTTONS = {
    "up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT",
    "cross": "CROSS", "circle": "CIRCLE", "triangle": "TRIANGLE", "square": "SQUARE",
    "options": "OPTIONS", "ps": "PS",
    "l1": "L1", "r1": "R1", "l2": "L2", "r2": "R2",
    "l3": "L3", "r3": "R3", "touchpad": "TOUCHPAD",
}
REPEATABLE = {"up", "down", "left", "right"}

DEFAULT_PRESS_MS = 80
REPEAT_DELAY = 0.40
REPEAT_INTERVAL = 0.15

WAKE_TIMEOUT = 60.0      # rest mode -> on usually takes 10-25 s
READY_TIMEOUT = 15.0
RETRY_WINDOW = 25.0      # a just-woken PS5, or one still holding an old session, refuses for a while
WATCH_INTERVAL = 2.0
MISSED_POLLS = 2
# The PS5 refuses new sessions for ~9 s after any session ends (measured 9.2-10.9 s).
REUSE_DELAY = 9.5
KEEPALIVE_S = 0.05       # how often the held state is re-checked (resent every 200 ms)
DEFAULT_STICK_HZ = 120


def check_button(name: str) -> str:
    name = name.lower()
    if name not in BUTTONS:
        raise ps5.PS5Error(f"Unknown button '{name}'. Choose from: {', '.join(BUTTONS)}")
    return name


class Remote:
    def __init__(self, press_ms: int = DEFAULT_PRESS_MS,
                 on_event: Callable[[str, str], None] | None = None,
                 idle_timeout: float | None = None):
        self.host, self.user = ps5.require_setup()
        self.press_s = press_ms / 1000
        self.idle_timeout = idle_timeout
        self.reuse_delay = REUSE_DELAY
        self.repeat_delay = REPEAT_DELAY
        self.repeat_interval = REPEAT_INTERVAL
        self._on_event = on_event or (lambda kind, msg: None)
        self._device: ps5.Device | None = None
        self._lock = asyncio.Lock()
        self._watchdog: asyncio.Task | None = None
        self._keepalive: asyncio.Task | None = None
        self._hold: asyncio.Task | None = None
        self._sender: PadSender | None = None
        self._tap_buttons: dict[str, int] = {}
        self._game_buttons: dict[str, int] = {}
        self._sticks: tuple[Stick, Stick] = (CENTRE, CENTRE)
        self.stick_hz = DEFAULT_STICK_HZ
        self._dropped_recently = False
        self._session_live = False
        self._last_activity = time.monotonic()
        self.last_session_end: float | None = None
        self.last_wake_s: float | None = None
        self.last_connect_s: float | None = None

    @property
    def connected(self) -> bool:
        session = self._device.session if self._device else None
        return bool(session and session.is_ready)

    @property
    def free_in(self) -> float:
        """Seconds until the PS5 should accept a new session (0 if it should now)."""
        if self.last_session_end is None or self.connected:
            return 0.0
        return max(0.0, self.last_session_end + self.reuse_delay - time.monotonic())

    @property
    def protected_content(self) -> bool | None:
        """True while the PS5 reports content it can't stream (e.g. streaming-app playback);
        None until it reports either way."""
        session = self._device.session if self._device else None
        return getattr(session, "protected_content", None)

    def _emit(self, kind: str, message: str) -> None:
        _LOGGER.debug("%s: %s", kind, message)
        try:
            self._on_event(kind, message)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("on_event callback failed")

    async def connect(self, wake: bool = True) -> None:
        async with self._lock:
            await self._ensure_connected(wake)

    async def _ensure_connected(self, wake: bool = True) -> None:
        if self.connected:
            return
        self._teardown_session()
        woke = False
        state = ps5.state_from_status(await ps5.async_get_status(self.host))
        if state == ps5.UNREACHABLE:
            raise ps5.PS5Error(
                f"No PS5 answered at {self.host}. Is it switched off completely, or has its IP changed?")
        if state == ps5.ASLEEP:
            if not wake:
                raise ps5.PS5Error("The PS5 is in rest mode.")
            await self._wake()
            woke = True
        await self._wait_until_free()
        patient = woke or self._dropped_recently
        self._dropped_recently = False
        await self._connect_with_retries(patient)

    async def _wait_until_free(self) -> None:
        """Wait out the PS5's ~9 s gap after the last session, with a countdown."""
        while (left := self.free_in) > 0:
            self._emit("progress", f"PS5 is still closing the last session - connecting in {left:.0f}s")
            await asyncio.sleep(min(1.0, left))

    async def wake(self) -> bool:
        """Wake the PS5 without connecting. Returns False if it was already awake."""
        async with self._lock:
            state = ps5.state_from_status(await ps5.async_get_status(self.host))
            if state == ps5.UNREACHABLE:
                raise ps5.PS5Error(f"No PS5 answered at {self.host}.")
            if state == ps5.AWAKE:
                return False
            await self._wake()
            return True

    async def _wake(self) -> None:
        self._emit("progress", "PS5 is in rest mode - waking it...")
        start = time.monotonic()
        await asyncio.to_thread(ps5.send_wake)
        while time.monotonic() - start < WAKE_TIMEOUT:
            await asyncio.sleep(1)
            if ps5.state_from_status(await ps5.async_get_status(self.host)) == ps5.AWAKE:
                self.last_wake_s = time.monotonic() - start
                self._emit("progress", f"PS5 is awake after {self.last_wake_s:.1f}s - connecting...")
                return
            self._emit("progress", f"Waiting for the PS5 to wake... {time.monotonic() - start:.0f}s")
        raise ps5.PS5Error(
            "Sent the wake signal but the PS5 didn't wake within a minute. Check the rest-mode "
            "settings in the README.")

    async def _connect_with_retries(self, patient: bool) -> None:
        """Retry for RETRY_WINDOW after a wake, a dropped session or a busy refusal; otherwise
        retry once. Never retry refusals that retrying can't fix."""
        start = time.monotonic()
        deadline = start + (RETRY_WINDOW if patient else 0)
        attempt = 0
        self._emit("progress", "Connecting to the PS5...")
        while True:
            attempt += 1
            try:
                await self._open_session()
                self._start_sending()
                self.last_connect_s = time.monotonic() - start
                self._emit("connected", f"Connected in {self.last_connect_s:.1f}s")
                self._watchdog = asyncio.create_task(self._watch())
                return
            except ps5.PS5Error as err:
                if isinstance(err, ps5.SessionBusy):
                    deadline = max(deadline, start + RETRY_WINDOW)
                out_of_time = attempt >= 2 and time.monotonic() > deadline
                if ps5.is_fatal(str(err)) or out_of_time:
                    raise
                self._emit("progress", f"Not ready yet ({err}) - retrying...")
                await asyncio.sleep(2)

    async def _open_session(self) -> None:
        profiles = config.profiles()
        device = ps5.Device(self.host)
        if not await device.async_get_status():
            raise ps5.PS5Error(f"No PS5 answered at {self.host}.")
        if not device.is_on:
            raise ps5.PS5Error("The PS5 is in rest mode.")
        ps5.require_paired(device, self.user, profiles)
        session = device.create_session(self.user, profiles=profiles)
        if not session:
            raise ps5.PS5Error("Couldn't create a Remote Play session.")
        session.on_protected_change = lambda protected: self._emit(
            "display", "PS5 is showing protected video (picture blanked)" if protected
            else "PS5 picture is streamable again")
        self._device = device
        try:
            if not await device.connect():
                reason = device.session.error if device.session else ""
                if "Another Remote Play session" in (reason or ""):
                    raise ps5.SessionBusy("The PS5 hasn't freed the last session yet.")
                raise ps5.PS5Error(f"Remote Play connection failed. {ps5.explain(reason or '')}".strip())
            if not await device.async_wait_for_session(READY_TIMEOUT):
                raise ps5.PS5Error(
                    "Connected, but the PS5 never finished starting the session. Close any other "
                    "Remote Play app that's connected to the PS5.")
        except BaseException:
            self._teardown_session()
            raise
        self._session_live = True
        self._last_activity = time.monotonic()
        # pyremoteplay's Controller thread is not started: gamepad.PadSender sends instead.

    def _start_sending(self) -> None:
        device = self._device
        self._sender = PadSender(
            lambda *args, **kwargs: device.session.stream.send_feedback(*args, **kwargs))
        self.flush()  # the held state, e.g. keys pressed while connecting
        self._keepalive = asyncio.create_task(self._keep_sending())

    async def _keep_sending(self) -> None:
        while self.connected:
            await asyncio.sleep(KEEPALIVE_S)
            self.flush()

    def flush(self) -> None:
        """Send whatever changed in the wanted controller state (event loop only)."""
        if not self._sender or not self.connected:
            return
        buttons = dict(self._game_buttons)
        buttons.update(self._tap_buttons)
        try:
            self._sender.sync(buttons, *self._sticks, min_interval=1 / self.stick_hz)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.debug("Couldn't send controller state", exc_info=True)

    def set_game(self, buttons: dict[str, int], left: Stick, right: Stick) -> None:
        """Gaming input: these buttons held (name -> 1-255) and these stick positions."""
        self._game_buttons = dict(buttons)
        self._sticks = (left, right)
        if buttons or left != CENTRE or right != CENTRE:
            self._last_activity = time.monotonic()
        self.flush()

    @property
    def game_active(self) -> bool:
        return bool(self._game_buttons) or self._sticks != (CENTRE, CENTRE)

    def neutral(self) -> None:
        """Release every button and centre both sticks."""
        self._game_buttons, self._tap_buttons = {}, {}
        self._sticks = (CENTRE, CENTRE)
        self.flush()

    async def tap(self, button: str) -> float:
        """Press and release a button, connecting (and waking) first if needed.
        Returns the seconds spent connecting (0 when already connected)."""
        button = check_button(button)
        async with self._lock:
            start = time.monotonic()
            await self._ensure_connected()
            waited = time.monotonic() - start
            await self._tap_now(button)
        return waited

    async def _tap_now(self, button: str) -> None:
        self._last_activity = time.monotonic()
        self._tap_buttons[button] = 255
        self.flush()
        try:
            await asyncio.sleep(self.press_s)
        finally:
            # Release even if cancelled mid-press, so no button is left held down.
            self._tap_buttons.pop(button, None)
            self.flush()

    async def hold(self, button: str) -> None:
        """Tap now, then repeat until stop_hold()."""
        await self.stop_hold()
        await self.tap(button)
        self._hold = asyncio.create_task(self._repeat(button, time.monotonic() - self.press_s))

    async def _repeat(self, button: str, first_tap: float) -> None:
        try:
            await asyncio.sleep(max(0.0, self.repeat_delay - (time.monotonic() - first_tap)))
            while True:
                tick = time.monotonic()
                await self.tap(button)
                await asyncio.sleep(max(0.0, self.repeat_interval - (time.monotonic() - tick)))
        except asyncio.CancelledError:
            raise
        except Exception as err:  # pylint: disable=broad-except
            self._emit("error", f"Repeat stopped: {err}")

    async def stop_hold(self) -> None:
        task, self._hold = self._hold, None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def open_burst(self) -> float:
        """One connect attempt, no waking, no watchdog. Raises ps5.SessionBusy if the PS5 is
        still freeing the last session."""
        async with self._lock:
            if self.connected:
                return 0.0
            self._teardown_session()
            state = ps5.state_from_status(await ps5.async_get_status(self.host))
            if state == ps5.UNREACHABLE:
                raise ps5.PS5Error(f"No PS5 answered at {self.host}.")
            if state == ps5.ASLEEP:
                raise ps5.PS5Error("The PS5 is in rest mode. Switch to Browse mode to wake it.")
            start = time.monotonic()
            await self._open_session()
            self._start_sending()
            self.last_connect_s = time.monotonic() - start
            return self.last_connect_s

    async def press(self, button: str) -> None:
        """Tap a button on the already-open burst session."""
        button = check_button(button)
        async with self._lock:
            if not self.connected:
                raise ps5.PS5Error("The burst session was lost before the press was sent.")
            await self._tap_now(button)

    def end_burst(self) -> None:
        self._teardown_session()

    async def standby(self) -> bool:
        """Put the PS5 into rest mode. Returns False if it was already asleep."""
        async with self._lock:
            try:
                await self._ensure_connected(wake=False)
            except ps5.PS5Error:
                if ps5.state_from_status(await ps5.async_get_status(self.host)) == ps5.ASLEEP:
                    return False
                raise
            session = self._device.session
            await session.async_standby()
            # pyremoteplay's own wait loop has an inverted comparison.
            start = time.monotonic()
            while time.monotonic() - start < 5 and not session.is_stopped:
                await asyncio.sleep(0.1)
            self._teardown_session()
            self._emit("disconnected", "PS5 is going into rest mode")
            return True

    async def _watch(self) -> None:
        """pyremoteplay notices the control connection closing, but not a silent network
        drop, so also poll the PS5's status."""
        missed = 0
        while True:
            await asyncio.sleep(WATCH_INTERVAL)
            session = self._device.session if self._device else None
            if session is None:
                return
            if session.is_stopped:
                return self._dropped(session.error or "the PS5 ended the session")
            idle = time.monotonic() - self._last_activity
            if self.game_active:
                idle = 0.0  # a key or stick still held: not idle
            if self.idle_timeout and idle > self.idle_timeout and not self._hold:
                self._watchdog = None  # running inside it: don't cancel ourselves
                self._teardown_session()
                return self._emit("disconnected",
                                  f"Idle for {self.idle_timeout / 60:.0f} min - disconnected")
            state = ps5.state_from_status(await ps5.async_get_status(self.host))
            if state == ps5.AWAKE:
                missed = 0
            elif state == ps5.ASLEEP:
                return self._dropped("the PS5 went into rest mode")
            else:
                missed += 1
                _LOGGER.debug("PS5 didn't answer a status check (%d in a row)", missed)
                if missed >= MISSED_POLLS:
                    return self._dropped("lost contact with the PS5 (network problem?)")

    def _dropped(self, reason: str) -> None:
        self._watchdog = None  # running inside it: don't cancel ourselves
        self._teardown_session()
        self._dropped_recently = True
        self._emit("dropped", f"Session lost: {reason}. The next press will reconnect.")

    def _teardown_session(self) -> None:
        if self._watchdog and self._watchdog is not asyncio.current_task():
            self._watchdog.cancel()
        self._watchdog = None
        if self._keepalive and self._keepalive is not asyncio.current_task():
            self._keepalive.cancel()
        self._keepalive = None
        if self._device:
            # A session is ending: release everything on the PS5 if it can still hear us,
            # and start the next session neutral. (No session: keep what's held, e.g. keys
            # pressed while connecting.)
            self.neutral()
        self._sender = None
        device, self._device = self._device, None
        if self._session_live:
            self._session_live = False
            self.last_session_end = time.monotonic()  # starts the ~9 s busy period
        if device:
            try:
                device.controller.disconnect()
                device.disconnect()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("Error while disconnecting", exc_info=True)

    def close(self) -> None:
        """Safe to call more than once."""
        if self._hold and not self._hold.done():
            self._hold.cancel()
        self._hold = None
        was_connected = self.connected
        self._teardown_session()
        if was_connected:
            self._emit("disconnected", "Disconnected")
