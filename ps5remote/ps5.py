"""PS5 operations built on pyremoteplay: discover, status, pair, wake, standby, buttons."""
from __future__ import annotations

import asyncio
import logging
import sys
import time

from pyremoteplay import ddp
from pyremoteplay.device import RPDevice

from . import config

_LOGGER = logging.getLogger(__name__)

# State names shown to the user
UNREACHABLE = "unreachable"
ASLEEP = "asleep"
AWAKE = "awake"
CONNECTED = "connected"


class PS5Error(Exception):
    pass


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


def _explain(reason: str) -> str:
    for code, hint in REJECT_HINTS.items():
        if str(code) in reason:
            return f"{hint} (code {code:#x})"
    return reason


def use_windows_event_loop() -> None:
    """pyremoteplay's sockets need the selector event loop on Windows (its own GUI does this)."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def quiet_library_logs(verbose: bool = False) -> None:
    """pyremoteplay logs pairing keys at DEBUG level, so never let it go below INFO."""
    logging.getLogger("pyremoteplay").setLevel(logging.INFO if verbose else logging.WARNING)


def discover(timeout: int = 3) -> list[dict]:
    """Broadcast on the local network and return PS5 status dicts."""
    found = ddp.search(timeout=timeout)
    return [d for d in found if d.get("host-type", "").upper() == "PS5"]


def get_status(host: str) -> dict:
    """Return the console's discovery status, or {} if it didn't answer."""
    return ddp.get_status(host) or {}


def state_from_status(status: dict) -> str:
    if not status:
        return UNREACHABLE
    return AWAKE if status.get("status-code") == ddp.STATUS_OK else ASLEEP


def _device(host: str) -> RPDevice:
    device = RPDevice(host)
    if not device.get_status():
        raise PS5Error(
            f"No PS5 answered at {host}. Check the IP address, that the PS5 is on or in rest "
            "mode, and that this PC is on the same network."
        )
    return device


def _require_setup() -> tuple[str, str]:
    cfg = config.load()
    host, user = cfg.get("ps5_host"), cfg.get("psn_user")
    if not host:
        raise PS5Error("No PS5 address saved yet. Run:  .\\ps5.bat discover")
    if not user:
        raise PS5Error("Not signed in to PSN yet. Run:  .\\ps5.bat login")
    return host, user


def _require_paired(device: RPDevice, user: str, profiles) -> None:
    if user not in device.get_users(profiles=profiles):
        raise PS5Error("This PC isn't paired with the PS5 yet. Run:  .\\ps5.bat pair")


def pair(pin: str) -> None:
    host, user = _require_setup()
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


def wake(wait: bool = True, timeout: float = 45.0) -> bool:
    """Send the wake packet. Returns True once the PS5 reports it's on (or immediately if wait=False)."""
    host, user = _require_setup()
    profiles = config.profiles()
    device = _device(host)
    if device.is_on:
        return True
    _require_paired(device, user, profiles)
    device.wakeup(user, profiles=profiles)
    if not wait:
        return True
    return device.wait_for_wakeup(timeout)


class Remote:
    """A Remote Play session used only for sending buttons (no video is decoded)."""

    READY_TIMEOUT = 15.0

    def __init__(self):
        self.host, self.user = _require_setup()
        self.device: RPDevice | None = None

    @property
    def connected(self) -> bool:
        return bool(self.device and self.device.connected and self.device.ready)

    async def connect(self) -> None:
        if self.connected:
            return
        self.disconnect()
        profiles = config.profiles()
        device = RPDevice(self.host)
        if not await device.async_get_status():
            raise PS5Error(f"No PS5 answered at {self.host}.")
        if not device.is_on:
            raise PS5Error("The PS5 is in rest mode. Wake it first.")
        _require_paired(device, self.user, profiles)
        if not device.create_session(self.user, profiles=profiles):
            raise PS5Error("Couldn't create a Remote Play session.")
        self.device = device
        if not await device.connect():
            reason = device.session.error if device.session else ""
            self.disconnect()
            raise PS5Error(f"Remote Play connection failed. {_explain(reason or '')}".strip())
        if not await device.async_wait_for_session(self.READY_TIMEOUT):
            self.disconnect()
            raise PS5Error(
                "Connected, but the PS5 never finished starting the session. Close any other "
                "Remote Play app (phone, PC) that's connected to the PS5 and try again."
            )
        device.controller.start()

    def disconnect(self) -> None:
        if self.device:
            try:
                self.device.controller.disconnect()
                self.device.disconnect()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("Error while disconnecting", exc_info=True)
        self.device = None

    async def press(self, button: str, action: str = "tap") -> None:
        """action: 'tap', 'press' (hold down) or 'release'."""
        await self.connect()
        await self.device.controller.async_button(button, action)

    async def standby(self) -> None:
        await self.connect()
        session = self.device.session
        await session.async_standby()
        # pyremoteplay's own wait loop has an inverted comparison, so wait here instead.
        start = time.time()
        while time.time() - start < 5 and not session.is_stopped:
            await asyncio.sleep(0.1)
        self.disconnect()


async def standby() -> bool:
    """Put the PS5 into rest mode. Returns False if it was already asleep."""
    host, _ = _require_setup()
    if state_from_status(get_status(host)) != AWAKE:
        return False
    remote = Remote()
    try:
        await remote.standby()
    finally:
        remote.disconnect()
    return True
