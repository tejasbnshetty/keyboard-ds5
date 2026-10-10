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
    monkeypatch.setattr(support, "download_all",
                        lambda: calls.append(1) or support.Extracted(tables(), None, "PyPI, test"))
    state = step(SetupWizard(server, None), "setup_support_download")
    assert calls == [1] and not state["error"]
    sup = state["support"]
    assert sup["state"] == "ready" and sup["restart_needed"] and not sup["loaded"]
    assert any(k == "info" and "Restart" in m for k, m in server.events)
    assert support.load_tables(support.default_dir()) == tables()


def test_download_failure_is_reported(server, keyfree_build, monkeypatch):
    def offline():
        raise support.SupportError("Couldn't download pyremoteplay from PyPI (wheel: no network).")
    monkeypatch.setattr(support, "download_all", offline)
    state = step(SetupWizard(server, None), "setup_support_download")
    assert "Couldn't download" in state["error"] and state["support"]["state"] == "missing"
    assert any(k == "error" for k, _ in server.events)


# Opt-in sign-in values -------------------------------------------------------------------------

def real_client():
    import pyremoteplay.oauth as installed_oauth
    return support.parse_oauth_source(Path(installed_oauth.__file__).read_bytes())


@pytest.fixture
def download_with_sign_in(monkeypatch):
    monkeypatch.setattr(support, "download_all",
                        lambda: support.Extracted(tables(), real_client(), "PyPI, test"))


def test_sign_in_is_off_unless_ticked(server, keyfree_build, download_with_sign_in):
    state = step(SetupWizard(server, None), "setup_support_download")   # box not ticked
    assert state["support"]["state"] == "ready"
    assert state["support"]["sign_in"]["state"] == "missing" and state["psn_configured"] is False


def test_ticking_the_box_enables_sign_in(server, keyfree_build, download_with_sign_in):
    state = step(SetupWizard(server, None), "setup_support_download", sign_in=True)
    assert state["support"]["state"] == "ready" and state["support"]["sign_in"]["state"] == "ready"
    assert state["psn_configured"] is True
    assert any("Sign in with PlayStation is enabled" in m for _, m in server.events)
    assert real_client()[1] not in json.dumps(state)     # never sent to the interface


def test_sign_in_problem_keeps_the_tables(server, keyfree_build, monkeypatch):
    monkeypatch.setattr(support, "download_all", lambda: support.Extracted(
        tables(), None, "PyPI, test", "oauth.py doesn't match"))
    state = step(SetupWizard(server, None), "setup_support_download", sign_in=True)
    assert not state["error"] and state["support"]["state"] == "ready"
    assert state["support"]["sign_in"]["state"] == "missing"
    assert any("weren't added" in m for _, m in server.events)


def test_oauth_file_needs_the_box(server, keyfree_build, tmp_path):
    import pyremoteplay.oauth as installed_oauth
    path = tmp_path / "oauth.py"
    path.write_bytes(Path(installed_oauth.__file__).read_bytes())
    server.pick_file = lambda: str(path)
    state = step(SetupWizard(server, None), "setup_support_file")
    assert "Tick" in state["error"] and state["support"]["sign_in"]["state"] == "missing"
    state = step(SetupWizard(server, None), "setup_support_file", sign_in=True)
    assert not state["error"] and state["support"]["sign_in"]["state"] == "ready"
    assert state["support"]["state"] == "missing"      # oauth.py has no key tables


def test_remove_sign_in_values_only(server, keyfree_build, download_with_sign_in):
    w = SetupWizard(server, None)
    step(w, "setup_support_download", sign_in=True)
    state = step(w, "setup_sign_in_remove")
    assert state["support"]["sign_in"]["state"] == "missing" and state["support"]["state"] == "ready"


