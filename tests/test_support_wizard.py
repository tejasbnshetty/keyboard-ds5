# SPDX-License-Identifier: AGPL-3.0-only
"""The support-files wizard step and Settings actions, as in the key-free public build."""
import asyncio
import json
import sys
from pathlib import Path

import pytest
import pyremoteplay.keys as installed

from ps5remote import keyfree, psn, support
from ps5remote.app import main as app_main
from ps5remote.app.wizard import SetupWizard

from .test_wizard import FakeServer

KEYS_PY = Path(installed.__file__)


@pytest.fixture
def keyfree_build(monkeypatch):
    """Behave like the public .exe before support files are loaded."""
    monkeypatch.setattr(keyfree, "ACTIVE", True)
    monkeypatch.setattr(keyfree, "TABLES_OK", False)


@pytest.fixture
def server():
    return FakeServer()


def step(wizard, kind, **data):
    asyncio.run(wizard.handle(kind, data))
    return wizard.public_state()


def tables():
    return {name: bytes(getattr(installed, name)) for name in support.TABLES}


def test_source_install_needs_no_support_files(server):
    sup = SetupWizard(server, None).public_state()["support"]
    assert sup["needed"] is False and sup["restart_needed"] is False
    # and the actions do nothing
    state = step(SetupWizard(server, None), "setup_support_download")
    assert state["support"]["state"] == "missing" and not state["error"]


def test_public_build_starts_without_them(server, keyfree_build):
    sup = SetupWizard(server, None).public_state()["support"]
    assert sup["needed"] and not sup["loaded"] and sup["state"] == "missing"
    assert sup["version"] == "0.7.6" and sup["pypi_page"].startswith("https://pypi.org/")
    assert sup["can_pick_file"] is False and sup["can_restart"] is False


def test_download_installs_and_asks_for_restart(server, keyfree_build, monkeypatch):
    calls = []
    monkeypatch.setattr(support, "download", lambda: calls.append(1) or (tables(), "PyPI, test"))
    state = step(SetupWizard(server, None), "setup_support_download")
    assert calls == [1] and not state["error"]
    sup = state["support"]
    assert sup["state"] == "ready" and sup["restart_needed"] and not sup["loaded"]
    assert any(k == "info" and "Restart" in m for k, m in server.events)
    assert support.load_tables(support.default_dir()) == tables()


def test_download_failure_is_reported(server, keyfree_build, monkeypatch):
    def offline():
        raise support.SupportError("Couldn't download pyremoteplay from PyPI (wheel: no network).")
    monkeypatch.setattr(support, "download", offline)
    state = step(SetupWizard(server, None), "setup_support_download")
    assert "Couldn't download" in state["error"] and state["support"]["state"] == "missing"
    assert any(k == "error" for k, _ in server.events)


def test_choose_file_needs_the_window(server, keyfree_build):
    state = step(SetupWizard(server, None), "setup_support_file")
    assert "browser mode" in state["error"]


def test_choose_real_keys_file(server, keyfree_build):
    server.pick_file = lambda: str(KEYS_PY)
    state = step(SetupWizard(server, None), "setup_support_file")
    assert not state["error"] and state["support"]["state"] == "ready"
    assert "keys.py" in state["support"]["source"]


def test_choose_file_cancelled(server, keyfree_build):
    server.pick_file = lambda: None
    state = step(SetupWizard(server, None), "setup_support_file")
    assert not state["error"] and state["support"]["state"] == "missing"


def test_tampered_file_is_rejected(server, keyfree_build, tmp_path):
    tampered = tmp_path / "keys.py"
    data = bytearray(KEYS_PY.read_bytes())
    at = data.index(b"0x", 5000) + 2
    data[at] = ord("f") if data[at] != ord("f") else ord("e")
    tampered.write_bytes(bytes(data))
    server.pick_file = lambda: str(tampered)
    state = step(SetupWizard(server, None), "setup_support_file")
    assert "checksum" in state["error"] and state["support"]["state"] == "missing"


def test_remove_and_restart(server, keyfree_build, monkeypatch):
    support.save(support.default_dir(), tables(), "test")
    monkeypatch.setattr(keyfree, "TABLES_OK", True)   # as if loaded at startup
    w = SetupWizard(server, None)
    assert w.public_state()["support"]["restart_needed"] is False
    state = step(w, "setup_support_remove")
    assert state["support"]["state"] == "missing" and state["support"]["restart_needed"]
    restarted = []
    server.restart = lambda: restarted.append(True)
    step(w, "setup_restart")
    assert restarted == [True]


def test_restart_without_callback(server, keyfree_build):
    assert "yourself" in step(SetupWizard(server, None), "setup_restart")["error"]


def test_public_build_ignores_psn_client_json(keyfree_build, psn_client):
    """Without opted-in sign-in values, a psn_client.json doesn't enable sign-in either."""
    assert psn.is_configured() is False
    with pytest.raises(psn.PSNError):
        psn.login_url()


def test_public_build_signs_in_with_the_stored_values(keyfree_build, monkeypatch):
    import pyremoteplay.oauth as installed_oauth
    client = support.parse_oauth_source(Path(installed_oauth.__file__).read_bytes())
    support.save_sign_in(support.default_dir(), client, "test")
    monkeypatch.setenv("PS5REMOTE_PSN_CLIENT_ID", "ignored-in-public-build")
    monkeypatch.setenv("PS5REMOTE_PSN_CLIENT_SECRET", "ignored")
    assert psn.is_configured() and psn._client() == client
    url = psn.login_url()
    assert url.startswith(psn.AUTHORIZE_URL) and f"client_id={client[0]}" in url
    assert client[1] not in url                       # the secret never goes in the URL
    assert f"redirect_uri={psn.REDIRECT_URL}" in url


def test_public_build_damaged_sign_in_file_means_no_sign_in(keyfree_build):
    folder = support.default_dir()
    folder.mkdir(parents=True)
    (folder / support.SIGN_IN_FILE).write_text('{"client_id": "x", "client_secret": "y"}')
    assert psn.is_configured() is False


def test_status_warns_when_support_files_are_missing(keyfree_build):
    from ps5remote.app.server import AppServer
    assert AppServer()._status_payload()["support_missing"] is True


def test_status_fine_from_source():
    from ps5remote.app.server import AppServer
    assert AppServer()._status_payload()["support_missing"] is False


@pytest.mark.parametrize("frozen, kwargs, tail", [
    (True, {}, []),
    (True, {"browser": True, "setup": True, "data_dir": "D:/x"}, ["--browser", "--setup", "--data-dir", "D:/x"]),
    (False, {"debug": True}, ["-m", "ps5remote.app", "--debug"]),
])
def test_relaunch_command_keeps_options(monkeypatch, frozen, kwargs, tail):
    monkeypatch.setattr(app_main.config, "FROZEN", frozen)
    command = app_main.relaunch_command(**kwargs)
    assert command[0] == sys.executable and command[1:] == tail
