"""Local web server behind the app window (and, later, the iPhone page).

Serves the HTML/CSS/JS interface and one WebSocket for live control.

Security model:
- Listens on 127.0.0.1 only, so other devices on the network can't reach it.
- A random token is made each run. The WebSocket requires it (constant-time compare), and the
  window is opened with it. Other local programs and web pages don't know it.
- The Host header must be 127.0.0.1/localhost:<port> (blocks DNS-rebinding attacks), and the
  WebSocket's Origin must be this server (blocks other websites in your browser).
- Strict Content-Security-Policy, no external resources, no referrer, and no access log (the
  page URL carries the token).
- Credentials (PSN account ID, pairing keys) are never sent to the interface.

WebSocket messages, client -> server (JSON):
  hello | press {button} | hold {button} | release {button} | wake | rest | disconnect
  save_settings {settings} | save_keymaps {keymaps} | reset_keymaps
Server -> client:
  init {settings, keymaps, buttons, repeatable} | status {...} | event {kind, message}
  settings {settings} | keymaps {keymaps} | error {message}
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
from ..remote import BUTTONS, REPEATABLE, Remote
from ..settings import AppSettings

_LOGGER = logging.getLogger(__name__)

# In the .exe, PyInstaller unpacks the web files to <_MEIPASS>/web (see ps5remote.spec).
WEB_DIR = config.RESOURCES / "web" if getattr(sys, "frozen", False) else Path(__file__).resolve().parent / "web"
STATUS_POLL_S = 3.0          # how often to ask the PS5 for its status
TICK_S = 0.5                 # how often to push connection / countdown changes
MAX_MESSAGE_BYTES = 64 * 1024
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class AppServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
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

    # ---- setup -----------------------------------------------------------------------------

    def _make_remote(self) -> None:
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

    # ---- HTTP ------------------------------------------------------------------------------

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

    # ---- WebSocket -------------------------------------------------------------------------

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
        if kind == "hello":
            await self._send(ws, {"type": "init", "settings": self.settings.to_dict(),
                                  "keymaps": self.keymaps, "buttons": list(BUTTONS),
                                  "repeatable": sorted(REPEATABLE)})
            await self._send(ws, {"type": "status", **self._status_payload()})
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
            await self._broadcast({"type": "keymaps", "keymaps": self.keymaps})
            await self._event("info", "Key maps reset to defaults.")
        else:
            await self._send(ws, {"type": "error", "message": "Unknown message"})

    # ---- actions ---------------------------------------------------------------------------

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
            await self._event("error", str(err))
        finally:
            self._status["busy"] = ""
            await self._push_status()

    async def _press(self, button: str) -> None:
        try:
            await self._need_remote().tap(button)
        except ps5.PS5Error as err:
            await self._event("error", str(err))

    async def _hold(self, button: str) -> None:
        self._held = button
        try:
            remote = self._need_remote()
            await remote.hold(button)
            if self._held != button:  # released while we were still connecting
                await remote.stop_hold()
        except ps5.PS5Error as err:
            self._held = None
            await self._event("error", str(err))

    async def _release(self, button: str | None = None) -> None:
        if button is None or self._held == button:
            self._held = None
            if self.remote:
                await self.remote.stop_hold()

    async def _wake(self) -> None:
        async def go():
            woke = await self._need_remote().wake()
            await self._event("info", "PS5 is awake." if woke else "PS5 was already awake.")
        await self._guarded(go(), "Waking the PS5...")
        await self._refresh_status()

    async def _rest(self) -> None:
        async def go():
            if await self._need_remote().standby():
                await self._event("info", "Rest mode requested.")
            else:
                await self._event("info", "The PS5 is already asleep.")
        await self._guarded(go(), "Putting the PS5 into rest mode...")
        await self._refresh_status()

    async def _save_settings(self, data) -> None:
        try:
            new = AppSettings.from_dict(data if isinstance(data, dict) else {})
            if new.profile_hotkey in self._all_bound_keys():
                raise ValueError(f"{new.profile_hotkey} is already used in a key map.")
        except ValueError as err:
            return await self._event("error", f"Settings not saved: {err}")
        self.settings = new
        new.save()
        self._apply_settings()
        await self._broadcast({"type": "settings", "settings": new.to_dict()})
        await self._event("info", "Settings saved.")

    def _all_bound_keys(self) -> set[str]:
        return {k for p in self.keymaps["profiles"].values() for k in p.values() if k}

    async def _save_keymaps(self, data) -> None:
        try:
            clean = keymaps.validate(data, {self.settings.profile_hotkey})
        except ValueError as err:
            return await self._event("error", f"Key maps not saved: {err}")
        self.keymaps = clean
        keymaps.save(clean)
        await self._broadcast({"type": "keymaps", "keymaps": clean})

    # ---- status ----------------------------------------------------------------------------

    def _on_remote_event(self, kind: str, message: str) -> None:
        self._spawn(self._event(kind, message))
        self._spawn(self._push_status())

    async def _event(self, kind: str, message: str) -> None:
        await self._broadcast({"type": "event", "kind": kind, "message": message,
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
        await self._broadcast({"type": "status", **self._status_payload()})

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
                    await self._broadcast({"type": "status", **payload})
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Status poll failed")
            await asyncio.sleep(TICK_S)

    # ---- sending ---------------------------------------------------------------------------

    async def _send(self, ws: web.WebSocketResponse, payload: dict) -> None:
        if not ws.closed:
            await ws.send_str(json.dumps(payload))

    async def _broadcast(self, payload: dict) -> None:
        for ws in list(self.clients):
            try:
                await self._send(ws, payload)
            except (ConnectionError, RuntimeError):
                self.clients.discard(ws)
