# SPDX-License-Identifier: AGPL-3.0-only
"""The app's local server: security checks and the WebSocket messages."""
import asyncio
import json

import aiohttp
import pytest

from ps5remote import config, keymaps, rpsession
from ps5remote.app.server import AppServer
from ps5remote.settings import AppSettings

from .conftest import ACCOUNT_ID
from .fakes import FakePS5


def serve(test):
    """Run test(server, base_url, session) against a started server, then stop it."""
    async def go():
        server = AppServer()
        await server.start()
        base = f"http://127.0.0.1:{server.port}"
        try:
            async with aiohttp.ClientSession() as session:
                return await test(server, base, session)
        finally:
            await server.stop()
    return asyncio.run(go())


async def open_ws(server, base, session, **overrides):
    params = {"token": overrides.pop("token", server.token)}
    headers = {"Origin": overrides.pop("origin", base)}
    return await session.ws_connect(f"{base}/ws", params=params, headers=headers)


async def receive_until(ws, kind, timeout=2.0):
    """Messages up to and including the first of the given type."""
    seen = []
    while True:
        msg = json.loads((await ws.receive(timeout=timeout)).data)
        seen.append(msg)
        if msg["type"] == kind:
            return seen


async def hello(ws):
    await ws.send_json({"type": "hello"})
    msgs = await receive_until(ws, "status")
    return {m["type"]: m for m in msgs}


def test_listens_on_loopback_only():
    assert AppServer().host == "127.0.0.1"


def test_page_is_served_with_security_headers():
    async def test(server, base, session):
        async with session.get(base + "/") as resp:
            assert resp.status == 200
            assert "default-src 'self'" in resp.headers["Content-Security-Policy"]
            assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
            assert resp.headers["X-Content-Type-Options"] == "nosniff"
            assert resp.headers["Referrer-Policy"] == "no-referrer"
        async with session.get(base + "/static/app.js") as resp:
            assert resp.status == 200
    serve(test)


@pytest.mark.parametrize("host", ["evil.example", "192.168.1.10", "127.0.0.1:1"])
def test_foreign_host_header_refused(host):
    async def test(server, base, session):
        async with session.get(base + "/", headers={"Host": host}) as resp:
            return resp.status
    assert serve(test) == 403


def test_static_files_cannot_escape_web_folder():
    async def test(server, base, session):
        async with session.get(base + "/static/..%2F..%2Fconfig.py") as resp:
            return resp.status
    assert serve(test) in (403, 404)


@pytest.mark.parametrize("overrides", [
    {"token": ""},
    {"token": "wrong"},
    {"origin": "http://evil.example"},
    {"origin": ""},
])
def test_websocket_refused_without_token_and_origin(overrides):
    async def test(server, base, session):
        with pytest.raises(aiohttp.WSServerHandshakeError) as err:
            await open_ws(server, base, session, **overrides)
        return err.value.status
    assert serve(test) == 403


def test_hello_when_not_set_up(psn_client):
    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            return await hello(ws)
    msgs = serve(test)
    assert msgs["init"]["buttons"][0] == "up"
    assert msgs["init"]["keymaps"] == keymaps.DEFAULTS
    assert msgs["setup"]["active"] is True
    assert msgs["setup"]["psn_configured"] is True
    assert msgs["status"]["power"] == "setup_needed"


def test_no_secrets_reach_the_interface(paired, psn_client, monkeypatch):
    FakePS5(monkeypatch)

    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            msgs = await hello(ws)
            return json.dumps(msgs)
    text = serve(test)
    assert ACCOUNT_ID not in text
    assert psn_client[1] not in text
    assert psn_client[0] not in text
    assert "RegistKey" not in text and "RP-Key" not in text


@pytest.mark.parametrize("raw, message", [
    ("not json", "Bad message"),
    ("[1, 2]", "Bad message"),
    ('{"type": 5}', "Unknown message"),
    ('{"type": "launch_missiles"}', "Unknown message"),
    ('{"type": "press", "button": "turbo"}', "Unknown button"),
])
def test_bad_messages_get_an_error(raw, message):
    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            await ws.send_str(raw)
            return (await receive_until(ws, "error"))[-1]["message"]
    assert serve(test) == message


