"""Interactive keyboard test mode:  .\\ps5.bat remote

Keeps one Remote Play session open, the way the phone remote will. Windows-only (uses msvcrt for
key presses and GetAsyncKeyState to see when a held arrow key is released).
"""
from __future__ import annotations

import asyncio
import ctypes
import msvcrt
import time

from . import ps5
from .remote import Remote

ARROWS = {"H": "up", "P": "down", "K": "left", "M": "right"}  # codes after a \xe0 / \x00 prefix
KEYS = {
    "\r": "cross", "\x08": "circle", "\x1b": "circle",
    "t": "triangle", "s": "square",
    "p": "ps", "o": "options",
    "q": "l1", "e": "r1", "z": "l2", "c": "r2",
}
QUIT = {"x", "\x03"}  # x or Ctrl+C
VK = {"up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27}

HELP = """
Keyboard remote - keep this window focused.
  Arrow keys  D-pad (hold to scroll)     Enter        Cross (select)
  Backspace   Circle (back)  (Esc too)   T / S        Triangle / Square
  P           PS button                  O            Options
  Q / E       L1 / R1                    Z / C        L2 / R2
  X           quit (Ctrl+C works too)
The first key press connects (and wakes the PS5 if it's asleep).
"""


def _key_down(button: str) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(VK[button]) & 0x8000)


def _read_key() -> str | None:
    """Return a button name, 'quit', or None for an unmapped key."""
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        return ARROWS.get(msvcrt.getwch())
    if ch.lower() in QUIT:
        return "quit"
    return KEYS.get(ch.lower())


def _drain_keys() -> None:
    """Throw away keys typed (or auto-repeated) while we were busy, so they don't fire late."""
    while msvcrt.kbhit():
        msvcrt.getwch()


def _stamp() -> str:
    return time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"


async def run(press_ms: int) -> None:
    def on_event(kind: str, message: str) -> None:
        prefix = {"dropped": "!! ", "error": "!! "}.get(kind, "   ")
        print(f"{_stamp()} {prefix}{message}")

    remote = Remote(press_ms=press_ms, on_event=on_event)
    print(HELP)
    print(f"Press duration: {press_ms} ms (change with --ms)\n")
    try:
        while True:
            if not msvcrt.kbhit():
                await asyncio.sleep(0.005)
                continue
            button = _read_key()
            if button == "quit":
                break
            if button is None:
                continue
            try:
                if button in VK:
                    await _hold_arrow(remote, button)
                else:
                    waited = await remote.tap(button)
                    _report(button, waited)
                    if waited > 1:
                        _drain_keys()  # keys mashed while connecting shouldn't fire late
            except ps5.PS5Error as err:
                print(f"{_stamp()} !! {err}")
                _drain_keys()
    finally:
        remote.close()
        print("Disconnected. Bye.")


async def _hold_arrow(remote: Remote, button: str) -> None:
    start = time.monotonic()
    await remote.hold(button)  # taps once now, then repeats while held
    _report(button, remote.last_connect_s if time.monotonic() - start > 1 else 0)
    held_from = time.monotonic()
    while _key_down(button):
        await asyncio.sleep(0.02)
    await remote.stop_hold()
    held = time.monotonic() - held_from
    if held > 0.4:
        print(f"{_stamp()}    (held {button} {held:.1f}s)")
    _drain_keys()  # drop the OS auto-repeat characters that piled up while holding


def _report(button: str, waited: float | None) -> None:
    note = f"  (after connecting)" if waited and waited > 0.5 else ""
    print(f"{_stamp()} -> {button}{note}")
