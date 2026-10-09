"""Interactive keyboard remote:  .\\ps5.bat remote

  BROWSE  live remote: stays connected, full buttons, hold-to-repeat, idle disconnect.
  WATCH   BENCHED (see README "Benched: Watch mode"). Only available, via the M key, when
          data/config.json has "features": {"watch_mode": true}.

Windows-only (msvcrt for key presses, GetAsyncKeyState for held keys). All PS5 logic lives in
remote.py and watch.py; this file only maps keys and prints.
"""
from __future__ import annotations

import asyncio
import ctypes
import msvcrt
import time

from . import config, ps5
from .remote import Remote
from .watch import WatchMode, WatchSettings


def watch_mode_enabled() -> bool:
    """Watch mode is benched: off unless explicitly enabled in data/config.json."""
    return bool(config.load().get("features", {}).get("watch_mode", False))

BROWSE, WATCH = "BROWSE", "WATCH"
IDLE_TIMEOUT = 120.0  # Browse mode disconnects after 2 minutes without a press

ARROWS = {"H": "up", "P": "down", "K": "left", "M": "right"}  # codes after a \xe0 / \x00 prefix
BROWSE_KEYS = {
    "\r": "cross", "\x08": "circle", "\x1b": "circle",
    "t": "triangle", "s": "square",
    "p": "ps", "o": "options",
    "q": "l1", "e": "r1", "z": "l2", "c": "r2",
}
QUIT = {"x", "\x03"}  # x or Ctrl+C
VK = {"up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27}
VK_SHIFT = 0x10

HELP = {
    BROWSE: """
BROWSE mode - live remote for menus, games and the home screen. Stays connected.
  Arrow keys  D-pad (hold to scroll)     Enter        Cross (select)
  Backspace   Circle (back)  (Esc too)   T / S        Triangle / Square
  P           PS button                  O            Options
  Q / E       L1 / R1                    Z / C        L2 / R2
  X           quit (Ctrl+C works too)
Disconnects after 2 minutes idle. The first key press connects (and wakes the PS5 if asleep).
""",
    WATCH: """
WATCH mode - for a playing video. Each action connects, presses, and disconnects straight away.
  Space / Enter        play / pause (smart play skips back first when resuming)
  Left / Right         back / forward 10 s
  Shift+Left/Right     back / forward 30 s   ( [ and ] too )
  H                    home (PS button), then back to BROWSE mode
  M                    switch to BROWSE mode    X   quit
Other keys are ignored here, so nothing gets selected blindly.
""",
}


def _key_down(vk: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def _read_key() -> str:
    """Return 'up'/'down'/'left'/'right' for arrows, otherwise the lower-cased character."""
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        return ARROWS.get(msvcrt.getwch(), "")
    return ch.lower()


def _drain_keys() -> None:
    """Throw away keys typed (or auto-repeated) while we were busy, so they don't fire late."""
    while msvcrt.kbhit():
        msvcrt.getwch()


def _stamp() -> str:
    return time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"


class KeyboardRemote:
    def __init__(self, press_ms: int, settings: WatchSettings):
        self.mode = BROWSE
        self.remote = Remote(press_ms=press_ms, on_event=self._on_remote_event,
                             idle_timeout=IDLE_TIMEOUT)
        self.watch = WatchMode(self.remote, settings, on_event=self._on_watch_event)
        self.watch_enabled = watch_mode_enabled()
        self._switch_to_browse = False

    def say(self, message: str, alert: bool = False) -> None:
        print(f"{_stamp()} [{self.mode:<6}] {'!! ' if alert else ''}{message}")

    def _on_remote_event(self, kind: str, message: str) -> None:
        self.say(message, alert=kind in ("dropped", "error"))

    def _on_watch_event(self, kind: str, message: str) -> None:
        if kind == "mode" and message == "browse":
            self._switch_to_browse = True
        elif kind == "queued":
            self.say(f"-> {message}")
        elif kind == "state":
            self.say(f"   video state (best guess): {message.upper()}")
        elif kind == "burst":
            self.say(f"   burst: {message}")
        else:
            self.say(message, alert=kind == "error")

    async def run(self) -> None:
        print(HELP[BROWSE])
        if self.watch_enabled:
            self.say("Watch mode is enabled in config (benched feature): M switches modes. "
                     f"Smart play {self.watch.settings.smart_play_s or 'off'} s, post-wait "
                     f"{self.watch.settings.post_wait_ms} ms.")
        self.say(f"Press duration {self.remote.press_s * 1000:.0f} ms.")
        try:
            while True:
                if self._switch_to_browse:
                    self._switch_to_browse = False
                    await self.set_mode(BROWSE)
                if not msvcrt.kbhit():
                    await asyncio.sleep(0.005)
                    continue
                key = _read_key()
                if key in QUIT:
                    break
                if key == "m" and self.watch_enabled:
                    await self.set_mode(WATCH if self.mode == BROWSE else BROWSE)
                elif self.mode == BROWSE:
                    await self.browse_key(key)
                else:
                    self.watch_key(key)
        finally:
            await self.watch.stop()
            self.remote.close()
            print("Disconnected. Bye.")

    async def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        if mode == WATCH:
            await self.remote.stop_hold()
            self.remote.close()  # drop the live session now so the picture comes back
            self.mode = WATCH
            print(HELP[WATCH])
            self.say("Now in WATCH mode. No session is held open.")
            try:
                await self.watch.enter()
            except ps5.PS5Error as err:
                self.say(f"{err} - switching back to BROWSE.", alert=True)
                self.mode = BROWSE
            else:
                self.say(f"   video state (best guess): {self.watch.play_state.upper()}")
        else:
            if self.watch.busy:
                self.say("Cancelling unsent Watch actions.")
            await self.watch.stop()
            self.mode = BROWSE
            print(HELP[BROWSE])
            self.say("Now in BROWSE mode. The next key press connects.")

    async def browse_key(self, key: str) -> None:
        button = key if key in VK else BROWSE_KEYS.get(key)
        if not button:
            return
        try:
            if button in VK:
                await self._hold_arrow(button)
            else:
                waited = await self.remote.tap(button)
                self.say(f"-> {button}{'  (after connecting)' if waited > 0.5 else ''}")
                if waited > 1:
                    _drain_keys()  # keys mashed while connecting shouldn't fire late
        except ps5.PS5Error as err:
            self.say(str(err), alert=True)
            _drain_keys()

    async def _hold_arrow(self, button: str) -> None:
        start = time.monotonic()
        await self.remote.hold(button)  # taps once now, then repeats while held
        self.say(f"-> {button}{'  (after connecting)' if time.monotonic() - start > 1 else ''}")
        held_from = time.monotonic()
        while _key_down(VK[button]):
            await asyncio.sleep(0.02)
        await self.remote.stop_hold()
        held = time.monotonic() - held_from
        if held > 0.4:
            self.say(f"   (held {button} {held:.1f}s)")
        _drain_keys()  # drop the OS auto-repeat characters that piled up while holding

    def watch_key(self, key: str) -> None:
        if self.watch.app is None:
            return
        shift = _key_down(VK_SHIFT)
        if key in (" ", "\r"):
            self.watch.play_pause()
        elif key == "left":
            self.watch.seek(-30 if shift else -10)
        elif key == "right":
            self.watch.seek(30 if shift else 10)
        elif key == "[":
            self.watch.seek(-30)
        elif key == "]":
            self.watch.seek(30)
        elif key == "h":
            self.watch.home()
        elif key:
            self.say("   (key ignored in WATCH mode - press M for BROWSE)")


async def run(press_ms: int, settings: WatchSettings) -> None:
    await KeyboardRemote(press_ms, settings).run()
