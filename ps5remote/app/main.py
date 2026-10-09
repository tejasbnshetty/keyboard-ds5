"""Windows app entry point: start the local server, then open it in a pywebview window.

Run with app.bat (no console window), or `python -m ps5remote.app` to see log output.
"""
from __future__ import annotations

import asyncio
import logging
import logging.handlers
import sys
import threading

from .. import config, ps5
from .server import AppServer

_LOGGER = logging.getLogger(__name__)


def setup_logging() -> None:
    config.LOG_DIR.mkdir(exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        config.LOG_DIR / "app.log", maxBytes=512_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr and not getattr(sys, "frozen", False):
        root.addHandler(logging.StreamHandler())
    ps5.quiet_library_logs()                         # pyremoteplay logs keys at DEBUG
    logging.getLogger("aiohttp.access").disabled = True  # URLs carry the session token


def main() -> None:
    import webview  # imported here so the server can be tested without a GUI

    setup_logging()
    ps5.use_windows_event_loop()
    loop = asyncio.new_event_loop()
    server = AppServer()
    started = threading.Event()
    result: dict = {}

    def serve() -> None:
        asyncio.set_event_loop(loop)
        try:
            result["url"] = loop.run_until_complete(server.start())
        except Exception as err:  # pylint: disable=broad-except
            result["error"] = err
            started.set()
            return
        started.set()
        loop.run_forever()
        loop.run_until_complete(server.stop())  # disconnects from the PS5 cleanly
        loop.close()

    thread = threading.Thread(target=serve, name="server", daemon=True)
    thread.start()
    started.wait(15)
    if "url" not in result:
        _LOGGER.error("Server failed to start: %s", result.get("error"))
        sys.exit(1)

    webview.create_window("PS5 Remote", result["url"], width=640, height=780,
                          min_size=(420, 600), background_color="#0e1015")
    # private_mode: no cookies or storage persisted to disk; debug off: no dev tools.
    webview.start(private_mode=True, debug=False)

    loop.call_soon_threadsafe(loop.stop)
    thread.join(8)


if __name__ == "__main__":
    main()