def test_press_without_setup_reports_error():
    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "press", "button": "cross"})
            msgs = await receive_until(ws, "event")
            return msgs[-1]
    event = serve(test)
    assert event["kind"] == "error" and "Not set up" in event["message"]


def test_press_reaches_the_ps5(paired, monkeypatch):
    fake = FakePS5(monkeypatch)

    async def test(server, base, session):
        server.remote.press_s = 0.001
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "press", "button": "cross"})
            for _ in range(100):
                if len(fake.presses) == 2:
                    break
                await asyncio.sleep(0.01)
            server.remote.close()
    serve(test)
    assert fake.presses == [("CROSS", "press"), ("CROSS", "release")]


def test_hold_and_release(paired, monkeypatch):
    fake = FakePS5(monkeypatch)

    async def test(server, base, session):
        server.remote.press_s = 0.001
        server.remote.repeat_delay = server.remote.repeat_interval = 0.01
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "hold", "button": "down"})
            await asyncio.sleep(0.15)
            await ws.send_json({"type": "release", "button": "down"})
            await asyncio.sleep(0.05)
            count = len(fake.presses)
            await asyncio.sleep(0.05)
            assert len(fake.presses) == count
            server.remote.close()
    serve(test)
    assert len([p for p in fake.presses if p[1] == "press"]) >= 3


def test_closing_the_window_releases_a_held_button(paired, monkeypatch):
    fake = FakePS5(monkeypatch)

    async def test(server, base, session):
        server.remote.press_s = 0.001
        server.remote.repeat_delay = server.remote.repeat_interval = 0.01
        ws = await open_ws(server, base, session)
        await ws.send_json({"type": "hold", "button": "up"})
        await asyncio.sleep(0.1)
        await ws.close()
        await asyncio.sleep(0.05)
        count = len(fake.presses)
        await asyncio.sleep(0.05)
        server.remote.close()
        return count
    count = serve(test)
    assert count == len(fake.presses)
    assert fake.presses[-1] == ("UP", "release")


def test_save_settings_valid():
    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "save_settings", "settings": {
                "press_ms": 120, "idle_timeout_min": 0, "repeat_delay_ms": 300,
                "repeat_interval_ms": 100, "safe_connect": True, "profile_hotkey": "F4"}})
            return await receive_until(ws, "event")
    msgs = serve(test)
    assert msgs[-1]["message"] == "Settings saved."
    assert AppSettings.load().press_ms == 120
    assert rpsession.EARLY_SESSION_ID is None  # safe connect applied


@pytest.mark.parametrize("settings, message", [
    ({"press_ms": 1}, "between"),
    ({"profile_hotkey": "Enter"}, "already used"),  # bound in the Menus profile
])
def test_save_settings_invalid(settings, message):
    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "save_settings", "settings": settings})
            return (await receive_until(ws, "event"))[-1]
    event = serve(test)
    assert event["kind"] == "error" and message in event["message"]
    assert "app" not in config.load()


def test_save_keymaps_rejects_the_hotkey():
    async def test(server, base, session):
        bad = keymaps.defaults()
        bad["profiles"]["Menus"]["bindings"]["F2"] = "ps"
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "save_keymaps", "keymaps": bad})
            return (await receive_until(ws, "event"))[-1]
    event = serve(test)
    assert event["kind"] == "error" and "reserved" in event["message"]
    assert not keymaps.keymaps_file().exists()


def test_rejected_keymaps_put_the_interface_back():
    """E.g. a profile name the server refuses: the window gets the saved maps back."""
    async def test(server, base, session):
        bad = keymaps.defaults()
        bad["profiles"]["<bad name>"] = {"bindings": {}}
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "save_keymaps", "keymaps": bad})
            return (await receive_until(ws, "keymaps"))[-1]["keymaps"]
    assert serve(test) == keymaps.DEFAULTS


def test_custom_profile_round_trip():
    async def test(server, base, session):
        km = keymaps.defaults()
        km["profiles"]["My racer"] = {"hold_buttons": True,
                                      "bindings": {"KeyW": "r2", "KeyS": "l2", "KeyA": "ls_left"}}
        km["active"] = "My racer"
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "save_keymaps", "keymaps": km})
            return (await receive_until(ws, "keymaps"))[-1]["keymaps"]
    saved = serve(test)
    assert saved["active"] == "My racer"
    assert keymaps.load()["profiles"]["My racer"]["bindings"]["KeyW"] == "r2"


