# SPDX-License-Identifier: AGPL-3.0-only
import pytest

from ps5remote import config, ps5


def test_explain_known_code():
    text = ps5.explain(f"Rejected: {0x80108B12}")
    assert "Enable Remote Play" in text and "0x80108b12" in text


def test_explain_unknown_reason_unchanged():
    assert ps5.explain("Something else") == "Something else"


def test_is_fatal():
    assert ps5.is_fatal(str(0x80108B12))
    assert ps5.is_fatal(str(0x80108B02))
    assert not ps5.is_fatal(str(0x80108B10))  # busy: worth retrying
    assert not ps5.is_fatal("")


@pytest.mark.parametrize("status, state", [
    ({}, ps5.UNREACHABLE),
    ({"status-code": 200}, ps5.AWAKE),
    ({"status-code": 620}, ps5.ASLEEP),
])
def test_state_from_status(status, state):
    assert ps5.state_from_status(status) == state


@pytest.mark.parametrize("text, ok", [
    ("192.168.1.50", True), ("10.0.0.1", True), ("256.1.1.1", False),
    ("192.168.1", False), ("ps5.local", False), ("", False), ("::1", False),
])
def test_is_ipv4(text, ok):
    assert ps5.is_ipv4(text) is ok


def test_require_setup_messages():
    with pytest.raises(ps5.PS5Error, match="discover"):
        ps5.require_setup()
    config.update(ps5_host="1.2.3.4")
    with pytest.raises(ps5.PS5Error, match="login"):
        ps5.require_setup()
    config.update(psn_user="me")
    assert ps5.require_setup() == ("1.2.3.4", "me")


@pytest.mark.parametrize("pin", ["1234567", "123456789", "abcdefgh", "1234 567", ""])
def test_pair_console_rejects_bad_pin_before_anything_else(pin, monkeypatch):
    monkeypatch.setattr(ps5, "Device", lambda *a: pytest.fail("contacted the PS5"))
    with pytest.raises(ps5.PS5Error, match="8 digits"):
        ps5.pair_console("1.2.3.4", "me", pin)
    assert not config.PROFILES_FILE.exists() or config.PROFILES_FILE.read_text() in ("", "{}")


def test_pair_console_needs_a_sign_in(monkeypatch):
    monkeypatch.setattr(ps5, "Device", lambda *a: pytest.fail("contacted the PS5"))
    with pytest.raises(ps5.PS5Error, match="Not signed in"):
        ps5.pair_console("1.2.3.4", "me", "12345678")


class _FakeDevice:
    def __init__(self, host, *, found=True, on=True, register_log=None, profile=None):
        self.host, self.found, self.is_on = host, found, on
        self.register_log, self.profile = register_log, profile

    def get_status(self):
        return {"status-code": 200} if self.found else {}

    def register(self, user, pin, timeout, profiles, save):
        assert save is False
        if self.register_log:
            import logging
            logging.getLogger("pyremoteplay.register").error(self.register_log)
        return self.profile


@pytest.mark.parametrize("kwargs, message", [
    ({"found": False}, "isn't reachable"),
    ({"on": False}, "rest mode"),
    ({"register_log": "Host is not in Register Mode"}, "Link Device"),
    ({"register_log": "Failed to register"}, "rejected the PIN"),
    ({"register_log": "No Register Response"}, "didn't answer"),
    ({}, "Pairing failed"),
])
def test_pair_console_failures_save_nothing(kwargs, message, monkeypatch):
    monkeypatch.setattr(ps5, "Device", lambda host: _FakeDevice(host, **kwargs))
    with pytest.raises(ps5.PS5Error, match=message):
        ps5.pair_console("1.2.3.4", "newuser", "12345678", account_id="AQAAAAAAAAA=")
    assert config.load() == {}
    profiles_text = config.PROFILES_FILE.read_text() if config.PROFILES_FILE.exists() else ""
    assert "newuser" not in profiles_text


def test_pair_console_success_saves(monkeypatch):
    monkeypatch.setattr(ps5, "Device", lambda host: _FakeDevice(host, profile={"ok": True}))
    ps5.pair_console("1.2.3.4", "newuser", "12345678", account_id="AQAAAAAAAAA=")
    assert config.load() == {"ps5_host": "1.2.3.4", "psn_user": "newuser"}
    assert "newuser" in config.PROFILES_FILE.read_text()


def test_device_skips_the_store_lookup(monkeypatch):
    from pyremoteplay.device import RPDevice
    seen = []
    monkeypatch.setattr(RPDevice, "_set_status", lambda self, data: seen.append(data))
    device = object.__new__(ps5.Device)  # no __init__: nothing to set up for this
    device._set_status({"host-id": "x", "running-app-titleid": "PPSA01234"})
    device._set_status({})
    assert seen == [{"host-id": "x"}, {}]
