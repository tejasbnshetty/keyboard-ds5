"""PS5 operations built on pyremoteplay: discover, status, pair, wake.

The Remote Play session used for buttons and rest mode lives in remote.py.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import threading

from pyremoteplay import ddp
from pyremoteplay.device import RPDevice

from . import config
from .rpsession import FastSession

_LOGGER = logging.getLogger(__name__)

# State names shown to the user
UNREACHABLE = "unreachable"
ASLEEP = "asleep"
AWAKE = "awake"


class PS5Error(Exception):
    pass


class SessionBusy(PS5Error):
    """The PS5 refused a new session because the previous one hasn't been freed yet.
    It takes ~9 s after any session ends, however cleanly it ended."""


# Remote Play rejection codes (RP-Application-Reason) that pyremoteplay doesn't name.
REJECT_HINTS = {
    0x80108B12: (
        "The PS5 refused the connection because Remote Play isn't enabled for your account. "
        "On the PS5: Settings > System > Remote Play > turn on 'Enable Remote Play' "
        "(and the switch next to your user, if shown)."
    ),
    0x80108B10: "Another Remote Play app is already connected to the PS5. Close it and try again.",
    0x80108B15: "Remote Play crashed on the PS5. Restart the PS5 and try again.",
    0x80108B02: "This PSN account isn't a user on that PS5. Run .\\ps5.bat login with the right account.",
}
# Rejections that retrying won't fix.
FATAL_CODES = {0x80108B12, 0x80108B02}


def explain(reason: str) -> str:
    for code, hint in REJECT_HINTS.items():
        if str(code) in reason:
            return f"{hint} (code {code:#x})"
    return reason


def is_fatal(reason: str) -> bool:
    return any(str(code) in reason for code in FATAL_CODES)


def use_windows_event_loop() -> None:
    """pyremoteplay's sockets need the selector event loop on Windows (its own GUI does this)."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def quiet_library_logs(verbose: bool = False) -> None:
    """pyremoteplay logs pairing keys at DEBUG level, so never let it go below INFO."""
    logging.getLogger("pyremoteplay").setLevel(logging.INFO if verbose else logging.WARNING)


class Device(RPDevice):
    """RPDevice that skips the PlayStation Store lookup pyremoteplay does whenever a game is
    running (an internet request we don't need, which also misbehaves outside an event loop)."""

    def _set_status(self, data: dict):
        if data:
            data = {k: v for k, v in data.items() if k != "running-app-titleid"}
        super()._set_status(data)

    def create_session(self, user: str, profiles=None, **_ignored):
        """Like RPDevice.create_session, but with our patched session (see rpsession.py)."""
        if self.session and not self.session.is_stopped:
            _LOGGER.error("Running session already exists. Disconnect first.")
            return None
        profile = self.get_profile(user, profiles)
        if not profile:
            return None
        self._session = FastSession(self.host, profile)  # no receiver: video is discarded
        self.controller.disconnect()
        self.controller.connect(self._session)
        return self._session


def discover(timeout: int = 3) -> list[dict]:
    """Broadcast on the local network and return PS5 status dicts."""
    found = ddp.search(timeout=timeout)
    return [d for d in found if d.get("host-type", "").upper() == "PS5"]


# Status queries bind local UDP port 9303 (the PS5 expects it), so run them one at a time.
_status_lock = threading.Lock()


def get_status(host: str) -> dict:
    """Return the console's discovery status, or {} if it didn't answer."""
    with _status_lock:
        return ddp.get_status(host) or {}


async def async_get_status(host: str) -> dict:
    return await asyncio.to_thread(get_status, host)


def state_from_status(status: dict) -> str:
    if not status:
        return UNREACHABLE
    return AWAKE if status.get("status-code") == ddp.STATUS_OK else ASLEEP


def _device(host: str) -> Device:
    device = Device(host)
    with _status_lock:
        found = device.get_status()
    if not found:
        raise PS5Error(
            f"No PS5 answered at {host}. Check the IP address, that the PS5 is on or in rest "
            "mode, and that this PC is on the same network."
        )
    return device


def require_setup() -> tuple[str, str]:
    cfg = config.load()
    host, user = cfg.get("ps5_host"), cfg.get("psn_user")
    if not host:
        raise PS5Error("No PS5 address saved yet. Run:  .\\ps5.bat discover")
    if not user:
        raise PS5Error("Not signed in to PSN yet. Run:  .\\ps5.bat login")
    return host, user


def require_paired(device: RPDevice, user: str, profiles) -> None:
    if user not in device.get_users(profiles=profiles):
        raise PS5Error("This PC isn't paired with the PS5 yet. Run:  .\\ps5.bat pair")


def pair(pin: str) -> None:
    host, user = require_setup()
    profiles = config.profiles()
    device = _device(host)
    if not device.is_on:
        raise PS5Error("The PS5 must be fully on (not in rest mode) to pair.")
    profile = device.register(user, pin, timeout=5.0, profiles=profiles, save=False)
    if not profile:
        raise PS5Error(
            "Pairing failed. Make sure the 'Link Device' screen with the PIN is still open on "
            "the PS5 and the PIN is typed exactly (8 digits). The PIN changes each time."
        )
    config.save_profiles(profiles)


def send_wake() -> bool:
    """Send the wake packet. Returns False if the PS5 was already awake. Doesn't wait."""
    host, user = require_setup()
    profiles = config.profiles()
    device = _device(host)
    if device.is_on:
        return False
    require_paired(device, user, profiles)
    device.wakeup(user, profiles=profiles)
    return True


def wake(timeout: float = 45.0) -> bool:
    """Wake the PS5 and wait until it reports it's on."""
    host, _ = require_setup()
    send_wake()
    device = Device(host)
    with _status_lock:
        return device.wait_for_wakeup(timeout)
