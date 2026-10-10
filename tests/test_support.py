# SPDX-License-Identifier: AGPL-3.0-only
"""Support files for the key-free build. Values are compared by hash; nothing is printed."""
import hashlib
import io
import json
import os
import tarfile
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
import pyremoteplay.keys as installed

from ps5remote import keyfree, ps5, support

KEYS_PY = Path(installed.__file__).read_bytes()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def real_tables():
    return {name: bytes(getattr(installed, name)) for name in support.TABLES}


# The pins themselves ---------------------------------------------------------------------

def test_pins_match_the_installed_pyremoteplay():
    """Hashes in support.py describe exactly the tables pyremoteplay 0.7.6 ships."""
    assert sha(KEYS_PY) == support.KEYS_FILE_SHA256 and len(KEYS_PY) == support.KEYS_FILE_SIZE
    for name, (size, digest) in support.TABLES.items():
        value = bytes(getattr(installed, name))
        assert len(value) == size and sha(value) == digest, name


def test_only_ps5_tables_are_pinned():
    assert set(support.TABLES) == {"HMAC_KEY_PS5", "REG_KEY_0_PS5", "REG_KEY_1_PS5",
                                   "SESSION_KEY_0_PS5", "SESSION_KEY_1_PS5"}
    assert all(name.endswith("_PS4") for name in support.PS4_NAMES)


def test_no_key_values_in_the_source():
    """support.py and keyfree.py hold hashes only: no table, not even a slice of one."""
    for module in (support, keyfree):
        text = Path(module.__file__).read_bytes()
        for value in real_tables().values():
            assert value[:12] not in text and value[:12].hex().encode() not in text


# Reading keys.py as data -------------------------------------------------------------------

def test_parse_real_keys_file():
    assert support.parse_keys_source(KEYS_PY) == real_tables()


def test_parse_never_executes_code(tmp_path):
    marker = tmp_path / "ran.txt"
    evil = (f"import pathlib\npathlib.Path({str(marker)!r}).write_text('x')\n"
            "HMAC_KEY_PS5 = b'0123456789abcdef'\n").encode()
    tables = support.parse_keys_source(evil)
    assert not marker.exists()
    assert tables == {"HMAC_KEY_PS5": b"0123456789abcdef"}


@pytest.mark.parametrize("source", [
    b"HMAC_KEY_PS5 = open('x').read()\n",
    b"HMAC_KEY_PS5 = bytes(16)\n",
    b"HMAC_KEY_PS5 = bytes([1, 2, 300])\n",
    b"HMAC_KEY_PS5 = bytes([x for x in range(16)])\n",
    b"HMAC_KEY_PS5 = 'text'\n",
])
def test_parse_rejects_non_literal_tables(source):
    with pytest.raises(support.SupportError, match="isn't plain data"):
        support.parse_keys_source(source)


def test_parse_rejects_garbage():
    with pytest.raises(support.SupportError):
        support.parse_keys_source(b"\xff\xfe not python")


def test_check_tables_names_the_bad_table_only():
    tables = real_tables()
    tables["REG_KEY_1_PS5"] = bytes(512)
    with pytest.raises(support.SupportError) as err:
        support.check_tables(tables)
    assert "REG_KEY_1_PS5" in str(err.value)
    del tables["SESSION_KEY_0_PS5"]
    with pytest.raises(support.SupportError, match="missing"):
        support.check_tables({k: v for k, v in real_tables().items() if k != "HMAC_KEY_PS5"})


# Files: keys.py, wheel, sdist, tampered -----------------------------------------------------

def test_keys_file_accepted():
    tables, description = support.tables_from_bytes(KEYS_PY)
    assert tables == real_tables() and "keys.py" in description