def test_save_and_reset_keymaps():
    async def test(server, base, session):
        km = keymaps.defaults()
        km["active"] = "Gaming"
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "save_keymaps", "keymaps": km})
            saved = (await receive_until(ws, "keymaps"))[-1]["keymaps"]
            await ws.send_json({"type": "reset_keymaps"})
            reset = (await receive_until(ws, "keymaps"))[-1]["keymaps"]
            return saved, reset
    saved, reset = serve(test)
    assert saved["active"] == "Gaming"
    assert reset == keymaps.DEFAULTS
    assert keymaps.load() == keymaps.DEFAULTS


def test_status_shows_power_app_and_streaming_warning(paired, monkeypatch):
    FakePS5(monkeypatch, status={"status-code": 200, "running-app-name": "Netflix"})

    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "hello"})
            for _ in range(20):
                msg = (await receive_until(ws, "status"))[-1]
                if msg["power"] == "on":
                    return msg
    status = serve(test)
    assert status["app"] == "Netflix"
    assert status["streaming_app"] == "Netflix"
    assert status["connected"] is False


async def pad_until(ws, check, timeout=2.0):
    """Read visualiser updates until one passes check()."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while True:
        msg = json.loads((await ws.receive(timeout=end - loop.time())).data)
        if msg["type"] == "pad" and check(msg):
            return msg


def test_visualiser_works_without_a_ps5():
    """Not set up at all: keys and mouse still move the sticks on screen."""
    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "act", "action": "ls_up", "down": True})
            await ws.send_json({"type": "act", "action": "ls_right", "down": True})
            await ws.send_json({"type": "act", "action": "r2", "down": True})
            pad = await pad_until(ws, lambda p: p["left"][0] > 0 and p["buttons"])
            await ws.send_json({"type": "capture", "on": True})
            await ws.send_json({"type": "mouse", "dx": 300, "dy": 0})
            moved = await pad_until(ws, lambda p: p["right"][0] > 0)
            await ws.send_json({"type": "capture", "on": False})
            released = await pad_until(ws, lambda p: not p["captured"])
            return pad, moved, released
    pad, moved, released = serve(test)
    assert pad["left"] == [0.707, -0.707] and pad["buttons"] == {"r2": 255}
    assert moved["captured"] is True
    assert released == {"type": "pad", "left": [0, 0], "right": [0, 0], "buttons": {},
                        "captured": False}


def test_mouse_ignored_until_captured():
    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "mouse", "dx": 500, "dy": 500})
            await asyncio.sleep(0.1)
            return server.game.sticks()
    assert serve(test) == ((0, 0), (0, 0))


@pytest.mark.parametrize("message, reply", [
    ({"type": "act", "action": "jump", "down": True}, "Unknown action"),
    ({"type": "act", "action": "cross", "down": 1}, "Unknown action"),
    ({"type": "mouse", "dx": "5", "dy": 0}, "Bad mouse movement"),
    ({"type": "mouse", "dx": 1e9, "dy": 0}, "Bad mouse movement"),
    ({"type": "mouse", "dx": True, "dy": 0}, "Bad mouse movement"),
])
def test_bad_gaming_messages(message, reply):
    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            await ws.send_json(message)
            return (await receive_until(ws, "error"))[-1]["message"]
    assert serve(test) == reply


def test_gaming_input_reaches_the_ps5(paired, monkeypatch):
    fake = FakePS5(monkeypatch)

    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "act", "action": "ls_up", "down": True})
            await ws.send_json({"type": "act", "action": "r2", "down": True})
            await ws.send_json({"type": "act", "action": "light_trigger", "down": True})
            for _ in range(100):
                if fake.devices and fake.devices[0].session.stream.values:
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)
            await ws.send_json({"type": "act", "action": "r2", "down": False})
            await asyncio.sleep(0.05)
            stream = fake.devices[0].session.stream
            values, states = list(stream.values), list(stream.states)
            server.remote.close()
            return values, states
    values, states = serve(test)
    assert values[0] == ("r2", 102) and values[-1] == ("r2", 0)
    assert ((0, -32767), (0, 0)) in states


def test_window_closing_sends_neutral(paired, monkeypatch):
    fake = FakePS5(monkeypatch)

    async def test(server, base, session):
        ws = await open_ws(server, base, session)
        await ws.send_json({"type": "act", "action": "cross", "down": True})
        await ws.send_json({"type": "act", "action": "ls_left", "down": True})
        for _ in range(100):
            if server.remote.connected:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        await ws.close()
        await asyncio.sleep(0.05)
        stream = fake.devices[0].session.stream
        result = list(stream.values), list(stream.states)
        server.remote.close()
        return result
    values, states = serve(test)
    assert values[-1] == ("cross", 0)
    assert states[-1] == ((0, 0), (0, 0))


def test_neutral_message_releases_everything(paired, monkeypatch):
    FakePS5(monkeypatch)

    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "act", "action": "triangle", "down": True})
            await pad_until(ws, lambda p: p["buttons"])
            await ws.send_json({"type": "neutral"})
            pad = await pad_until(ws, lambda p: not p["buttons"])
            server.remote.close()
            return pad
    assert serve(test)["left"] == [0, 0]


def test_dropped_session_resets_the_interface(paired, monkeypatch):
    fake = FakePS5(monkeypatch)

    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "capture", "on": True})
            await ws.send_json({"type": "act", "action": "ls_up", "down": True})
            for _ in range(100):
                if server.remote.connected:
                    break
                await asyncio.sleep(0.01)
            server.remote._dropped("test")
            msgs = await receive_until(ws, "game_reset")
            return msgs[-1], server.game.captured, server.game.is_neutral
    reset, captured, neutral = serve(test)
    assert reset["reason"] == "dropped" and not captured and neutral


def test_failed_game_connect_is_not_retried_by_mouse_alone(paired, monkeypatch):
    fake = FakePS5(monkeypatch, status={})   # PS5 not answering

    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "capture", "on": True})
            await receive_until(ws, "event")           # "No PS5 answered"
            for _ in range(5):
                await ws.send_json({"type": "mouse", "dx": 400, "dy": 0})
                await asyncio.sleep(0.03)
            errors_after_mouse = server._game_retry_at
            await ws.send_json({"type": "act", "action": "cross", "down": True})
            await receive_until(ws, "event")           # a key press tries again
            return errors_after_mouse
    import math
    assert serve(test) == math.inf


def test_hotkeys_cannot_be_bound_or_collide():
    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "save_settings", "settings": {"mouse_toggle_key": "KeyW"}})
            first = (await receive_until(ws, "event"))[-1]
            bad = keymaps.defaults()
            bad["profiles"]["Gaming"]["bindings"]["F1"] = "cross"
            await ws.send_json({"type": "save_keymaps", "keymaps": bad})
            second = (await receive_until(ws, "event"))[-1]
            return first, second
    first, second = serve(test)
    assert "KeyW is already used" in first["message"]
    assert "reserved" in second["message"]


def test_events_are_written_to_the_log(caplog):
    caplog.set_level("INFO", logger="ps5remote.app.server")

    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "press", "button": "cross"})   # not set up: an error
            await receive_until(ws, "event")
    serve(test)
    assert any(r.levelname == "WARNING" and "error: Not set up" in r.getMessage()
               for r in caplog.records)


def test_init_lists_actions_and_new_buttons():
    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            return await hello(ws)
    init = serve(test)["init"]
    assert "touchpad" in init["buttons"] and "ls_up" in init["actions"]
    assert "Gaming" in init["keymaps"]["profiles"]
    assert init["templates"] == keymaps.DEFAULTS["profiles"]   # for "New profile"


def test_forget_pairing_keeps_settings_and_keymaps(paired, monkeypatch):
    FakePS5(monkeypatch)
    AppSettings(press_ms=150).save()
    keymaps.save(keymaps.defaults())

    async def test(server, base, session):
        async with await open_ws(server, base, session) as ws:
            await ws.send_json({"type": "forget_all"})
            return (await receive_until(ws, "setup"))[-1]
    setup = serve(test)
    assert setup["active"] is True
    assert not config.PROFILES_FILE.exists()
    assert "ps5_host" not in config.load() and "psn_user" not in config.load()
    assert AppSettings.load().press_ms == 150
    assert keymaps.keymaps_file().exists()
