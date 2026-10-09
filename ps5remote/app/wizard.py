# SPDX-License-Identifier: AGPL-3.0-only
"""Setup wizard, server side: find the PS5, sign in to PSN, pair.

Nothing is written until pairing succeeds, so an abandoned or failed re-pair leaves the
existing pairing untouched. The account ID never leaves the server.
"""
from __future__ import annotations

import asyncio
import json
import logging
import webbrowser
from typing import TYPE_CHECKING, Callable

from .. import config, ps5, psn

if TYPE_CHECKING:
    from .server import AppServer

_LOGGER = logging.getLogger(__name__)


class SetupWizard:
    def __init__(self, server: "AppServer", open_login: Callable | None, force: bool = False):
        self.server = server
        # open_login(url, on_result) calls on_result(redirect or None) from any thread.
        # None in --browser mode.
        self.open_login = open_login
        self.active = force or not config.is_paired()
        self.mode = "full"
        self._reset()

    def _reset(self) -> None:
        self.consoles: list[dict] = []
        self.console: dict | None = None
        self.signed_in: str | None = None
        self._pending_account_id: str | None = None  # new sign-in, not saved until paired
        self.busy = ""
        self.error = ""
        self.paired = False
        self.login_window_open = False
        self.paste_needed = False

    def existing_account(self) -> str | None:
        # Read the file directly: config.profiles() would create an empty profiles.json.
        user = config.load().get("psn_user")
        if not user or not config.PROFILES_FILE.is_file():
            return None
        try:
            data = json.loads(config.PROFILES_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return user if isinstance(data, dict) and user in data else None

    def public_state(self) -> dict:
        migration = config.migration_source()
        return {
            "active": self.active,
            "mode": self.mode,
            "can_cancel": config.is_paired(),
            "consoles": self.consoles,
            "console": self.console,
            "signed_in": self.signed_in,
            "existing_account": self.existing_account(),
            "current_ps5": config.load().get("ps5_host") if config.is_paired() else None,
            "psn_configured": psn.is_configured(),
            "embedded_login": self.open_login is not None,
            "login_window_open": self.login_window_open,
            "paste_needed": self.paste_needed,
            "paired": self.paired,
            "busy": self.busy,
            "error": self.error,
            "migration": str(migration) if migration else None,
            "data_dir": str(config.DATA_DIR),
        }

    async def push(self) -> None:
        await self.server.broadcast({"type": "setup", **self.public_state()})

    async def handle(self, kind: str, data: dict) -> None:
        handlers = {
            "setup_start": self._start, "setup_cancel": self._cancel,
            "setup_discover": self._discover, "setup_use_console": self._use_console,
            "setup_psn_open": self._psn_open, "setup_psn_paste": self._psn_paste,
            "setup_psn_keep": self._psn_keep, "setup_pair": self._pair,
            "setup_finish": self._finish, "migrate": self._migrate, "forget_all": self._forget,
        }
        handler = handlers.get(kind)
        if handler:
            self.error = ""
            await handler(data)
            await self.push()

    async def _busy(self, label: str, coro):
        self.busy, self.error = label, ""
        await self.push()
        try:
            return await coro
        except (ps5.PS5Error, psn.PSNError) as err:
            self.error = str(err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.exception("Setup step failed")
            self.error = f"Something went wrong ({err.__class__.__name__}). Try again."
        finally:
            self.busy = ""
        return None

    async def _start(self, data: dict) -> None:
        self._reset()
        self.mode = "repair" if data.get("mode") == "repair" else "full"
        self.active = True

    async def _cancel(self, _data: dict) -> None:
        if config.is_paired():
            self._reset()
            self.active = False

    async def _discover(self, _data: dict) -> None:
        async def go():
            found = await asyncio.to_thread(ps5.discover)
            self.consoles = [{"ip": d.get("host-ip"), "name": d.get("host-name", "PS5"),
                              "state": ps5.state_from_status(d)} for d in found if d.get("host-ip")]
            if not self.consoles:
                self.error = ("No PS5 found. Make sure it's fully on (or in rest mode with 'Stay "
                              "Connected to the Internet'), on the same network, then search "
                              "again - or enter its IP address below.")
        await self._busy("Searching the network for a PS5 (3 s)...", go())

    async def _use_console(self, data: dict) -> None:
        ip = str(data.get("ip", "")).strip()
        if not ps5.is_ipv4(ip):
            self.error = f"'{ip}' isn't a valid IP address (it looks like 192.168.1.50)."
            return

        async def go():
            status = await ps5.async_get_status(ip)
            if not status:
                raise ps5.PS5Error(f"Nothing answered at {ip}. Check the address on the PS5: "
                                   "Settings > Network > Connection Status > View Connection Status.")
            if status.get("host-type", "").upper() != "PS5":
                raise ps5.PS5Error(f"The console at {ip} isn't a PS5.")
            self.console = {"ip": ip, "name": status.get("host-name", "PS5"),
                            "state": ps5.state_from_status(status)}
        await self._busy("Checking the PS5...", go())

    async def _psn_open(self, _data: dict) -> None:
        try:
            url = psn.login_url()
        except psn.PSNError as err:
            self.error = str(err)
            return
        loop = asyncio.get_running_loop()
        if self.open_login:
            def on_result(redirect: str | None) -> None:  # called from a GUI thread
                loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._login_done(redirect)))
            self.login_window_open = True
            self.open_login(url, on_result)
        else:
            webbrowser.open(url)
            self.paste_needed = True

    async def _login_done(self, redirect: str | None) -> None:
        self.login_window_open = False
        if redirect:
            await self._exchange(redirect)
        else:
            self.paste_needed = True  # window closed without finishing
        await self.push()

    async def _psn_paste(self, data: dict) -> None:
        await self._exchange(str(data.get("url", "")))

    async def _exchange(self, text: str) -> None:
        async def go():
            code = psn.extract_code(text)
            online_id, account_id = await asyncio.to_thread(psn.fetch_account, code)
            self.signed_in, self._pending_account_id = online_id, account_id
            self.paste_needed = False
        await self._busy("Signing in...", go())

    async def _psn_keep(self, _data: dict) -> None:
        existing = self.existing_account()
        if existing:
            self.signed_in, self._pending_account_id = existing, None

    async def _pair(self, data: dict) -> None:
        pin = "".join(ch for ch in str(data.get("pin", "")) if ch.isdigit())
        if not self.console:
            self.error = "Choose a PS5 first (step 1)."
            return
        if not self.signed_in:
            self.error = "Sign in to PSN first (step 2)."
            return

        async def go():
            await asyncio.to_thread(ps5.pair_console, self.console["ip"], self.signed_in,
                                    pin, self._pending_account_id)
            self._pending_account_id = None
            self.paired = True
            self.server.reload_remote()
        await self._busy("Pairing with the PS5...", go())

    async def _finish(self, _data: dict) -> None:
        if config.is_paired():
            self._reset()
            self.active = False

    async def _migrate(self, data: dict) -> None:
        source = config.migration_source()
        if not source:
            return
        if data.get("accept"):
            copied = config.migrate_from(source)
            await self.server.event("info", f"Copied {', '.join(copied)} into {config.DATA_DIR}.")
            if config.is_paired():
                self.active = False
                self.server.reload_remote()
        else:
            config.decline_migration()

    async def _forget(self, _data: dict) -> None:
        self.server.forget_pairing()
        self._reset()
        self.active = True
        self.mode = "full"
        await self.server.event("info", "Signed out. Pairing data deleted.")