def test_use_my_browser_instead(server, keyfree_build, download_with_sign_in, monkeypatch):
    opened_in_window, opened_in_browser = [], []
    monkeypatch.setattr("webbrowser.open", opened_in_browser.append)
    w = SetupWizard(server, lambda url, cb: opened_in_window.append(url))
    step(w, "setup_support_download", sign_in=True)
    state = step(w, "setup_psn_open", browser=True)
    assert opened_in_browser and not opened_in_window and state["paste_needed"]
    step(w, "setup_psn_open")
    assert opened_in_window   # the default is the app's sign-in window


def test_closed_sign_in_window_points_to_manual_entry(server, keyfree_build, download_with_sign_in):
    w = SetupWizard(server, lambda url, cb: None)
    step(w, "setup_support_download", sign_in=True)
    asyncio.run(w._login_done(None))
    state = w.public_state()
    assert state["sign_in_failed"] and "account ID" in state["error"]


def test_rejected_sign_in_points_to_manual_entry(server, keyfree_build, download_with_sign_in,
                                                 monkeypatch):
    def reject(code):
        raise psn.PSNError("Sony rejected the sign-in code (HTTP 400).")
    monkeypatch.setattr(psn, "fetch_account", reject)
    w = SetupWizard(server, None)
    step(w, "setup_support_download", sign_in=True)
    state = step(w, "setup_psn_paste", url="CODE12345")
    assert state["sign_in_failed"] and "enter your account ID instead" in state["error"]
    state = step(w, "setup_psn_manual", account_id="42")   # and the fallback works
    assert state["signed_in"] and not state["error"]


# "Enable Sign in with PlayStation" on the Account step -----------------------------------

@pytest.fixture
def tables_installed(keyfree_build, monkeypatch):
    """The usual state on the Account step: key tables installed and loaded, no sign-in."""
    support.save(support.default_dir(), tables(), "PyPI, earlier")
    monkeypatch.setattr(keyfree, "TABLES_OK", True)


def test_enable_sign_in_from_the_account_step(server, tables_installed, download_with_sign_in):
    w = SetupWizard(server, None)
    before = w.public_state()
    assert before["psn_configured"] is False and before["support"]["restart_needed"] is False
    state = step(w, "setup_sign_in_enable", source="download")
    assert not state["error"] and state["psn_configured"] is True
    assert state["support"]["sign_in"]["state"] == "ready"
    assert state["support"]["restart_needed"] is False          # sign-in works at once
    assert state["support"]["source"] == "PyPI, earlier"         # key tables left as they were
    assert not any("Restart" in m for _, m in server.events)


def test_enable_sign_in_from_a_chosen_oauth_file(server, tables_installed, tmp_path):
    import pyremoteplay.oauth as installed_oauth
    path = tmp_path / "oauth.py"
    path.write_bytes(Path(installed_oauth.__file__).read_bytes())
    server.pick_file = lambda: str(path)
    state = step(SetupWizard(server, None), "setup_sign_in_enable", source="file")
    assert not state["error"] and state["psn_configured"] is True


def test_enable_sign_in_refuses_keys_py(server, tables_installed):
    server.pick_file = lambda: str(KEYS_PY)
    state = step(SetupWizard(server, None), "setup_sign_in_enable", source="file")
    assert "Sign-in wasn't enabled" in state["error"] and "account ID" in state["error"]
    assert state["psn_configured"] is False and state["support"]["state"] == "ready"


def test_enable_sign_in_download_failure(server, tables_installed, monkeypatch):
    def offline():
        raise support.SupportError("Couldn't download pyremoteplay from PyPI (wheel: offline).")
    monkeypatch.setattr(support, "download_all", offline)
    state = step(SetupWizard(server, None), "setup_sign_in_enable", source="download")
    assert "Couldn't download" in state["error"] and state["psn_configured"] is False
    assert support.load_tables(support.default_dir()) == tables()


def test_enable_sign_in_file_cancelled_or_browser_mode(server, tables_installed):
    assert "browser mode" in step(SetupWizard(server, None), "setup_sign_in_enable", source="file")["error"]
    server.pick_file = lambda: None
    state = step(SetupWizard(server, None), "setup_sign_in_enable", source="file")
    assert not state["error"] and state["psn_configured"] is False


