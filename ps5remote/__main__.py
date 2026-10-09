# SPDX-License-Identifier: AGPL-3.0-only
"""Command-line tool: .\\ps5.bat <command> (see --help)."""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import logging
import sys
import time
import webbrowser

from . import config, ps5, psn, rpsession, watch
from .remote import BUTTONS, DEFAULT_PRESS_MS, Remote
from .watch import WatchSettings


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)


def save_host(status: dict) -> None:
    config.update(ps5_host=status["host-ip"])
    print(f"Saved PS5 address {status['host-ip']} to data/config.json.")


def describe(status: dict) -> str:
    name = status.get("host-name", "PS5")
    return f"{name} at {status['host-ip']} ({ps5.state_from_status(status)})"


def cmd_discover(args) -> None:
    if args.ip:
        return set_ip_manually(args.ip)

    print("Searching the network for a PS5 (3 seconds)...")
    found = ps5.discover()
    if not found:
        print(
            "\nNo PS5 found. Common causes:\n"
            "  - The PS5 is fully switched off (it must be on or in rest mode).\n"
            "  - In rest mode, 'Stay connected to the internet' is off\n"
            "    (PS5: Settings > System > Power Saving > Features Available in Rest Mode).\n"
            "  - Windows Firewall is blocking replies, or Wi-Fi is set to 'Public'.\n"
            "  - The PC and PS5 are on different networks (e.g. guest Wi-Fi).\n"
            "\nYou can type the PS5's IP address instead. Find it on the PS5 under\n"
            "Settings > Network > Connection Status > View Connection Status (IPv4 Address)."
        )
        ip = ask("PS5 IP address (or press Enter to quit): ")
        if ip:
            set_ip_manually(ip)
        return

    for i, status in enumerate(found, 1):
        print(f"  {i}. {describe(status)}")
    choice = found[0]
    if len(found) > 1:
        n = ask(f"Which one? [1-{len(found)}]: ")
        choice = found[int(n) - 1] if n.isdigit() and 1 <= int(n) <= len(found) else found[0]
    save_host(choice)


def set_ip_manually(ip: str) -> None:
    try:
        ipaddress.IPv4Address(ip)
    except ValueError:
        sys.exit(f"'{ip}' isn't a valid IP address (it should look like 192.168.1.50).")
    status = ps5.get_status(ip)
    if not status:
        print(f"Warning: nothing answered at {ip}. Saving it anyway; check it's correct.")
        config.update(ps5_host=ip)
        return
    print(f"Found {describe(status)}.")
    save_host(status)


def cmd_status(args) -> None:
    host = config.load().get("ps5_host")
    if not host:
        sys.exit("No PS5 address saved yet. Run:  .\\ps5.bat discover")
    status = ps5.get_status(host)
    state = ps5.state_from_status(status)
    label = {
        ps5.UNREACHABLE: "not reachable (switched off, or wrong IP)",
        ps5.ASLEEP: "asleep (rest mode)",
        ps5.AWAKE: "awake",
    }[state]
    print(f"PS5 at {host}: {label}")
    if status.get("running-app-name"):
        title_id = status.get("running-app-titleid", "")
        print(f"Running: {status['running-app-name']}" + (f"  (title ID {title_id})" if title_id else ""))
        try:
            app_map, why = watch.pick_app_map("auto", status)
            print(f"Watch-mode button map: {app_map.name} ({why})")
        except (OSError, ValueError, KeyError) as err:
            print(f"Couldn't read app_maps.json: {err}")


def cmd_login(args) -> None:
    print(
        "\nPSN sign-in (only needed once)\n"
        "------------------------------\n"
        "1. A browser window will open on Sony's sign-in page. Sign in with the PSN account\n"
        "   you use on your PS5.\n"
        "2. After signing in you'll land on a page whose address starts with\n"
        "   https://remoteplay.dl.playstation.net/remoteplay/redirect?code=...\n"
        "   The page itself may be blank or say 'error' / 'not found'. That's normal.\n"
        "3. Click the address bar, copy the whole address (Ctrl+L, then Ctrl+C) and paste it here.\n"
        "   Be quick: the code expires after a minute or two.\n"
    )
    try:
        url = psn.login_url()
    except psn.PSNError as err:
        sys.exit(str(err))
    print("If the browser doesn't open, copy this link into it yourself:\n")
    print(url + "\n")
    webbrowser.open(url)
    pasted = ask("Paste the redirect address here: ")
    try:
        online_id, account_id = psn.fetch_account(psn.extract_code(pasted))
    except psn.PSNError as err:
        sys.exit(f"Sign-in failed: {err}")

    profiles = config.profiles()
    profiles.update_user(psn.make_profile(online_id, account_id, profiles.get(online_id)))
    config.save_profiles(profiles)
    config.update(psn_user=online_id)
    print(f"\nSigned in as {online_id}. Account ID saved to data/profiles.json (not shown).")
    print("Next:  .\\ps5.bat pair")


