# SPDX-License-Identifier: AGPL-3.0-only
"""Opt-in PSN sign-in values from the downloaded pyremoteplay. Compared by hash; never printed."""
import base64
import hashlib
import io
import json
import tarfile
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
import pyremoteplay.keys as installed_keys
import pyremoteplay.oauth as installed_oauth

from ps5remote import keyfree, support

KEYS_PY = Path(installed_keys.__file__).read_bytes()
OAUTH_PY = Path(installed_oauth.__file__).read_bytes()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def real_client():
    """The real values, read the same way the app does (for comparisons only)."""
    return support.parse_oauth_source(OAUTH_PY)


def real_tables():
    return {name: bytes(getattr(installed_keys, name)) for name in support.TABLES}


# Pins and the "no values in the source" guarantee -------------------------------------------

def test_pins_match_the_installed_oauth_file():
    client_id, secret = real_client()
    assert sha(OAUTH_PY) == support.OAUTH_FILE_SHA256 and len(OAUTH_PY) == support.OAUTH_FILE_SIZE
    assert sha(client_id.encode()) == support.CLIENT_ID_SHA256
    assert sha(secret.encode()) == support.CLIENT_SECRET_SHA256


def test_no_sign_in_values_in_the_source():
    """support.py and keyfree.py hold hashes only: neither value in any form."""
    client_id, secret = real_client()
    forms = []
    for value in (client_id, secret):
        raw = value.encode()
        forms += [raw, base64.b64encode(raw), raw.hex().encode(), value.encode("utf-16-le"),
                  base64.b64encode(raw).rstrip(b"=")]
    forms += [client_id.replace("-", "").encode()]
    for module in (support, keyfree):
        text = Path(module.__file__).read_bytes()
        for form in forms:
            assert form not in text, f"a sign-in value appears in {Path(module.__file__).name}"


# Reading oauth.py as data ------------------------------------------------------------------------

def test_parse_real_oauth_file():
    client_id, secret = real_client()
    assert len(client_id) == 36 and len(secret) == 16
    assert support.check_client(client_id, secret) == (client_id, secret)


def test_parse_never_executes_code(tmp_path):
    marker = tmp_path / "ran.txt"
    evil = (f"import pathlib\npathlib.Path({str(marker)!r}).write_text('x')\n"
            "__CLIENT_ID = 'abc'\n__CLIENT_SECRET = 'c2VjcmV0'\n").encode()
    assert support.parse_oauth_source(evil) == ("abc", "secret")
    assert not marker.exists()


@pytest.mark.parametrize("source, message", [
    (b"__CLIENT_ID = get()\n__CLIENT_SECRET = 'eA=='\n", "isn't plain data"),
    (b"__CLIENT_ID = 'a'\n", "weren't found"),
    (b"__CLIENT_ID = 'a'\n__CLIENT_SECRET = 'not base64!!'\n", "expected form"),
    (b"\xff\xfe not python", "couldn't be read"),
])
def test_parse_rejects(source, message):
    with pytest.raises(support.SupportError, match=message):
        support.parse_oauth_source(source)


def test_wrong_values_rejected():
    client_id, secret = real_client()
    with pytest.raises(support.SupportError, match="don't match"):
        support.check_client(client_id, secret + "x")
    with pytest.raises(support.SupportError, match="don't match"):
        support.check_client("00000000-0000-0000-0000-000000000000", secret)


# Files: archives, keys.py, oauth.py -----------------------------------------------------------------

def make_wheel(keys=KEYS_PY, oauth=OAUTH_PY) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pyremoteplay/keys.py", keys)
        if oauth is not None:
            z.writestr("pyremoteplay/oauth.py", oauth)
    return buf.getvalue()


def make_sdist(keys=KEYS_PY, oauth=OAUTH_PY) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in (("keys.py", keys), ("oauth.py", oauth)):
            if data is None:
                continue
            info = tarfile.TarInfo(f"pyremoteplay-0.7.6/pyremoteplay/{name}")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def pinned_to(monkeypatch):
    def pin(wheel: bytes = b"", sdist: bytes = b""):
        wheel_src, sdist_src = support.SOURCES
        monkeypatch.setattr(support, "SOURCES", (
            replace(wheel_src, sha256=sha(wheel), size=len(wheel)),
            replace(sdist_src, sha256=sha(sdist), size=len(sdist))))
    return pin