def test_enable_sign_in_is_public_build_only(server, download_with_sign_in):
    state = step(SetupWizard(server, None), "setup_sign_in_enable", source="download")
    assert state["psn_configured"] is False and not state["error"]


def test_wizard_never_sends_people_to_settings():
    """The Account step offers sign-in itself; the wizard's own text never says 'go to Settings'."""
    root = Path(__file__).resolve().parent.parent / "ps5remote" / "app" / "web"
    js = (root / "app.js").read_text(encoding="utf-8")
    render = js[js.index("function renderWizard()"):js.index("function autoDiscover()")]
    assert "Settings" not in render
    html = (root / "index.html").read_text(encoding="utf-8")
    account = html[html.index('data-step="3">'):html.index('<div class="wiz-step" data-step="4">')]
    assert "Settings →" not in account.replace("Settings → Network", "").replace("Settings → System", "")
    assert 'id="wiz-enable-signin-open"' in account and "as chiaki-ng does" in account


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


@pytest.mark.parametrize("url, expected", [
    (None, "Sign in to PlayStation Network - loading..."),
    ("", "Sign in to PlayStation Network - loading..."),
    ("about:blank", "Sign in to PlayStation Network - loading..."),
    ("https://my.account.sony.com/central/signin/?x=1&code=secret",
     "Sign in to PlayStation Network - my.account.sony.com"),
    ("https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/authorize?client_id=abc",
     "Sign in to PlayStation Network - auth.api.sonyentertainmentnetwork.com"),
    ("http://evil.example/login", "Sign in to PlayStation Network - evil.example (NOT a secure connection)"),
])
def test_login_window_title_shows_the_domain(url, expected):
    title = app_main.login_window_title(url)
    assert title == expected
    assert "secret" not in title and "client_id" not in title   # never the path or query


class FakeLoginWindow:
    def __init__(self, urls):
        self.urls, self.titles, self.destroyed = list(urls), [], False
        self.events = type("E", (), {"closed": self})()

    def __iadd__(self, handler):   # window.events.closed += handler
        return self

    def get_current_url(self):
        return self.urls.pop(0) if len(self.urls) > 1 else self.urls[0]

    def set_title(self, title):
        self.titles.append(title)

    def destroy(self):
        self.destroyed = True


def test_sign_in_window_title_follows_the_page(monkeypatch):
    import threading
    real_sleep = app_main.time.sleep
    monkeypatch.setattr(app_main.time, "sleep", lambda s: real_sleep(0.001))
    window = FakeLoginWindow(["https://my.account.sony.com/signin", "https://my.account.sony.com/signin",
                              "https://id.sonyentertainmentnetwork.com/x",
                              "https://remoteplay.dl.playstation.net/remoteplay/redirect?code=ABC"])
    webview = type("W", (), {"create_window": staticmethod(lambda *a, **k: window)})
    got = threading.Event()
    result = []
    app_main.make_login_opener(webview)("https://start", lambda r: (result.append(r), got.set()))
    assert got.wait(5)
    assert window.titles[:2] == ["Sign in to PlayStation Network - my.account.sony.com",
                                 "Sign in to PlayStation Network - id.sonyentertainmentnetwork.com"]
    assert result[0].endswith("code=ABC") and window.destroyed


@pytest.mark.parametrize("frozen, kwargs, tail", [
    (True, {}, []),
    (True, {"browser": True, "setup": True, "data_dir": "D:/x"}, ["--browser", "--setup", "--data-dir", "D:/x"]),
    (False, {"debug": True}, ["-m", "ps5remote.app", "--debug"]),
])
def test_relaunch_command_keeps_options(monkeypatch, frozen, kwargs, tail):
    monkeypatch.setattr(app_main.config, "FROZEN", frozen)
    command = app_main.relaunch_command(**kwargs)
    assert command[0] == sys.executable and command[1:] == tail
