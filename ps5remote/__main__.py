"""Command-line tool:  .\\ps5.bat <command>

  discover        find the PS5 on the network and save its address (or --ip to set it by hand)
  status          show whether the PS5 is asleep / awake
  login           sign in to PSN once to get your account ID
  pair            link this PC to the PS5 using the PIN shown on the TV
  wake            wake the PS5 from rest mode
  standby         put the PS5 into rest mode
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import logging
import sys
import webbrowser

from . import config, ps5, psn


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
        print(f"Running: {status['running-app-name']}")


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
    print("If the browser doesn't open, copy this link into it yourself:\n")
    print(psn.LOGIN_URL + "\n")
    webbrowser.open(psn.LOGIN_URL)
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
    if ps5.wake(wait=not args.no_wait):
        print("The PS5 is awake." if not args.no_wait else "Wake signal sent.")
    else:
        sys.exit("Sent the wake signal, but the PS5 didn't report being awake within 45 seconds.")


def cmd_standby(args) -> None:
    print("Connecting to the PS5 to put it into rest mode (takes a few seconds)...")
    if asyncio.run(ps5.standby()):
        print("Rest mode requested. The PS5's light should turn orange shortly.")
    else:
        print("The PS5 is already asleep or not reachable.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="ps5.bat", description="PS5 phone remote - command line")
    parser.add_argument("-v", "--verbose", action="store_true", help="show more log output")
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

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    ps5.quiet_library_logs(args.verbose)
    ps5.use_windows_event_loop()
    try:
        args.func(args)
    except ps5.PS5Error as err:
        sys.exit(f"Error: {err}")


if __name__ == "__main__":
    main()
