# SPDX-License-Identifier: AGPL-3.0-only
"""Local web server behind the app window: the interface plus one JSON WebSocket.

Security: listens on 127.0.0.1 only; the WebSocket needs this run's random token and this
server's Origin; the Host header must be local (blocks DNS rebinding); strict CSP; no access
log (URLs carry the token). Credentials are never sent to the interface.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import sys
import time
from pathlib import Path

from aiohttp import WSMsgType, web

from .. import appmaps, config, keymaps, ps5, rpsession
from .wizard import SetupWizard
from ..remote import BUTTONS, REPEATABLE, Remote
from ..settings import AppSettings

_LOGGER = logging.getLogger(__name__)

# In the .exe, PyInstaller unpacks the web files to <_MEIPASS>/web (see ps5remote.spec).
WEB_DIR = config.RESOURCES / "web" if getattr(sys, "frozen", False) else Path(__file__).resolve().parent / "web"
STATUS_POLL_S = 3.0
TICK_S = 0.5
MAX_MESSAGE_BYTES = 64 * 1024
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class AppServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0, open_login=None,
                 force_setup: bool = False):
        self.host = host
        self.port = port
        self.token = secrets.token_urlsafe(32)
        self.settings = AppSettings.load()
        self.keymaps = keymaps.load({self.settings.profile_hotkey})
        self.clients: set[web.WebSocketResponse] = set()
        self.remote: Remote | None = None
        self.setup_error = ""
        self._held: str | None = None
        self._tasks: set[asyncio.Task] = set()
        self._status = {"power": "unknown", "app": "", "connected": False,
                        "free_in": 0, "streaming_app": "", "busy": ""}
        self._runner: web.AppRunner | None = None
        self._poller: asyncio.Task | None = None
        self._make_remote()
        self.wizard = SetupWizard(self, open_login, force=force_setup)

    def _make_remote(self) -> None:
        if not config.is_paired():
            self.remote, self.setup_error = None, "Not set up yet."
            return
        try:
            self.remote = Remote(press_ms=self.settings.press_ms, on_event=self._on_remote_event)
        except ps5.PS5Error as err:
            self.remote, self.setup_error = None, str(err)
            return
        self._apply_settings()

    def _apply_settings(self) -> None:
        s = self.settings
        rpsession.EARLY_SESSION_ID = None if s.safe_connect else 0.3
        if self.remote:
            self.remote.press_s = s.press_ms / 1000
            self.remote.idle_timeout = s.idle_timeout_min * 60 or None
            self.remote.repeat_delay = s.repeat_delay_ms / 1000
            self.remote.repeat_interval = s.repeat_interval_ms / 1000

    def reload_remote(self) -> None:
        """Start using a new pairing (after pairing or copying old data)."""
        if self.remote:
            self.remote.close()
        self._make_remote()
        self._spawn(self._refresh_and_push())

    def forget_pairing(self) -> None:
        """Deletes pairing keys, account ID and PS5 address; keeps settings and key maps."""
        if self.remote:
            self.remote.close()
        self.remote, self.setup_error = None, "Not set up yet."
        if config.PROFILES_FILE.exists():
            config.PROFILES_FILE.unlink()
        config.remove_keys("ps5_host", "psn_user")
        self._status.update(power="unknown", app="", streaming_app="")

    async def _refresh_and_push(self) -> None:
        await self._refresh_status()
        await self._push_status()

    @staticmethod
    def build_info() -> dict:
        personal = config.FROZEN and (config.RESOURCES / "PERSONAL_BUILD.txt").exists()
        return {"personal": personal, "frozen": config.FROZEN}

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={self.token}"

    async def start(self) -> str:
        app = web.Application(middlewares=[self._guard], client_max_size=MAX_MESSAGE_BYTES)
        app.router.add_get("/", self._index)
        app.router.add_get("/ws", self._ws)
        app.router.add_static("/static/", WEB_DIR, follow_symlinks=False)
        self._runner = web.AppRunner(app, access_log=None)  # the page URL contains the token
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # pylint: disable=protected-access
        self._poller = asyncio.create_task(self._poll())
        _LOGGER.info("App server listening on %s:%s", self.host, self.port)  # no token
        return self.url

    async def stop(self) -> None:
        if self._poller:
            self._poller.cancel()
        for task in list(self._tasks):
            task.cancel()
        if self.remote:
            self.remote.close()
        for ws in list(self.clients):
            await ws.close()
        if self._runner:
            await self._runner.cleanup()

    @web.middleware
    async def _guard(self, request: web.Request, handler):
        allowed = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        if request.host not in allowed:
            return web.Response(status=403, text="Forbidden")
        response = await handler(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    async def _index(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(WEB_DIR / "index.html")

    def _authorised(self, request: web.Request) -> bool:
        token = request.query.get("token", "")
        origin = request.headers.get("Origin", "")
        good_origin = origin in (f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}")
        return good_origin and secrets.compare_digest(token, self.token)

    async def _ws(self, request: web.Request) -> web.StreamResponse:
        if not self._authorised(request):
            return web.Response(status=403, text="Forbidden")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=MAX_MESSAGE_BYTES)
        await ws.prepare(request)
        self.clients.add(ws)
        _LOGGER.info("Interface connected (%d open)", len(self.clients))
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                    if not isinstance(data, dict):
                        raise ValueError
                except ValueError:
                    await self._send(ws, {"type": "error", "message": "Bad message"})
                    continue
                await self._handle(ws, data)
        finally:
            self.clients.discard(ws)
            if not self.clients:
                await self._release()  # window closed mid-hold: never leave a button held
        return ws

    async def _handle(self, ws: web.WebSocketResponse, data: dict) -> None:
        kind = data.get("type")
        if not isinstance(kind, str):
            return await self._send(ws, {"type": "error", "message": "Unknown message"})
        if kind == "hello":
            await self._send(ws, {"type": "init", "settings": self.settings.to_dict(),
                                  "keymaps": self.keymaps, "buttons": list(BUTTONS),
                                  "repeatable": sorted(REPEATABLE), "build": self.build_info()})
            await self._send(ws, {"type": "setup", **self.wizard.public_state()})
            await self._send(ws, {"type": "status", **self._status_payload()})
        elif kind.startswith("setup_") or kind in ("migrate", "forget_all"):
            await self.wizard.handle(kind, data)
        elif kind in ("press", "hold", "release"):
            button = data.get("button")
            if button not in BUTTONS:
                return await self._send(ws, {"type": "error", "message": "Unknown button"})
            if kind == "press":
                self._spawn(self._press(button))
            elif kind == "hold":
                self._spawn(self._hold(button))
            else:
                await self._release(button)
        elif kind == "wake":
            self._spawn(self._wake())
        elif kind == "rest":
            self._spawn(self._rest())
        elif kind == "disconnect":
            await self._release()
            if self.remote:
                self.remote.close()
        elif kind == "save_settings":
            await self._save_settings(data.get("settings"))
        elif kind == "save_keymaps":
            await self._save_keymaps(data.get("keymaps"))
        elif kind == "reset_keymaps":
            self.keymaps = keymaps.defaults()
            keymaps.save(self.keymaps)
            await self.broadcast({"type": "keymaps", "keymaps": self.keymaps})
            await self.event("info", "Key maps reset to defaults.")
        else:
            await self._send(ws, {"type": "error", "message": "Unknown message"})

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _need_remote(self) -> Remote:
        if not self.remote:
            raise ps5.PS5Error(self.setup_error or "Not set up yet.")
        return self.remote

    async def _guarded(self, action, busy_label: str):
        self._status["busy"] = busy_label
        await self._push_status()
        try:
            return await action
        except ps5.PS5Error as err:
            await self.event("error", str(err))
        finally:
            self._status["busy"] = ""
            await self._push_status()

    async def _press(self, button: str) -> None:
        try:
            await self._need_remote().tap(button)
        except ps5.PS5Error as err:
            await self.event("error", str(err))

    async def _hold(self, button: str) -> None:
        self._held = button
        try:
            remote = self._need_remote()
            await remote.hold(button)
            if self._held != button:  # released while we were still connecting
                await remote.stop_hold()
        except ps5.PS5Error as err:
            self._held = None
            await self.event("error", str(err))

    async def _release(self, button: str | None = None) -> None:
        if button is None or self._held == button:
            self._held = None
            if self.remote:
                await self.remote.stop_hold()

    async def _wake(self) -> None:
        async def go():
            woke = await self._need_remote().wake()
            await self.event("info", "PS5 is awake." if woke else "PS5 was already awake.")
        await self._guarded(go(), "Waking the PS5...")
        await self._refresh_status()

    async def _rest(self) -> None:
        async def go():
            if await self._need_remote().standby():
                await self.event("info", "Rest mode requested.")
            else:
                await self.event("info", "The PS5 is already asleep.")
        await self._guarded(go(), "Putting the PS5 into rest mode...")
        await self._refresh_status()

    async def _save_settings(self, data) -> None:
        try:
            new = AppSettings.from_dict(data if isinstance(data, dict) else {})
            if new.profile_hotkey in self._all_bound_keys():
                raise ValueError(f"{new.profile_hotkey} is already used in a key map.")
        except ValueError as err:
            return await self.event("error", f"Settings not saved: {err}")
        self.settings = new
        new.save()
        self._apply_settings()
        await self.broadcast({"type": "settings", "settings": new.to_dict()})
        await self.event("info", "Settings saved.")

    def _all_bound_keys(self) -> set[str]:
        return {k for p in self.keymaps["profiles"].values() for k in p.values() if k}

    async def _save_keymaps(self, data) -> None:
        try:
            clean = keymaps.validate(data, {self.settings.profile_hotkey})
        except ValueError as err:
            return await self.event("error", f"Key maps not saved: {err}")
        self.keymaps = clean
        keymaps.save(clean)
        await self.broadcast({"type": "keymaps", "keymaps": clean})

    def _on_remote_event(self, kind: str, message: str) -> None:
        self._spawn(self.event(kind, message))
        self._spawn(self._push_status())

    async def event(self, kind: str, message: str) -> None:
        await self.broadcast({"type": "event", "kind": kind, "message": message,
                               "time": time.strftime("%H:%M:%S")})

    def _status_payload(self) -> dict:
        s = dict(self._status)
        if not self.remote:
            s.update(power="setup_needed", setup_error=self.setup_error)
        else:
            s["connected"] = self.remote.connected
            s["free_in"] = round(self.remote.free_in)
        return s

    async def _push_status(self) -> None:
        await self.broadcast({"type": "status", **self._status_payload()})

    async def _refresh_status(self) -> None:
        if not self.remote:
            return
        status = await ps5.async_get_status(self.remote.host)
        power = ps5.state_from_status(status)
        self._status["power"] = {"awake": "on"}.get(power, power)
        self._status["app"] = (status.get("running-app-name") or "").strip()
        try:
            found = appmaps.find_streaming_app(status)
        except (OSError, ValueError, KeyError):
            found = None
        self._status["streaming_app"] = found.name if found else ""

    async def _poll(self) -> None:
        last_poll, last_sent = 0.0, None
        while True:
            try:
                if time.monotonic() - last_poll >= STATUS_POLL_S:
                    last_poll = time.monotonic()
                    await self._refresh_status()
                payload = self._status_payload()
                if payload != last_sent:
                    last_sent = payload
                    await self.broadcast({"type": "status", **payload})
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Status poll failed")
            await asyncio.sleep(TICK_S)

    async def _send(self, ws: web.WebSocketResponse, payload: dict) -> None:
        if not ws.closed:
            await ws.send_str(json.dumps(payload))

    async def broadcast(self, payload: dict) -> None:
        for ws in list(self.clients):
            try:
                await self._send(ws, payload)
            except (ConnectionError, RuntimeError):
                self.clients.discard(ws)
