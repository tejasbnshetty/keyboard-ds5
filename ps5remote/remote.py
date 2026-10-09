"""A long-lived Remote Play session for sending controller buttons.

Shared by the command line (press / remote) and the phone server. One Remote object keeps one
session open, wakes the PS5 if needed, notices when the session drops, and reconnects on the
next button press. No video is decoded: pyremoteplay drops the stream to its lowest quality and
discards it.

Events are reported through on_event(kind, message), where kind is one of:
  "progress"      something slow is happening (waking, connecting, retrying)
  "connected"     session ready; message says how long it took
  "dropped"       session lost unexpectedly; the next press reconnects
  "disconnected"  closed on purpose
  "error"         a background action (e.g. hold-to-repeat) failed
  "display"       the PS5 switched to/from protected content (see protected_content)
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from . import config, ps5

_LOGGER = logging.getLogger(__name__)

# Our button names -> pyremoteplay FeedbackEvent.Type names
BUTTONS = {
    "up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT",
    "cross": "CROSS", "circle": "CIRCLE", "triangle": "TRIANGLE", "square": "SQUARE",
    "options": "OPTIONS", "ps": "PS",
    "l1": "L1", "r1": "R1", "l2": "L2", "r2": "R2",
}
REPEATABLE = {"up", "down", "left", "right"}

# How long a tap holds the button down. Tune with --ms; see README "Press timing".
DEFAULT_PRESS_MS = 80
# Hold-to-repeat: first repeat after REPEAT_DELAY, then one tap every REPEAT_INTERVAL.
REPEAT_DELAY = 0.40
REPEAT_INTERVAL = 0.15

WAKE_TIMEOUT = 60.0      # rest mode -> "on" usually takes 10-25 s
READY_TIMEOUT = 15.0     # connected -> stream ready
RETRY_WINDOW = 25.0      # keep retrying a failed connect this long (PS5 still booting, old session)
WATCH_INTERVAL = 2.0     # how often to check the session is still alive
MISSED_POLLS = 2         # unanswered status checks in a row before declaring the session lost


def check_button(name: str) -> str:
    name = name.lower()
    if name not in BUTTONS:
        raise ps5.PS5Error(f"Unknown button '{name}'. Choose from: {', '.join(BUTTONS)}")
    return name


class Remote:
    def __init__(self, press_ms: int = DEFAULT_PRESS_MS,
                 on_event: Callable[[str, str], None] | None = None):
        self.host, self.user = ps5.require_setup()
        self.press_s = press_ms / 1000
        self._on_event = on_event or (lambda kind, msg: None)
        self._device: ps5.Device | None = None
        self._lock = asyncio.Lock()          # one connect / button send at a time
        self._watchdog: asyncio.Task | None = None
        self._hold: asyncio.Task | None = None
        self._dropped_recently = False
        self.last_wake_s: float | None = None
        self.last_connect_s: float | None = None

    # ---- state -----------------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        session = self._device.session if self._device else None
        return bool(session and session.is_ready)

    @property
    def protected_content(self) -> bool | None:
        """True while the PS5 says it's showing content that can't be streamed (e.g. video
        playback in a streaming app), False once it says it can show the picture again,
        None if it hasn't said either since connecting (or not connected)."""
        session = self._device.session if self._device else None
        return getattr(session, "protected_content", None)

    def _emit(self, kind: str, message: str) -> None:
        _LOGGER.debug("%s: %s", kind, message)
        try:
            self._on_event(kind, message)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("on_event callback failed")

    # ---- connecting ------------------------------------------------------------------------

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
        patient = woke or self._dropped_recently
        self._dropped_recently = False
        await self._connect_with_retries(patient)

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
        """Right after waking, or after a dropped session (the PS5 may still be holding the old
        one), the PS5 can refuse connections for a while, so keep retrying for RETRY_WINDOW.
        Otherwise retry once. Never retry refusals that retrying can't fix."""
        start = time.monotonic()
        deadline = start + (RETRY_WINDOW if patient else 0)
        attempt = 0
        self._emit("progress", "Connecting to the PS5...")
        while True:
            attempt += 1
            try:
                await self._open_session()
                self.last_connect_s = time.monotonic() - start
                self._emit("connected", f"Connected in {self.last_connect_s:.1f}s")
                self._watchdog = asyncio.create_task(self._watch())
                return
            except ps5.PS5Error as err:
                if "Another Remote Play session" in str(err):
                    # The PS5 frees a session a few seconds after it ends; worth waiting for.
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
                raise ps5.PS5Error(f"Remote Play connection failed. {ps5.explain(reason or '')}".strip())
            if not await device.async_wait_for_session(READY_TIMEOUT):
                raise ps5.PS5Error(
                    "Connected, but the PS5 never finished starting the session. Close any other "
                    "Remote Play app that's connected to the PS5.")
        except BaseException:
            self._teardown_session()
            raise
        device.controller.start()

    # ---- buttons ---------------------------------------------------------------------------

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
        controller = self._device.controller
        name = BUTTONS[button]
        controller.button(name, "press")
        try:
            await asyncio.sleep(self.press_s)
        finally:
            # Always release, even if cancelled mid-press, so no button is left held down.
            if self.connected:
                controller.button(name, "release")

    async def hold(self, button: str) -> None:
        """Tap now, then keep repeating until stop_hold(). For D-pad scrolling."""
        await self.stop_hold()
        await self.tap(button)
        self._hold = asyncio.create_task(self._repeat(button, time.monotonic() - self.press_s))

    async def _repeat(self, button: str, first_tap: float) -> None:
        try:
            await asyncio.sleep(max(0.0, REPEAT_DELAY - (time.monotonic() - first_tap)))
            while True:
                tick = time.monotonic()
                await self.tap(button)
                await asyncio.sleep(max(0.0, REPEAT_INTERVAL - (time.monotonic() - tick)))
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

    # ---- rest mode -------------------------------------------------------------------------

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
            # pyremoteplay's own wait loop has an inverted comparison, so wait here instead.
            start = time.monotonic()
            while time.monotonic() - start < 5 and not session.is_stopped:
                await asyncio.sleep(0.1)
            self._teardown_session()
            self._emit("disconnected", "PS5 is going into rest mode")
            return True

    # ---- dropped-session detection ---------------------------------------------------------

    async def _watch(self) -> None:
        """The control connection closing (PS5 turned off from its controller, another app
        taking over) is noticed immediately by pyremoteplay. A silent network drop isn't, so
        also poll the PS5's status and give up after a couple of unanswered checks."""
        missed = 0
        while True:
            await asyncio.sleep(WATCH_INTERVAL)
            session = self._device.session if self._device else None
            if session is None:
                return
            if session.is_stopped:
                return self._dropped(session.error or "the PS5 ended the session")
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
        self._watchdog = None  # we're running inside it; don't cancel ourselves
        self._teardown_session()
        self._dropped_recently = True
        self._emit("dropped", f"Session lost: {reason}. The next press will reconnect.")

    # ---- shutting down ---------------------------------------------------------------------

    def _teardown_session(self) -> None:
        if self._watchdog and self._watchdog is not asyncio.current_task():
            self._watchdog.cancel()
        self._watchdog = None
        device, self._device = self._device, None
        if device:
            try:
                device.controller.disconnect()
                # Sends a "disconnect" message to the PS5 so it doesn't keep a stale session.
                device.disconnect()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("Error while disconnecting", exc_info=True)

    def close(self) -> None:
        """Disconnect cleanly. Safe to call from finally blocks and more than once."""
        if self._hold and not self._hold.done():
            self._hold.cancel()
        self._hold = None
        was_connected = self.connected
        self._teardown_session()
        if was_connected:
            self._emit("disconnected", "Disconnected")
