# SPDX-License-Identifier: AGPL-3.0-only
"""App entry point: start the local server, then show it in a pywebview window (see --help)."""
from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import re
import subprocess
import sys
import threading
import time
import webbrowser

import ps5remote

from .. import config, ps5, psn
from .server import AppServer

_LOGGER = logging.getLogger(__name__)


class Redact(logging.Filter):
    """Last line of defence: scrub sign-in codes, tokens, PINs and secrets from every log line."""

    PATTERN = re.compile(
        r"(?i)\b(code|token|access_token|refresh_token|client_secret|client_id|pin)"
        r"(['\"]?\s*[:=]\s*['\"]?)([^&\s'\",}]+)")

    def __init__(self):
        super().__init__()
        self.extra: list[str] = []   # exact values to hide, e.g. the session token

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pylint: disable=broad-except
            return True
        clean = self.PATTERN.sub(r"\1\2<redacted>", message)
        for value in self.extra:
            clean = clean.replace(value, "<redacted>")
        if clean != message:
            record.msg, record.args = clean, ()
        return True


def setup_logging(debug: bool, console: bool) -> Redact:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    redact = Redact()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers = [logging.handlers.RotatingFileHandler(
        config.LOG_DIR / "app.log", maxBytes=512_000, backupCount=2, encoding="utf-8")]
    if console and sys.stderr:
        handlers.append(logging.StreamHandler())
    root = logging.getLogger()
    for old in list(root.handlers):  # e.g. ps5.bat's handler, which has no redaction
        root.removeHandler(old)
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    for handler in handlers:
        handler.setFormatter(fmt)
        handler.addFilter(redact)
        root.addHandler(handler)
    # pyremoteplay logs pairing keys at DEBUG: never below INFO, even with --debug.
    ps5.quiet_library_logs(verbose=debug)
    logging.getLogger("aiohttp.access").disabled = True  # request URLs carry the token
    for noisy in ("urllib3", "asyncio", "pythonnet", "clr_loader"):
        logging.getLogger(noisy).setLevel(logging.INFO if debug else logging.WARNING)
    return redact


def make_login_opener(webview):
    """Opens Sony's sign-in page in an app window and catches the redirect."""

    def open_login(url: str, on_result) -> None:
        window = webview.create_window("Sign in to PlayStation Network", url,
                                       width=520, height=760)
        done = threading.Event()

        def finish(value):
            if not done.is_set():
                done.set()
                on_result(value)

        def watch():
            while not done.is_set():
                try:
                    current = window.get_current_url()
                except Exception:  # pylint: disable=broad-except
                    current = None
                if psn.is_redirect(current):
                    finish(current)
                    try:
                        window.destroy()
                    except Exception:  # pylint: disable=broad-except
                        pass
                    return
                time.sleep(0.25)

        window.events.closed += lambda *args: finish(None)
        threading.Thread(target=watch, name="login-watch", daemon=True).start()

    return open_login


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="KeyboardDS5", description="Keyboard DS5 app")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {ps5remote.__version__} ({ps5remote.SOURCE_URL})")
    parser.add_argument("--debug", action="store_true", help="verbose logs and devtools")
    parser.add_argument("--browser", action="store_true",
                        help="open the interface in your default browser instead of a window")
    parser.add_argument("--setup", action="store_true", help="show the setup wizard even if paired")
    parser.add_argument("--data-dir", help="use this data folder (e.g. a temporary one for testing)")
    return parser.parse_args(argv)


def relaunch_command(debug=False, browser=False, setup=False, data_dir=None) -> list[str]:
    """How to start the app again with the same options (after installing support files)."""
    base = [sys.executable] if config.FROZEN else [sys.executable, "-m", "ps5remote.app"]
    return (base + (["--debug"] if debug else []) + (["--browser"] if browser else [])
            + (["--setup"] if setup else []) + (["--data-dir", str(data_dir)] if data_dir else []))


def _spawn(command: list[str]) -> None:
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(command, close_fds=True, creationflags=flags)  # pylint: disable=consider-using-with


def run(debug=False, browser=False, setup=False, data_dir=None, console=False) -> None:
    if data_dir:
        config.set_data_dir(data_dir)
    redact = setup_logging(debug, console)
    ps5.use_windows_event_loop()
    _LOGGER.info("Data folder: %s", config.DATA_DIR)
    command = relaunch_command(debug, browser, setup, data_dir)
    if browser:
        return _run_browser(setup, redact, command)
    return _run_window(debug, setup, redact, command)


def _run_browser(setup: bool, redact: Redact, command: list[str]) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def restart() -> None:
        _LOGGER.info("Restarting")
        _spawn(command)
        loop.call_soon_threadsafe(loop.stop)

    # Browser mode: sign-in uses the paste fallback, and support files can only be downloaded.
    server = AppServer(open_login=None, force_setup=setup, pick_file=None, restart=restart)
    redact.extra.append(server.token)
    url = loop.run_until_complete(server.start())
    print("Opening the interface in your default browser. Press Ctrl+C here to stop.")
    webbrowser.open(url)
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(server.stop())
        loop.close()
        print("Stopped.")


SUPPORT_FILE_TYPES = ("pyremoteplay files (*.whl;*.tar.gz;*.py)", "All files (*.*)")


def _run_window(debug: bool, setup: bool, redact: Redact, command: list[str]) -> None:
    import webview  # imported here so the server can be tested without a GUI

    loop = asyncio.new_event_loop()
    windows: list = []

    def pick_file() -> str | None:
        """Native open dialog (called from the server thread). The chosen path or None."""
        if not windows:
            return None
        chosen = windows[0].create_file_dialog(webview.FileDialog.OPEN, file_types=SUPPORT_FILE_TYPES)
        return chosen[0] if chosen else None

    def restart() -> None:
        _LOGGER.info("Restarting")
        _spawn(command)
        if windows:
            windows[0].destroy()

    server = AppServer(open_login=make_login_opener(webview), force_setup=setup,
                       pick_file=pick_file, restart=restart)
    redact.extra.append(server.token)
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
        loop.run_until_complete(server.stop())
        loop.close()

    thread = threading.Thread(target=serve, name="server", daemon=True)
    thread.start()
    started.wait(15)
    if "url" not in result:
        _LOGGER.error("Server failed to start: %s", result.get("error"))
        sys.exit(1)

    title = "Keyboard DS5"
    if AppServer.build_info()["personal"]:
        title += " (personal build - do not distribute)"
    windows.append(webview.create_window(title, result["url"], width=660, height=820,
                                         min_size=(420, 600), background_color="#0e1015"))
    # private_mode: no cookies or storage kept on disk, including Sony's sign-in.
    webview.start(private_mode=True, debug=debug)

    loop.call_soon_threadsafe(loop.stop)
    thread.join(8)


def main(argv=None) -> None:
    args = parse_args(argv)
    run(debug=args.debug, browser=args.browser, setup=args.setup, data_dir=args.data_dir,
        console=not config.FROZEN)


if __name__ == "__main__":
    main()
