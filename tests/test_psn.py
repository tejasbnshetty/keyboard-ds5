# SPDX-License-Identifier: AGPL-3.0-only
import base64
import json

import pytest

from ps5remote import config, psn


def test_not_configured_by_default():
    assert not psn.is_configured()
    with pytest.raises(psn.PSNError, match="isn't configured"):
        psn.login_url()


def test_client_from_data_folder(psn_client):
    assert psn._client() == psn_client
    assert f"client_id={psn_client[0]}" in psn.login_url()


def test_env_vars_win_over_file(psn_client, monkeypatch):
    monkeypatch.setenv("PS5REMOTE_PSN_CLIENT_ID", "aaaaaaaa-env")
    monkeypatch.setenv("PS5REMOTE_PSN_CLIENT_SECRET", "env-secret")
    assert psn._client() == ("aaaaaaaa-env", "env-secret")


def test_env_vars_need_both(psn_client, monkeypatch):
    monkeypatch.setenv("PS5REMOTE_PSN_CLIENT_ID", "aaaaaaaa-env")
    assert psn._client() == psn_client


def test_source_data_folder_is_a_fallback():
    config.SOURCE_DATA_DIR.mkdir(parents=True)
    (config.SOURCE_DATA_DIR / "psn_client.json").write_text(
        json.dumps({"client_id": "bbbbbbbb", "client_secret": "s"}))
    assert psn._client() == ("bbbbbbbb", "s")


@pytest.mark.parametrize("content", ["{bad json", '{"client_id": "x"}', '{"client_secret": "y"}'])
def test_incomplete_or_broken_file_is_ignored(data_dir, content):
    data_dir.mkdir(parents=True)
    (data_dir / "psn_client.json").write_text(content)
    assert not psn.is_configured()


def test_unsafe_client_id_rejected(data_dir):
    data_dir.mkdir(parents=True)
    (data_dir / "psn_client.json").write_text(
        json.dumps({"client_id": "abc&redirect_uri=evil", "client_secret": "s"}))
    with pytest.raises(psn.PSNError, match="invalid client_id"):
        psn.login_url()


def test_login_url_uses_sony_redirect(psn_client):
    url = psn.login_url()
    assert url.startswith(psn.AUTHORIZE_URL + "?")
    assert f"redirect_uri={psn.REDIRECT_URL}" in url
    assert psn_client[1] not in url  # the secret never goes in the browser URL


@pytest.mark.parametrize("text, code", [
    (f"{psn.REDIRECT_URL}?code=AbCd1234&cid=x", "AbCd1234"),
    (f'  "{psn.REDIRECT_URL}?code=AbCd1234"  ', "AbCd1234"),
    ("AbCd1234", "AbCd1234"),
])
def test_extract_code(text, code):
    assert psn.extract_code(text) == code


@pytest.mark.parametrize("text", ["", "abc", f"{psn.REDIRECT_URL}?error=denied"])
def test_extract_code_rejects(text):
    with pytest.raises(psn.PSNError, match="Couldn't find a code"):
        psn.extract_code(text)


def test_is_redirect():
    assert psn.is_redirect(psn.REDIRECT_URL + "?code=x")
    assert not psn.is_redirect("https://example.com/?u=" + psn.REDIRECT_URL)
    assert not psn.is_redirect(None)


def test_make_profile_keeps_pairings_only_for_same_account():
    existing = {"id": "SAME", "hosts": {"MAC": {"x": 1}}}
    assert psn.make_profile("me", "SAME", existing)["hosts"] == {"MAC": {"x": 1}}
    assert psn.make_profile("me", "OTHER", existing)["hosts"] == {}
    assert psn.make_profile("me", "SAME", None)["hosts"] == {}


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def _fake_requests(monkeypatch, post, get):
    calls = []
    monkeypatch.setattr(psn.requests, "post", lambda url, **kw: calls.append(("post", url, kw)) or post)
    monkeypatch.setattr(psn.requests, "get", lambda url, **kw: calls.append(("get", url, kw)) or get)
    return calls


def test_fetch_account_encodes_account_id(psn_client, monkeypatch):
    user_id = 1234567890123456789
    calls = _fake_requests(monkeypatch, _Resp(200, {"access_token": "TOKEN"}),
                           _Resp(200, {"user_id": str(user_id), "online_id": "Player1"}))
    online_id, account_id = psn.fetch_account("CODE")
    assert online_id == "Player1"
    assert base64.b64decode(account_id) == user_id.to_bytes(8, "little")
    assert calls[0][2]["data"]["code"] == "CODE"
    assert calls[0][2]["auth"] == psn_client
    assert all(kw["timeout"] for _, _, kw in calls)


@pytest.mark.parametrize("post, get, message", [
    (_Resp(400, {}), None, "rejected the sign-in code"),
    (_Resp(200, {}), None, "no access token"),
    (_Resp(200, {"access_token": "T"}), _Resp(500, {}), "HTTP 500"),
    (_Resp(200, {"access_token": "T"}), _Resp(200, {}), "no account ID"),
])
def test_fetch_account_errors(psn_client, monkeypatch, post, get, message):
    _fake_requests(monkeypatch, post, get)
    with pytest.raises(psn.PSNError, match=message):
        psn.fetch_account("CODE")