def cmd_pair(args) -> None:
    pin = args.pin
    if not pin:
        print(
            "\nOn the PS5 (it must be fully on, not in rest mode):\n"
            "  Settings > System > Remote Play > Link Device\n"
            "  An 8-digit number appears on the TV. Leave that screen open.\n"
        )
        pin = ask("Enter the 8-digit number: ")
    pin = pin.replace(" ", "").replace("-", "")
    if not (pin.isdigit() and len(pin) == 8):
        sys.exit("The PIN should be exactly 8 digits.")
    print("Pairing...")
    ps5.pair(pin)
    print("Paired! Pairing keys saved to data/profiles.json (not shown).")
    print("Try:  .\\ps5.bat standby   then   .\\ps5.bat wake")


def cmd_wake(args) -> None:
    host = config.load().get("ps5_host")
    if host and ps5.state_from_status(ps5.get_status(host)) == ps5.AWAKE:
        print("The PS5 is already awake. Put it in rest mode first to test waking it.")
        return
    print("Sending wake signal...")
    if args.no_wait:
        ps5.send_wake()
        print("Wake signal sent.")
        return
    start = time.monotonic()
    if ps5.wake():
        print(f"The PS5 is awake ({time.monotonic() - start:.1f}s).")
    else:
        sys.exit("Sent the wake signal, but the PS5 didn't report being awake within 45 seconds.")


def print_event(kind: str, message: str) -> None:
    print(message)


async def _standby() -> bool:
    remote = Remote(on_event=print_event)
    try:
        return await remote.standby()
    finally:
        remote.close()


def cmd_standby(args) -> None:
    if asyncio.run(_standby()):
        print("Rest mode requested. The PS5's light should turn orange shortly.")
    else:
        print("The PS5 is already asleep.")


async def _press(button: str, press_ms: int) -> None:
    remote = Remote(press_ms=press_ms, on_event=print_event)
    try:
        await remote.tap(button)
        print(f"Pressed {button} ({press_ms} ms).")
        await asyncio.sleep(0.5)  # let the release reach the PS5 before hanging up
    finally:
        remote.close()


def cmd_press(args) -> None:
    try:
        asyncio.run(_press(args.button, args.ms))
    except KeyboardInterrupt:
        pass  # _press has already disconnected in its finally block


async def _probe_display(seconds: int) -> None:
    start = time.monotonic()

    def stamp() -> str:
        return f"{time.monotonic() - start:6.1f}s"

    remote = Remote(on_event=lambda kind, msg: print(f"{stamp()}  {msg}"))
    try:
        await remote.connect(wake=False)
        session = remote._device.session  # pylint: disable=protected-access

        def on_ctrl(msg_type: int, payload: bytes) -> None:
            if msg_type in (rpsession.CTRL_HEARTBEAT_REQ, rpsession.CTRL_HEARTBEAT_REP,
                            rpsession.CTRL_SESSION_ID):
                return  # routine; the session ID isn't shown
            print(f"{stamp()}  ctrl message {msg_type:#06x}: {payload[:16].hex(' ')}")

        session.on_ctrl_message = on_ctrl
        print(f"{stamp()}  Listening for {seconds}s. Switch between apps / play / pause now.")
        print(f"{stamp()}  Current state: {describe_protected(remote.protected_content)}")
        while time.monotonic() - start < seconds and remote.connected:
            await asyncio.sleep(0.2)
        print(f"{stamp()}  Final state: {describe_protected(remote.protected_content)}")
    finally:
        remote.close()


def describe_protected(value) -> str:
    return {None: "no display message yet (treated as normal)",
            True: "protected video (picture blanked)",
            False: "streamable picture"}[value]


def cmd_probe_display(args) -> None:
    try:
        asyncio.run(_probe_display(args.seconds))
    except KeyboardInterrupt:
        pass


def watch_settings_from_args(args) -> WatchSettings:
    settings = WatchSettings.load()
    for name in ("smart_play_s", "smart_pause_s", "post_wait_ms", "collect_ms", "gap_ms", "app"):
        value = getattr(args, name)
        if value is not None:
            setattr(settings, name, value)
    if args.save_settings:
        settings.save()
        print("Watch settings saved to data/config.json.")
    return settings


async def _post_wait_test(press_ms: int, settings: WatchSettings, button: str) -> None:
    print(
        "\nPost-press wait test\n--------------------\n"
        "Start a video playing in the streaming app. Each step sends one press in its own burst,\n"
        "waits the given time, then disconnects. After each step, say whether the PS5 reacted.\n"
        "Steps are ~10 s apart because the PS5 needs that long between sessions."
    )
    remote = Remote(press_ms=press_ms)
    try:
        best = await watch.post_wait_test(remote, settings, button, ask=ask, say=print)
    finally:
        remote.close()
    if best is None:
        print("No reliable value found. Keep the default, or try a longer press with --ms.")
    else:
        suggestion = best + 100 if best < 500 else best
        print(f"Shortest reliable post-wait: {best} ms. Suggested setting (with margin): {suggestion} ms")
        print(f"Save it with:  .\\ps5.bat remote --post-wait {suggestion} --save-settings")


