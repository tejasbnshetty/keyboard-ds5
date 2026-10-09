"""PSN sign-in, used once to learn the account ID that Remote Play pairing needs.

Uses the same OAuth flow, scopes and redirect as chiaki-ng. The access token is used once and
discarded; only the derived account ID (and PSN online ID, used as a profile name) is kept.

The Sony client ID/secret are NOT in this source code. They're read, in order, from:
  1. environment variables PS5REMOTE_PSN_CLIENT_ID / PS5REMOTE_PSN_CLIENT_SECRET
  2. psn_client.json in the data folder ({"client_id": ..., "client_secret": ...})
  3. psn_client.json in the source tree's data/ folder (so --data-dir test runs still work)
  4. psn_client.json bundled into a *personal* .exe by build.bat
See psn_client.example.json. Never commit or publish real values.
"""
from __future__ import annotations

import base64
import json
import os
import re
from urllib.parse import parse_qs, quote, urlparse

import requests
from pyremoteplay.profile import UserProfile

from . import config

REDIRECT_URL = "https://remoteplay.dl.playstation.net/remoteplay/redirect"
SCOPES = (
    "psn:clientapp referenceDataService:countryConfig.read "
    "pushNotification:webSocket.desktop.connect "
    "sessionManager:remotePlaySession.system.update"
)
TOKEN_URL = "https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/token"
AUTHORIZE_URL = "https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/authorize"
CLIENT_FILE = "psn_client.json"
_SAFE_ID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


class PSNError(Exception):
    pass


def _client() -> tuple[str, str] | None:
    env_id = os.environ.get("PS5REMOTE_PSN_CLIENT_ID")
    env_secret = os.environ.get("PS5REMOTE_PSN_CLIENT_SECRET")
    if env_id and env_secret:
        return env_id, env_secret
    for folder in (config.DATA_DIR, config.SOURCE_DATA_DIR, config.RESOURCES):
        path = folder / CLIENT_FILE
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("client_id") and data.get("client_secret"):
                    return data["client_id"], data["client_secret"]
            except (OSError, ValueError):
                continue
    return None


def is_configured() -> bool:
    return _client() is not None


def _require_client() -> tuple[str, str]:
    client = _client()
    if not client:
        raise PSNError(
            "PSN sign-in isn't configured: no psn_client.json found. See psn_client.example.json "
            "and the README section 'PSN sign-in values'.")
    if not _SAFE_ID.match(client[0]):
        raise PSNError("psn_client.json has an invalid client_id.")
    return client


def login_url() -> str:
    client_id, _ = _require_client()
    return (
        f"{AUTHORIZE_URL}?service_entity=urn:service-entity:psn&response_type=code"
        f"&client_id={client_id}&redirect_uri={REDIRECT_URL}&scope={quote(SCOPES)}"
        "&request_locale=en_US&ui=pr&service_logo=ps&layout_type=popup"
        "&smcid=remoteplay&prompt=always&PlatformPrivacyWs1=minimal&"
    )


def is_redirect(url: str | None) -> bool:
    return bool(url) and url.startswith(REDIRECT_URL)


def extract_code(text: str) -> str:
    """Accept either the full redirect URL or just the code value."""
    text = text.strip().strip('"')
    if "://" in text:
        code = parse_qs(urlparse(text).query).get("code", [""])[0]
    else:
        code = text
    if len(code) < 4:
        raise PSNError(
            "Couldn't find a code in that. Paste the whole address from the browser's "
            "address bar after signing in (it contains 'redirect?code=').")
    return code


def fetch_account(code: str) -> tuple[str, str]:
    """Exchange the sign-in code for (online_id, base64 account id). The token is discarded."""
    auth = _require_client()
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URL,
    }
    resp = requests.post(TOKEN_URL, data=body, auth=auth, timeout=15)
    if resp.status_code != 200:
        raise PSNError(
            f"Sony rejected the sign-in code (HTTP {resp.status_code}). Codes expire after "
            "a minute or two and work only once. Sign in again.")
    token = resp.json().get("access_token")
    if not token:
        raise PSNError("Sony's response had no access token.")

    resp = requests.get(f"{TOKEN_URL}/{token}", auth=auth, timeout=15)
    del token
    if resp.status_code != 200:
        raise PSNError(f"Couldn't read account info (HTTP {resp.status_code}).")
    info = resp.json()
    user_id = info.get("user_id")
    if not user_id:
        raise PSNError("Sony's response had no account ID.")
    online_id = info.get("online_id") or "psn-user"
    account_id = base64.b64encode(int(user_id).to_bytes(8, "little")).decode()
    return online_id, account_id


def make_profile(online_id: str, account_id: str, existing: dict | None = None) -> UserProfile:
    """Build a pyremoteplay profile, keeping any PS5 pairings already saved for this user."""
    hosts = (existing or {}).get("hosts", {}) if existing and existing.get("id") == account_id else {}
    return UserProfile(online_id, {"id": account_id, "hosts": hosts})
