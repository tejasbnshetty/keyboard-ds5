# SPDX-License-Identifier: AGPL-3.0-only
"""PSN sign-in, used once to get the account ID that pairing needs. The access token is
discarded; only the account ID and online ID are kept.

OAuth flow, scopes and redirect as in chiaki-ng (gui/include/psnaccountid.h). The client
ID/secret are not in the source: they come from env vars PS5REMOTE_PSN_CLIENT_ID /
PS5REMOTE_PSN_CLIENT_SECRET, or psn_client.json in the data folder, the source data/ folder,
or a personal .exe. psn_client.json takes the secret as "client_secret", or base64-encoded as
"client_secret_base64". See psn_client.example.json.
"""
from __future__ import annotations

import base64
import json
import os
import re
from urllib.parse import parse_qs, quote, urlparse

import requests
from pyremoteplay.profile import UserProfile

from . import config, keyfree

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
    if keyfree.ACTIVE:
        # Public build: only the values the user opted to take from their pyremoteplay
        # download (hash-checked, see support.py). Otherwise no sign-in: the account ID is typed.
        from . import support  # pylint: disable=import-outside-toplevel
        return support.load_sign_in(support.default_dir())
    env_id = os.environ.get("PS5REMOTE_PSN_CLIENT_ID")
    env_secret = os.environ.get("PS5REMOTE_PSN_CLIENT_SECRET")
    if env_id and env_secret:
        return env_id, env_secret
    # The data folder; from source, also the project's data\ folder; a personal .exe's bundle.
    for folder in (config.DATA_DIR, config.SOURCE_DATA_DIR, config.RESOURCES):
        if folder is None:
            continue
        path = folder / CLIENT_FILE
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                secret = data.get("client_secret")
                if not secret and data.get("client_secret_base64"):
                    # As some open-source clients store it.
                    secret = base64.b64decode(data["client_secret_base64"], validate=True).decode()
                if data.get("client_id") and secret:
                    return data["client_id"], secret
            except (OSError, ValueError, TypeError):
                continue
    return None


def is_configured() -> bool:
    return _client() is not None


def _require_client() -> tuple[str, str]:
    client = _client()
    if not client:
        raise PSNError(
            "Sign-in with PlayStation isn't set up on this PC, so enter your account ID instead. "
            "(To set up sign-in, see 'PSN sign-in values' in the README.)")
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
    """Accepts the full redirect URL or just the code."""
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
    """Returns (online_id, base64 account id)."""
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


_ONLINE_ID = re.compile(r"^[A-Za-z0-9_\-]{1,16}$")
DEFAULT_ONLINE_ID = "psn-user"


def parse_account_id(text: str) -> str:
    """A PSN account ID typed in by hand -> the base64 form pairing uses.

    Accepts the number (e.g. 1234567890123456789) or the encoded form (12 characters ending
    in '=', e.g. as chiaki-ng shows it). Both are the same 64-bit ID: 8 bytes, little-endian."""
    text = (text or "").strip().replace(" ", "")
    if not text:
        raise PSNError("Enter your account ID.")
    if text.isdigit():
        number = int(text)
        if not 0 < number < 2 ** 64:
            raise PSNError("That number is too large to be a PSN account ID.")
        return base64.b64encode(number.to_bytes(8, "little")).decode()
    try:
        raw = base64.b64decode(text + "=" * (-len(text) % 4), validate=True)
    except ValueError:
        raw = b""
    if len(raw) != 8 or not any(raw):
        raise PSNError(
            "That doesn't look like a PSN account ID. Enter the number (up to 20 digits) or the "
            "encoded form (12 characters ending in '=').")
    return base64.b64encode(raw).decode()


def check_online_id(text: str) -> str:
    """The name shown for a manually entered account. Optional; only used as a label here."""
    text = (text or "").strip()
    if not text:
        return DEFAULT_ONLINE_ID
    if not _ONLINE_ID.match(text):
        raise PSNError("The name can have up to 16 letters, numbers, - and _ (like a PSN online ID).")
    return text


def make_profile(online_id: str, account_id: str, existing: dict | None = None) -> UserProfile:
    """Keeps PS5 pairings already saved for the same account."""
    hosts = (existing or {}).get("hosts", {}) if existing and existing.get("id") == account_id else {}
    return UserProfile(online_id, {"id": account_id, "hosts": hosts})