def cmd_remote(args) -> None:
    settings = watch_settings_from_args(args)
    try:
        if args.post_wait_test:
            from .keyremote import watch_mode_enabled
            if not watch_mode_enabled():
                sys.exit("Watch mode is benched. See README 'Benched: Watch mode' to re-enable it.")
            asyncio.run(_post_wait_test(args.ms, settings, args.post_wait_test))
            return
        from . import keyremote  # Windows-only module
        asyncio.run(keyremote.run(args.ms, settings))
    except KeyboardInterrupt:
        pass  # the finally blocks have already disconnected


def cmd_app(args) -> None:
    from .app.main import run
    run(debug=args.debug, browser=args.browser, setup=args.setup, data_dir=args.data_dir,
        console=True)


def main() -> None:
    parser = argparse.ArgumentParser(prog="ps5.bat", description="Keyboard DS5 - command line")
    parser.add_argument("-v", "--verbose", action="store_true", help="show more log output")
    parser.add_argument("--safe-connect", action="store_true",
                        help="wait for the PS5's own session ID (about 1.5 s slower to connect)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover", help="find the PS5 and save its address")
    p.add_argument("--ip", help="skip searching and use this IP address")
    p.set_defaults(func=cmd_discover)
    sub.add_parser("status", help="show asleep / awake").set_defaults(func=cmd_status)
    sub.add_parser("login", help="sign in to PSN (once)").set_defaults(func=cmd_login)
    p = sub.add_parser("pair", help="link with the PS5 using its PIN")
    p.add_argument("--pin", help="8-digit PIN from the PS5 (prompted if omitted)")
    p.set_defaults(func=cmd_pair)
    p = sub.add_parser("wake", help="wake from rest mode")
    p.add_argument("--no-wait", action="store_true", help="don't wait for it to finish waking")
    p.set_defaults(func=cmd_wake)
    sub.add_parser("standby", help="put into rest mode").set_defaults(func=cmd_standby)
    p = sub.add_parser("press", help="press one button (wakes and connects if needed)")
    p.add_argument("button", choices=list(BUTTONS), type=str.lower)
    p.add_argument("--ms", type=int, default=DEFAULT_PRESS_MS,
                   help=f"how long to hold the button down (default {DEFAULT_PRESS_MS})")
    p.set_defaults(func=cmd_press)
    p = sub.add_parser("remote", help="interactive keyboard remote (stays connected)")
    p.add_argument("--ms", type=int, default=DEFAULT_PRESS_MS,
                   help=f"how long each press holds the button down (default {DEFAULT_PRESS_MS})")
    w = p.add_argument_group("Watch mode settings - BENCHED, only used if enabled in config")
    w.add_argument("--smart-play", dest="smart_play_s", type=int, choices=[0, 10, 20],
                   help="skip back this many seconds when resuming from paused (0 = off; default 10)")
    w.add_argument("--smart-pause", dest="smart_pause_s", type=int, choices=[0, 10, 20],
                   help="skip back this many seconds after pausing (0 = off; default 0)")
    w.add_argument("--post-wait", dest="post_wait_ms", type=int, metavar="MS",
                   help="keep each burst connected this long after the last press (default 300)")
    w.add_argument("--collect", dest="collect_ms", type=int, metavar="MS",
                   help="wait this long for more presses before connecting (default 300)")
    w.add_argument("--gap", dest="gap_ms", type=int, metavar="MS",
                   help="pause between presses inside one burst (default 150)")
    w.add_argument("--app", help="button map from app_maps.json, or 'auto' (default)")
    w.add_argument("--save-settings", action="store_true",
                   help="save the Watch settings given here as the new defaults")
    w.add_argument("--post-wait-test", metavar="BUTTON", nargs="?", const="cross",
                   help="find the shortest reliable post-press wait (sends cross unless given)")
    p.set_defaults(func=cmd_remote)
    p = sub.add_parser("app", help="open the app window with live logs in this terminal")
    p.add_argument("--debug", action="store_true", help="verbose logs + devtools (right-click > Inspect)")
    p.add_argument("--browser", action="store_true", help="use your default browser instead of the window")
    p.add_argument("--setup", action="store_true",
                   help="show the setup wizard even if paired (existing pairing kept until the new one works)")
    p.add_argument("--data-dir", help="use another data folder, e.g. a temporary one for testing setup")
    p.set_defaults(func=cmd_app)
    p = sub.add_parser("probe-display",
                       help="stay connected and report when the PS5 says it's showing protected video")
    p.add_argument("--seconds", type=int, default=90)
    p.set_defaults(func=cmd_probe_display)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.verbose:
        logging.getLogger("ps5remote").setLevel(logging.DEBUG)
    ps5.quiet_library_logs(args.verbose)
    ps5.use_windows_event_loop()
    if args.safe_connect:
        rpsession.EARLY_SESSION_ID = None
    try:
        args.func(args)
    except ps5.PS5Error as err:
        sys.exit(f"Error: {err}")


if __name__ == "__main__":
    main()
