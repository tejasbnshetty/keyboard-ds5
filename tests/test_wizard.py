# SPDX-License-Identifier: AGPL-3.0-only
"""Setup wizard, server side. Nothing is saved until pairing succeeds."""
import asyncio
import base64
import json

import pytest

from ps5remote import config, ps5, psn
from ps5remote.app.wizard import SetupWizard

from .conftest import ACCOUNT_ID


class FakeServer:
    def __init__(self):
        self.sent = []
        self.events = []
        self.reloaded = 0
        self.forgotten = 0
        self.pick_file = None
        self.restart = None

    async def broadcast(self, payload):
        self.sent.append(payload)

    async def event(self, kind, message):
        self.events.append((kind, message))

    def reload_remote(self):
        self.reloaded += 1

    def forget_pairing(self):
        self.forgotten += 1
        config.PROFILES_FILE.unlink(missing_ok=True)
        config.remove_keys("ps5_host", "psn_user")


@pytest.fixture
def server():
    return FakeServer()


def make(server, open_login=None, force=False):
    return SetupWizard(server, open_login, force=force)


def step(wizard, kind, **data):
    asyncio.run(wizard.handle(kind, data))
    return wizard.public_state()


def test_active_when_not_paired(server):
    state = make(server).public_state()
    assert state["active"] and not state["can_cancel"]
    assert state["psn_configured"] is False


def test_inactive_when_paired_unless_forced(server, paired):
    assert not make(server).active
    assert make(server, force=True).active
    assert make(server).public_state()["existing_account"] == "tester"


def test_cancel_only_when_paired(server):
    w = make(server)
    assert step(w, "setup_cancel")["active"]


def test_cancel_when_paired(server, paired):
    w = make(server, force=True)
    assert not step(w, "setup_cancel")["active"]


def test_start_modes(server, paired):
    w = make(server)
    assert step(w, "setup_start", mode="repair")["mode"] == "repair"
    assert step(w, "setup_start", mode="other")["mode"] == "full"


def test_discover_lists_consoles(server, monkeypatch):
    monkeypatch.setattr(ps5, "discover", lambda: [
        {"host-ip": "10.0.0.5", "host-name": "Living room", "status-code": 200},
        {"host-name": "no ip"}])
    state = step(make(server), "setup_discover")
    assert state["consoles"] == [{"ip": "10.0.0.5", "name": "Living room", "state": "awake"}]
    assert not state["error"] and not state["busy"]


def test_discover_nothing_found(server, monkeypatch):
    monkeypatch.setattr(ps5, "discover", lambda: [])
    assert "No PS5 found" in step(make(server), "setup_discover")["error"]


def test_discover_crash_gives_a_friendly_error(server, monkeypatch):
    def boom():
        raise OSError("port 9303 in use")
    monkeypatch.setattr(ps5, "discover", boom)
    state = step(make(server), "setup_discover")
    assert "Something went wrong (OSError)" in state["error"]


@pytest.mark.parametrize("ip, status, message", [
    ("not-an-ip", None, "isn't a valid IP"),
    ("10.0.0.9", {}, "Nothing answered"),
    ("10.0.0.9", {"host-type": "PS4", "status-code": 200}, "isn't a PS5"),
])
def test_use_console_errors(server, monkeypatch, ip, status, message):
    async def get_status(_ip):
        return status
    monkeypatch.setattr(ps5, "async_get_status", get_status)
    state = step(make(server), "setup_use_console", ip=ip)
    assert message in state["error"] and state["console"] is None


def test_use_console_ok(server, monkeypatch):
    async def get_status(_ip):
        return {"host-type": "PS5", "host-name": "Den", "status-code": 620}
    monkeypatch.setattr(ps5, "async_get_status", get_status)
    state = step(make(server), "setup_use_console", ip="10.0.0.9")
    assert state["console"] == {"ip": "10.0.0.9", "name": "Den", "state": "asleep"}
    assert config.load() == {}  # nothing saved yet


def test_sign_in_not_configured(server):
    error = step(make(server), "setup_psn_open")["error"]
    assert "account ID" in error and "psn_client.example.json" not in error


def test_manual_account_id_without_sign_in_values(server, monkeypatch):
    """The path for a download with no sign-in values: type the ID, then pair."""
    w = make(server)
    assert w.public_state()["psn_configured"] is False
    state = step(w, "setup_psn_manual", account_id="1234567890123456789", online_id="Player_1")
    assert state["signed_in"] == "Player_1" and not state["error"]
    encoded = base64.b64encode((1234567890123456789).to_bytes(8, "little")).decode()
    assert encoded not in json.dumps(state) and encoded not in json.dumps(server.sent)
    assert "1234567890123456789" not in json.dumps(server.sent)
    assert not config.PROFILES_FILE.exists()   # nothing saved until paired

    w.console = {"ip": "10.0.0.9", "name": "PS5", "state": "awake"}
    calls = []
    monkeypatch.setattr(ps5, "pair_console", lambda *args: calls.append(args))
    assert step(w, "setup_pair", pin="12345678")["paired"]
    assert calls == [("10.0.0.9", "Player_1", "12345678", encoded)]


