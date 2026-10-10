# SPDX-License-Identifier: AGPL-3.0-only
import base64
import json

import pytest

from ps5remote import config, psn


def test_not_configured_by_default():
    assert not psn.is_configured()
    with pytest.raises(psn.PSNError, match="isn't set up.*account ID") as err:
        psn.login_url()
    assert "psn_client.example.json" not in str(err.value)   # not shipped with a download


def test_no_psn_client_lookup_next_to_the_exe(monkeypatch, data_dir):
    """The .exe has no source data folder: only the data folder and a personal bundle count."""
    monkeypatch.setattr(config, "SOURCE_DATA_DIR", None)
    assert not psn.is_configured()


@pytest.mark.parametrize("text, user_id", [
    ("1", 1),
    ("1234567890123456789", 1234567890123456789),
    (" 1234 5678 9012 3456 789 ", 1234567890123456789),
    (str(2 ** 64 - 1), 2 ** 64 - 1),
])
def test_parse_account_id_number(text, user_id):
    assert base64.b64decode(psn.parse_account_id(text)) == user_id.to_bytes(8, "little")


def test_parse_account_id_encoded_round_trip():
    encoded = base64.b64encode((987654321).to_bytes(8, "little")).decode()
    assert psn.parse_account_id(encoded) == encoded
    assert psn.parse_account_id(encoded.rstrip("=")) == encoded   # padding optional
    assert psn.parse_account_id(f"  {encoded} ") == encoded


def test_number_and_encoded_forms_agree():
    """The same ID typed either way pairs as the same account (as fetch_account encodes it)."""
    user_id = 7340032000123456
    encoded = base64.b64encode(user_id.to_bytes(8, "little")).decode()
    assert psn.parse_account_id(str(user_id)) == psn.parse_account_id(encoded) == encoded


@pytest.mark.parametrize("text", [
    "", "   ", "0", str(2 ** 64), "-5", "12.5", "hello", "AAAAAAAAAAA=",   # all zero
    "QUJD", "QUJDREVGR0hJSktM",                                         # 3 and 12 bytes
    "not base64!!", "ΩΩΩΩ",
])
def test_parse_account_id_rejects(text):
    with pytest.raises(psn.PSNError):
        psn.parse_account_id(text)


@pytest.mark.parametrize("text, expected", [
    ("", psn.DEFAULT_ONLINE_ID), ("  ", psn.DEFAULT_ONLINE_ID), ("Player_1", "Player_1"),
    ("a-b", "a-b"),
])
def test_check_online_id(text, expected):
    assert psn.check_online_id(text) == expected


@pytest.mark.parametrize("text", ["x" * 17, "has space", "<b>", "naïve"])
def test_check_online_id_rejects(text):
    with pytest.raises(psn.PSNError):
        psn.check_online_id(text)


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


def test_base64_secret_is_decoded(data_dir):
    data_dir.mkdir(parents=True)
    encoded = base64.b64encode(b"plain-secret").decode()
    (data_dir / "psn_client.json").write_text(
        json.dumps({"client_id": "cccccccc", "client_secret_base64": encoded}))
    assert psn._client() == ("cccccccc", "plain-secret")


def test_plain_secret_wins_over_base64(data_dir):
    data_dir.mkdir(parents=True)
    (data_dir / "psn_client.json").write_text(json.dumps(
        {"client_id": "cccccccc", "client_secret": "plain", "client_secret_base64": "eHg="}))
    assert psn._client() == ("cccccccc", "plain")


@pytest.mark.parametrize("content", [
    "{bad json", '{"client_id": "x"}', '{"client_secret": "y"}',
    '{"client_id": "cccccccc", "client_secret_base64": "not base64!"}',
    '{"client_id": "cccccccc", "client_secret_base64": 5}',
])
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
    assert psn.is_redirect(psn.REDIRECT_URL)
    assert not psn.is_redirect("https://example.com/?u=" + psn.REDIRECT_URL)
    assert not psn.is_redirect(None)


@pytest.mark.parametrize("url", [
    psn.REDIRECT_URL + "EVIL?code=x",                                   # longer path
    psn.REDIRECT_URL + "/extra?code=x",
    psn.REDIRECT_URL.replace("https://", "http://") + "?code=x",        # not https
    psn.REDIRECT_URL.replace("playstation.net", "playstation.net.evil.example") + "?code=x",
    "https://remoteplay.dl.playstation.net:8443/remoteplay/redirect?code=x",
    "https://user@evil.example/remoteplay/redirect?code=x",
])
def test_is_redirect_is_exact(url):
    assert not psn.is_redirect(url)


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