def test_tampered_keys_file_rejected():
    tampered = bytearray(KEYS_PY)
    at = tampered.index(b"0x", 2000)
    tampered[at + 2] = ord("0") if tampered[at + 2] != ord("0") else ord("1")
    with pytest.raises(support.SupportError, match="checksum"):
        support.tables_from_bytes(bytes(tampered))


def make_wheel(keys: bytes = KEYS_PY, member="pyremoteplay/keys.py") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pyremoteplay/__init__.py", "")
        z.writestr(member, keys)
    return buf.getvalue()


def make_sdist(keys: bytes = KEYS_PY, member="pyremoteplay-0.7.6/pyremoteplay/keys.py") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo(member)
        info.size = len(keys)
        t.addfile(info, io.BytesIO(keys))
    return buf.getvalue()


@pytest.fixture
def pinned_to(monkeypatch):
    """Point the wheel/sdist pins at test archives (the real ones are checked by the network test)."""
    def pin(wheel: bytes = b"", sdist: bytes = b""):
        wheel_src, sdist_src = support.SOURCES
        monkeypatch.setattr(support, "SOURCES", (
            replace(wheel_src, sha256=sha(wheel), size=len(wheel)),
            replace(sdist_src, sha256=sha(sdist), size=len(sdist))))
    return pin


def test_pinned_wheel_accepted(pinned_to):
    wheel = make_wheel()
    pinned_to(wheel=wheel)
    tables, description = support.tables_from_bytes(wheel)
    assert tables == real_tables() and "wheel" in description


def test_pinned_sdist_accepted(pinned_to):
    sdist = make_sdist()
    pinned_to(sdist=sdist)
    tables, description = support.tables_from_bytes(sdist)
    assert tables == real_tables() and "sdist" in description


def test_unpinned_archives_rejected(pinned_to):
    pinned_to(wheel=make_wheel(), sdist=make_sdist())
    other = make_wheel(member="pyremoteplay/keys.py") + b"extra"
    with pytest.raises(support.SupportError, match="checksum"):
        support.tables_from_bytes(make_wheel(keys=KEYS_PY + b"\n"))
    with pytest.raises(support.SupportError, match="checksum"):
        support.tables_from_bytes(make_sdist(keys=KEYS_PY + b"\n"))
    with pytest.raises(support.SupportError):
        support.tables_from_bytes(other)


def test_pinned_archive_with_altered_keys_rejected(pinned_to):
    """Even if an archive's own hash were pinned, its keys.py must match too."""
    wheel = make_wheel(keys=KEYS_PY.replace(b"0x", b"0X", 1))
    pinned_to(wheel=wheel)
    with pytest.raises(support.SupportError, match="checksum"):
        support.tables_from_bytes(wheel)


def test_pinned_archive_without_keys_rejected(pinned_to):
    wheel = make_wheel(member="pyremoteplay/other.py")
    pinned_to(wheel=wheel)
    with pytest.raises(support.SupportError, match="couldn't be read"):
        support.tables_from_bytes(wheel)


def test_oversized_file_rejected(tmp_path):
    big = tmp_path / "big.whl"
    big.write_bytes(b"0" * (support.MAX_FILE + 1))
    with pytest.raises(support.SupportError, match="too large"):
        support.tables_from_file(big)


def test_file_from_disk(tmp_path):
    path = tmp_path / "keys.py"
    path.write_bytes(KEYS_PY)
    assert support.tables_from_file(path)[0] == real_tables()
    with pytest.raises(support.SupportError, match="Couldn't read"):
        support.tables_from_file(tmp_path / "nope.whl")


# Download (no network: fetch is faked) -------------------------------------------------------

def test_download_uses_the_wheel(pinned_to):
    wheel, sdist = make_wheel(), make_sdist()
    pinned_to(wheel=wheel, sdist=sdist)
    urls = []
    tables, description = support.download(lambda url: urls.append(url) or wheel)
    assert tables == real_tables() and "wheel" in description and "PyPI" in description
    assert urls == [support.SOURCES[0].url]