def test_manual_account_id_name_is_optional(server):
    state = step(make(server), "setup_psn_manual", account_id="42")
    assert state["signed_in"] == psn.DEFAULT_ONLINE_ID


@pytest.mark.parametrize("data, message", [
    ({"account_id": ""}, "Enter your account ID"),
    ({"account_id": "hello"}, "doesn't look like"),
    ({"account_id": "42", "online_id": "bad name!"}, "up to 16"),
])
def test_manual_account_id_errors(server, data, message):
    state = step(make(server), "setup_psn_manual", **data)
    assert message in state["error"] and state["signed_in"] is None


def test_sign_in_with_window(server, psn_client):
    opened = []
    w = make(server, open_login=lambda url, cb: opened.append((url, cb)))
    state = step(w, "setup_psn_open")
    assert state["login_window_open"] and state["embedded_login"]
    assert opened[0][0].startswith(psn.AUTHORIZE_URL)


def test_sign_in_window_closed_early_asks_for_paste(server, psn_client):
    w = make(server, open_login=lambda url, cb: None)
    asyncio.run(w._login_done(None))
    state = w.public_state()
    assert state["paste_needed"] and not state["login_window_open"]


def test_sign_in_browser_fallback(server, psn_client, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    state = step(make(server), "setup_psn_open")
    assert state["paste_needed"] and len(opened) == 1


def test_paste_sign_in_keeps_account_id_private(server, psn_client, monkeypatch):
    monkeypatch.setattr(psn, "fetch_account", lambda code: ("Player1", ACCOUNT_ID))
    w = make(server)
    state = step(w, "setup_psn_paste", url=f"{psn.REDIRECT_URL}?code=ABCDEFG")
    assert state["signed_in"] == "Player1"
    assert ACCOUNT_ID not in json.dumps(state)
    assert ACCOUNT_ID not in json.dumps(server.sent)
    assert "ABCDEFG" not in json.dumps(server.sent)
    assert not config.PROFILES_FILE.exists()  # not saved until paired


def test_paste_sign_in_rejected(server, psn_client, monkeypatch):
    def reject(code):
        raise psn.PSNError("Sony rejected the sign-in code (HTTP 400).")
    monkeypatch.setattr(psn, "fetch_account", reject)
    state = step(make(server), "setup_psn_paste", url=f"{psn.REDIRECT_URL}?code=ABCDEFG")
    assert "rejected" in state["error"] and not state["signed_in"]


def test_keep_existing_account(server, paired):
    w = make(server, force=True)
    assert step(w, "setup_psn_keep")["signed_in"] == "tester"


def test_pair_needs_console_and_sign_in(server):
    w = make(server)
    assert "Choose a PS5" in step(w, "setup_pair", pin="12345678")["error"]
    w.console = {"ip": "10.0.0.9", "name": "PS5", "state": "awake"}
    assert "Sign in" in step(w, "setup_pair", pin="12345678")["error"]


def _ready(server, monkeypatch):
    monkeypatch.setattr(psn, "fetch_account", lambda code: ("Player1", ACCOUNT_ID))
    w = make(server)
    w.console = {"ip": "10.0.0.9", "name": "PS5", "state": "awake"}
    step(w, "setup_psn_paste", url="CODE1234")
    return w


def test_pair_failure_keeps_old_pairing(server, paired, monkeypatch):
    before_cfg = config.load()
    before_profiles = config.PROFILES_FILE.read_text()
    w = _ready(server, monkeypatch)

    def reject(*args):
        raise ps5.PS5Error("The PS5 rejected the PIN.")
    monkeypatch.setattr(ps5, "pair_console", reject)
    state = step(w, "setup_pair", pin="1234-5678")
    assert "rejected the PIN" in state["error"] and not state["paired"]
    assert config.load() == before_cfg
    assert config.PROFILES_FILE.read_text() == before_profiles
    assert server.reloaded == 0


def test_pair_success(server, monkeypatch):
    w = _ready(server, monkeypatch)
    calls = []
    monkeypatch.setattr(ps5, "pair_console", lambda *args: calls.append(args))
    state = step(w, "setup_pair", pin="1234 5678")
    assert state["paired"] and not state["error"]
    assert calls == [("10.0.0.9", "Player1", "12345678", ACCOUNT_ID)]
    assert server.reloaded == 1


def test_finish_only_when_paired(server, paired):
    w = make(server, force=True)
    assert not step(w, "setup_finish")["active"]


def test_finish_ignored_when_not_paired(server):
    assert step(make(server), "setup_finish")["active"]


def test_forget_all(server, paired):
    w = make(server)
    state = step(w, "forget_all")
    assert state["active"] and state["mode"] == "full"
    assert server.forgotten == 1
    assert not config.is_paired()


def test_unknown_setup_message_is_ignored(server):
    w = make(server)
    asyncio.run(w.handle("setup_nonsense", {}))
    assert server.sent == []
