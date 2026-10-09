"""PSN sign-in, used once to learn the account ID that Remote Play pairing needs.

Uses the same OAuth client, scopes and redirect as chiaki-ng (actively maintained),
rather than pyremoteplay's older login URL. The access token is used once and discarded;
only the derived account ID (and PSN online ID, used as a profile name) is kept.
"""
from __future__ import annotations

import base64
from urllib.parse import parse_qs, quote, urlparse

import requests
from pyremoteplay.profile import UserProfile

CLIENT_ID = "<PSN_CLIENT_ID>"
# Public client secret of Sony's Remote Play app, also embedded in chiaki-ng and pyremoteplay.
CLIENT_SECRET = "<PSN_CLIENT_SECRET>"
REDIRECT_URL = "https://remoteplay.dl.playstation.net/remoteplay/redirect"
SCOPES = (
    "psn:clientapp referenceDataService:countryConfig.read "
    "pushNotification:webSocket.desktop.connect "
    "sessionManager:remotePlaySession.system.update"
)
TOKEN_URL = "https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/token"
LOGIN_URL = (
    "https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/authorize"
    "?service_entity=urn:service-entity:psn&response_type=code"
    f"&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URL}&scope={quote(SCOPES)}"
    "&request_locale=en_US&ui=pr&service_logo=ps&layout_type=popup"
    "&smcid=remoteplay&prompt=always&PlatformPrivacyWs1=minimal&"
)


class PSNError(Exception):
    pass


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
            "address bar after signing in (it contains 'redirect?code=')."
        )
    return code


def fetch_account(code: str) -> tuple[str, str]:
    """Exchange the sign-in code for (online_id, base64 account id)."""
    auth = (CLIENT_ID, CLIENT_SECRET)
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
            "a minute or two and work only once. Run the login again."
        )
    token = resp.json().get("access_token")
    if not token:
        raise PSNError("Sony's response had no access token.")

    resp = requests.get(f"{TOKEN_URL}/{token}", auth=auth, timeout=15)
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