@pytest.mark.parametrize("maker", [make_wheel, make_sdist])
def test_archive_gives_tables_and_sign_in_values(pinned_to, maker):
    data = maker()
    pinned_to(**{"wheel" if maker is make_wheel else "sdist": data})
    found = support.extract_bytes(data)
    assert found.tables == real_tables() and found.client == real_client()
    assert not found.client_problem


def test_altered_oauth_in_a_pinned_archive_keeps_the_tables(pinned_to):
    """Independent failure: a bad oauth.py never stops the key tables."""
    data = make_wheel(oauth=OAUTH_PY.replace(b"__CLIENT_ID", b"__CLIENT_ID ", 1))
    pinned_to(wheel=data)
    found = support.extract_bytes(data)
    assert found.tables == real_tables() and found.client is None
    assert "checksum" in found.client_problem


def test_archive_without_oauth_keeps_the_tables(pinned_to):
    data = make_wheel(oauth=None)
    pinned_to(wheel=data)
    found = support.extract_bytes(data)
    assert found.tables == real_tables() and found.client is None and found.client_problem


def test_keys_file_gives_tables_only():
    found = support.extract_bytes(KEYS_PY)
    assert found.tables == real_tables() and found.client is None
    assert "oauth.py" in found.client_problem


def test_oauth_file_gives_sign_in_values_only(tmp_path):
    path = tmp_path / "oauth.py"
    path.write_bytes(OAUTH_PY)
    found = support.extract_file(path)
    assert found.tables is None and found.client == real_client()
    with pytest.raises(support.SupportError, match="only has the sign-in values"):
        support.tables_from_file(path)


def test_tampered_oauth_file_rejected():
    tampered = OAUTH_PY.replace(b"__REDIRECT_URL", b"__REDIRECT_URL ", 1)
    with pytest.raises(support.SupportError, match="checksum"):
        support.extract_bytes(tampered)


def test_download_all_includes_sign_in_values(pinned_to):
    wheel = make_wheel()
    pinned_to(wheel=wheel, sdist=make_sdist())
    found = support.download_all(lambda url: wheel)
    assert found.tables == real_tables() and found.client == real_client()
    assert found.description.startswith("PyPI, ")


# Storage -----------------------------------------------------------------------------------------

def test_sign_in_storage_round_trip(tmp_path):
    folder = tmp_path / "support"
    assert support.sign_in_status(folder)["state"] == "missing" and support.load_sign_in(folder) is None
    support.save_sign_in(folder, real_client(), "test")
    assert support.load_sign_in(folder) == real_client()
    assert support.sign_in_status(folder)["state"] == "ready"
    assert not (folder / support.TABLES_FILE).exists()      # separate from the tables
    support.remove_sign_in(folder)
    assert support.sign_in_status(folder)["state"] == "missing"


def test_tampered_sign_in_file_disables_sign_in_only(tmp_path):
    folder = tmp_path / "support"
    support.save(folder, real_tables(), "test")
    support.save_sign_in(folder, real_client(), "test")
    path = folder / support.SIGN_IN_FILE
    payload = json.loads(path.read_text())
    payload["client_secret"] = payload["client_secret"][:-1] + "?"
    path.write_text(json.dumps(payload))
    assert support.load_sign_in(folder) is None and support.sign_in_status(folder)["state"] == "invalid"
    assert support.load_tables(folder) == real_tables()       # tables unaffected


def test_save_sign_in_refuses_wrong_values(tmp_path):
    with pytest.raises(support.SupportError):
        support.save_sign_in(tmp_path, ("x", "y"), "bad")
    assert not (tmp_path / support.SIGN_IN_FILE).exists()


@pytest.mark.skipif(not __import__("os").environ.get("KEYBOARDDS5_NETWORK_TESTS"),
                    reason="set KEYBOARDDS5_NETWORK_TESTS=1 to download from PyPI")
def test_real_download_includes_sign_in_values():
    found = support.download_all()
    assert found.tables == real_tables() and found.client == real_client()


def test_remove_support_files_removes_both(tmp_path):
    support.save(tmp_path, real_tables(), "t")
    support.save_sign_in(tmp_path, real_client(), "t")
    support.remove(tmp_path)
    assert not any(tmp_path.iterdir())