def test_download_falls_back_to_the_sdist(pinned_to):
    wheel, sdist = make_wheel(), make_sdist()
    pinned_to(wheel=wheel, sdist=sdist)

    def fetch(url):
        if url == support.SOURCES[0].url:
            raise OSError("connection reset")
        return sdist
    tables, description = support.download(fetch)
    assert tables == real_tables() and "sdist" in description


def test_download_rejects_wrong_content(pinned_to):
    pinned_to(wheel=make_wheel(), sdist=make_sdist())
    with pytest.raises(support.SupportError, match="checksum didn't match.*checksum didn't match"):
        support.download(lambda url: b"<html>captive portal</html>")


def test_download_failure_suggests_the_file_option():
    def offline(url):
        raise OSError("no network")
    with pytest.raises(support.SupportError, match="I have the file"):
        support.download(offline)


@pytest.mark.parametrize("url", ["http://files.pythonhosted.org/packages/x.whl",
                                 "https://evil.example/packages/x.whl",
                                 "file:///C:/Windows/win.ini",
                                 "https://files.pythonhosted.org.evil.example/packages/x.whl"])
def test_fetch_refuses_anything_but_pypi_https(url):
    with pytest.raises(support.SupportError, match="PyPI over https"):
        support._fetch(url)


def test_real_urls_are_pypi_https():
    for source in support.SOURCES:
        assert source.url.startswith("https://files.pythonhosted.org/packages/")
        assert source.url.endswith(source.filename)


# Stored copy ---------------------------------------------------------------------------------

def test_save_load_status_remove(tmp_path):
    folder = tmp_path / "support"
    assert support.status(folder)["state"] == "missing"
    assert support.load_tables(folder) is None
    support.save(folder, real_tables(), "test source")
    assert support.load_tables(folder) == real_tables()
    st = support.status(folder)
    assert st["state"] == "ready" and st["source"] == "test source" and st["installed"]
    support.remove(folder)
    assert support.status(folder)["state"] == "missing"


def test_tampered_stored_tables_are_not_used(tmp_path):
    folder = tmp_path / "support"
    support.save(folder, real_tables(), "test")
    path = folder / support.TABLES_FILE
    payload = json.loads(path.read_text())
    hexed = payload["tables"]["SESSION_KEY_1_PS5"]
    payload["tables"]["SESSION_KEY_1_PS5"] = ("0" if hexed[0] != "0" else "1") + hexed[1:]
    path.write_text(json.dumps(payload))
    assert support.load_tables(folder) is None
    assert support.status(folder)["state"] == "invalid"
    path.write_text("{not json")
    assert support.status(folder)["state"] == "invalid"


def test_save_refuses_bad_tables(tmp_path):
    with pytest.raises(support.SupportError):
        support.save(tmp_path, {"HMAC_KEY_PS5": b"x"}, "bad")
    assert not (tmp_path / support.TABLES_FILE).exists()


# The gate ------------------------------------------------------------------------------------

def test_source_installs_are_always_ready():
    assert keyfree.ACTIVE is False and support.ready()


def test_keyfree_build_without_tables_refuses_to_pair(monkeypatch):
    monkeypatch.setattr(keyfree, "ACTIVE", True)
    monkeypatch.setattr(keyfree, "TABLES_OK", False)
    monkeypatch.setattr(ps5, "Device", lambda *a: pytest.fail("contacted the PS5"))
    with pytest.raises(ps5.SupportMissing, match="support files"):
        ps5.pair_console("1.2.3.4", "me", "12345678", account_id="AQAAAAAAAAA=")


@pytest.mark.skipif(not os.environ.get("KEYBOARDDS5_NETWORK_TESTS"),
                    reason="set KEYBOARDDS5_NETWORK_TESTS=1 to download from PyPI")
def test_real_download_from_pypi():
    tables, description = support.download()
    assert tables == real_tables() and "wheel" in description
