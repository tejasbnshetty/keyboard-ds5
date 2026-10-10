# SPDX-License-Identifier: AGPL-3.0-only
"""Remote Play support files for the key-free public build.

Remote Play needs five static key tables for the PS5 (see PROVENANCE.md, "Sony-derived
material"). Source installs use the copy in the installed pyremoteplay package. The public
.exe contains none of them: at the user's request, it fetches pyremoteplay 0.7.6 from PyPI
(or takes the file from disk), checks it against pinned SHA-256 hashes, reads the tables out
of pyremoteplay/keys.py WITHOUT executing it, and stores them in the data folder.

Optionally (opt-in in the setup wizard), the same verified wheel or sdist also provides the
PS Remote Play app's OAuth client ID and secret from pyremoteplay/oauth.py, read the same way
(parsed, never executed, hash-checked). They're stored separately in the data folder and used
only to sign in to PSN. A problem with them never affects the key tables.

Only hashes are pinned here, never key tables or sign-in values. Nothing in this module imports
pyremoteplay or config at module level: keyfree.py calls it while pyremoteplay is being imported.
"""
from __future__ import annotations

import ast
import base64
import binascii
import hashlib
import io
import json
import os
import ssl
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

PYREMOTEPLAY_VERSION = "0.7.6"
PYPI_PAGE = f"https://pypi.org/project/pyremoteplay/{PYREMOTEPLAY_VERSION}/"


@dataclass(frozen=True)
class Source:
    kind: str       # "wheel" or "sdist"
    filename: str
    url: str
    size: int
    sha256: str
    member: str     # path of keys.py inside the archive

    @property
    def oauth_member(self) -> str:
        return self.member.replace("keys.py", "oauth.py")


SOURCES = (
    Source("wheel", "pyremoteplay-0.7.6-py3-none-any.whl",
           "https://files.pythonhosted.org/packages/95/c6/"
           "1ea12b30ec895f73cd1e4c2bac3d0c4686189167d5cfbf809ed0bcc13671/"
           "pyremoteplay-0.7.6-py3-none-any.whl",
           154435, "12f645120abd613952aac50a21b3536f25b69753f567a52ed8fc39050d1c3a9c",
           "pyremoteplay/keys.py"),
    Source("sdist", "pyremoteplay-0.7.6.tar.gz",
           "https://files.pythonhosted.org/packages/38/68/"
           "168fcbe8cd5a2b2e37c7eab17e8dc0ffcb8c6a92e930ff18436221b5161a/"
           "pyremoteplay-0.7.6.tar.gz",
           141830, "42e1558cf0d3f64f4f156d09d7e63b636c064f5d2a37c063e91dda1d76b77887",
           "pyremoteplay-0.7.6/pyremoteplay/keys.py"),
)
KEYS_FILE_SIZE = 105341
KEYS_FILE_SHA256 = "54492ae5769dde47e64a5ce077c3dc5d37f22aeb0cb0bad314460af43724d669"

# The PS5 tables only (name -> size, SHA-256). PS4 ones are not used and not stored.
TABLES = {
    "HMAC_KEY_PS5": (16, "880c56eda992313f9aaa57e70e725b72b4371253beba1fabf60a83fe3d429a37"),
    "REG_KEY_0_PS5": (512, "53b11608360076562655967ca89d6bd5e9b8c05220644075bb49876c95cd3965"),
    "REG_KEY_1_PS5": (512, "3299d292a30e9be23c16a79bdd1a7cf8862a973ead751fd20d6d7c48154edeb0"),
    "SESSION_KEY_0_PS5": (3584, "1db53dc52e9259b87d3b4e6c93ed008eb3aeed3a05d8dbeb27ce12c92511beb9"),
    "SESSION_KEY_1_PS5": (3584, "22f6776ae81cc9bf2e562abee4618e3a32557875af5cd346145a5f2a5d81009b"),
}
PS4_NAMES = ("HMAC_KEY_PS4", "REG_KEY_0_PS4", "REG_KEY_1_PS4", "SESSION_KEY_0_PS4", "SESSION_KEY_1_PS4")

# PSN sign-in values (opt-in): pyremoteplay/oauth.py and the two values in it, hashes only.
OAUTH_FILE_SIZE = 6688
OAUTH_FILE_SHA256 = "5dde9d4343049f0d1b3911276c4bc688aa8951f6cd9710e7d10dd193113b2e97"
CLIENT_ID_SHA256 = "d31b32a273be2adf3f57d3729646862c86917756a13e3b680e1c50e94f10da43"
CLIENT_SECRET_SHA256 = "ae60b6ee79a8db97e63f931d0c9176a20dcf9a398297a6650140761267dce49d"  # decoded

TABLES_FILE = "remoteplay-tables.json"
SIGN_IN_FILE = "psn-sign-in.json"
FORMAT = 1
MAX_FILE = 2_000_000          # bytes accepted from a download or a chosen file
DOWNLOAD_TIMEOUT = 30


class SupportError(Exception):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# Reading the tables out of keys.py, as data -----------------------------------------------

def _literal_bytes(node: ast.AST) -> bytes | None:
    """b"..." or bytes([0x.., ...]) / bytearray([...]) -> bytes; anything else -> None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, bytes):
        return node.value
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in ("bytes", "bytearray") and len(node.args) == 1 and not node.keywords
            and isinstance(node.args[0], (ast.List, ast.Tuple))):
        values = []
        for elt in node.args[0].elts:
            if not (isinstance(elt, ast.Constant) and type(elt.value) is int and 0 <= elt.value <= 255):
                return None
            values.append(elt.value)
        return bytes(values)
    return None


def parse_keys_source(source: bytes) -> dict[str, bytes]:
    """The PS5 tables from pyremoteplay's keys.py. The file is parsed, never executed."""
    try:
        tree = ast.parse(source.decode("utf-8"), filename="keys.py")
    except (SyntaxError, UnicodeDecodeError, ValueError) as err:
        raise SupportError("The keys file couldn't be read.") from err
    tables = {}
    for stmt in tree.body:
        if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id in TABLES):
            value = _literal_bytes(stmt.value)
            if value is None:
                raise SupportError(f"{stmt.targets[0].id} in the keys file isn't plain data.")
            tables[stmt.targets[0].id] = value
    return tables


def check_tables(tables: dict[str, bytes]) -> dict[str, bytes]:
    """Every PS5 table present with the pinned size and hash. Errors name the table only."""
    for name, (size, digest) in TABLES.items():
        value = tables.get(name)
        if not isinstance(value, (bytes, bytearray)):
            raise SupportError(f"{name} is missing from the support files.")
        if len(value) != size or _sha(bytes(value)) != digest:
            raise SupportError(f"{name} doesn't match the expected table (the file may be damaged "
                               "or altered).")
    return {name: bytes(tables[name]) for name in TABLES}


def parse_oauth_source(source: bytes) -> tuple[str, str]:
    """(client ID, client secret) from pyremoteplay's oauth.py, parsed and never executed.
    The secret is stored there base64-encoded; this returns it decoded."""
    try:
        tree = ast.parse(source.decode("utf-8"), filename="oauth.py")
    except (SyntaxError, UnicodeDecodeError, ValueError) as err:
        raise SupportError("The sign-in file couldn't be read.") from err
    found = {}
    for stmt in tree.body:
        if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id in ("__CLIENT_ID", "__CLIENT_SECRET")):
            if not (isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)):
                raise SupportError(f"{stmt.targets[0].id} in the sign-in file isn't plain data.")
            found[stmt.targets[0].id] = stmt.value.value
    if set(found) != {"__CLIENT_ID", "__CLIENT_SECRET"}:
        raise SupportError("The sign-in values weren't found in the file.")
    try:
        secret = base64.b64decode(found["__CLIENT_SECRET"], validate=True).decode("utf-8")
    except (binascii.Error, ValueError) as err:
        raise SupportError("The sign-in secret in the file isn't in the expected form.") from err
    return found["__CLIENT_ID"], secret


def check_client(client_id: str, secret: str) -> tuple[str, str]:
    """Both sign-in values match their pinned hashes."""
    if not (isinstance(client_id, str) and isinstance(secret, str)
            and _sha(client_id.encode()) == CLIENT_ID_SHA256
            and _sha(secret.encode()) == CLIENT_SECRET_SHA256):
        raise SupportError("The sign-in values don't match the expected ones (the file may be "
                           "damaged or altered).")
    return client_id, secret


def _client_from_oauth_file(data: bytes) -> tuple[str, str]:
    if _sha(data) != OAUTH_FILE_SHA256:
        raise SupportError(f"That isn't pyremoteplay {PYREMOTEPLAY_VERSION}'s oauth.py, or it has "
                           "been changed (its checksum doesn't match).")
    return check_client(*parse_oauth_source(data))


def _from_keys_file(data: bytes) -> dict[str, bytes]:
    if _sha(data) != KEYS_FILE_SHA256:
        raise SupportError(f"That isn't pyremoteplay {PYREMOTEPLAY_VERSION}'s keys.py, or it has "
                           "been changed (its checksum doesn't match).")
    return check_tables(parse_keys_source(data))


@dataclass
class Extracted:
    """What a file or download provided. Either part can be missing: a problem with the
    sign-in values never stops the key tables from being used, and vice versa."""
    tables: dict[str, bytes] | None
    client: tuple[str, str] | None
    description: str
    client_problem: str = ""    # why there are no sign-in values (for the user)


def _read_member(data: bytes, source: Source, member: str, limit: int) -> bytes:
    name = member.rsplit("/", 1)[-1]
    try:
        if source.kind == "wheel":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                info = archive.getinfo(member)
                if info.file_size > limit:
                    raise SupportError(f"{name} in the archive is unexpectedly large.")
                return archive.read(info)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            info = archive.getmember(member)
            if not info.isfile() or info.size > limit:
                raise SupportError(f"{name} in the archive isn't a normal file.")
            return archive.extractfile(info).read()
    except (KeyError, zipfile.BadZipFile, tarfile.TarError, OSError, EOFError) as err:
        raise SupportError(f"{name} couldn't be read from the archive.") from err


def _from_archive(data: bytes, source: Source) -> Extracted:
    """A pinned (already hash-checked) wheel or sdist -> tables and, if possible, sign-in values."""
    tables = _from_keys_file(_read_member(data, source, source.member, KEYS_FILE_SIZE * 2))
    description = f"pyremoteplay {PYREMOTEPLAY_VERSION} {source.kind}"
    try:
        client = _client_from_oauth_file(
            _read_member(data, source, source.oauth_member, OAUTH_FILE_SIZE * 2))
    except SupportError as err:
        return Extracted(tables, None, description, str(err))
    return Extracted(tables, client, description)


def extract_bytes(data: bytes) -> Extracted:
    """A pinned wheel or sdist (tables + sign-in values), pyremoteplay's keys.py (tables only),
    or its oauth.py (sign-in values only). Anything else is refused."""
    if len(data) > MAX_FILE:
        raise SupportError("That file is too large to be pyremoteplay or one of its files.")
    digest = _sha(data)
    for source in SOURCES:
        if digest == source.sha256:
            return _from_archive(data, source)
    if data[:4] == b"PK\x03\x04" or data[:2] == b"\x1f\x8b":
        raise SupportError(f"That archive isn't the pyremoteplay {PYREMOTEPLAY_VERSION} download "
                           "from PyPI (its checksum doesn't match).")
    if digest == OAUTH_FILE_SHA256:
        return Extracted(None, _client_from_oauth_file(data),
                         f"pyremoteplay {PYREMOTEPLAY_VERSION} oauth.py")
    return Extracted(_from_keys_file(data), None, f"pyremoteplay {PYREMOTEPLAY_VERSION} keys.py",
                     "keys.py only has the key tables; the sign-in values are in the full "
                     "package (or its oauth.py).")


def extract_file(path: str | Path) -> Extracted:
    path = Path(path)
    try:
        if path.stat().st_size > MAX_FILE:
            raise SupportError("That file is too large to be pyremoteplay or one of its files.")
        data = path.read_bytes()
    except OSError as err:
        raise SupportError(f"Couldn't read {path.name} ({err.__class__.__name__}).") from err
    return extract_bytes(data)


def tables_from_bytes(data: bytes) -> tuple[dict[str, bytes], str]:
    """Key tables only, from a pinned wheel or sdist or pyremoteplay's keys.py."""
    found = extract_bytes(data)
    if found.tables is None:
        raise SupportError("That file only has the sign-in values, not the key tables.")
    return found.tables, found.description


def tables_from_file(path: str | Path) -> tuple[dict[str, bytes], str]:
    found = extract_file(path)
    if found.tables is None:
        raise SupportError("That file only has the sign-in values, not the key tables.")
    return found.tables, found.description


# Download ----------------------------------------------------------------------------------

def _fetch(url: str) -> bytes:
    try:
        import certifi  # pylint: disable=import-outside-toplevel
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    request = urllib.request.Request(url, headers={"User-Agent": "KeyboardDS5-support-files"})
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT, context=context) as resp:
        data = resp.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise SupportError("The download was larger than expected.")
    return data


def download_all(fetch: Callable[[str], bytes] = _fetch) -> Extracted:
    """Only call this when the user asked for it. Tries the wheel, then the sdist."""
    problems = []
    for source in SOURCES:
        try:
            data = fetch(source.url)
        except (urllib.error.URLError, OSError, SupportError, ValueError) as err:
            problems.append(f"{source.kind}: {getattr(err, 'reason', err)}")
            continue
        if _sha(data) != source.sha256:
            problems.append(f"{source.kind}: checksum didn't match")
            continue
        found = _from_archive(data, source)
        found.description = f"PyPI, {found.description}"
        return found
    raise SupportError("Couldn't download pyremoteplay from PyPI (" + "; ".join(problems) + "). "
                       "Check the internet connection, or use \"I have the file\".")


def download(fetch: Callable[[str], bytes] = _fetch) -> tuple[dict[str, bytes], str]:
    """Key tables only (see download_all)."""
    found = download_all(fetch)
    return found.tables, found.description


# Stored copy in the data folder -----------------------------------------------------------

def default_dir() -> Path:
    from . import config  # pylint: disable=import-outside-toplevel
    return config.DATA_DIR / "support"


def save(support_dir: Path, tables: dict[str, bytes], description: str) -> None:
    tables = check_tables(tables)
    support_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": FORMAT,
        "pyremoteplay": PYREMOTEPLAY_VERSION,
        "source": description,
        "installed": time.strftime("%Y-%m-%d %H:%M"),
        "tables": {name: value.hex() for name, value in tables.items()},
    }
    path = support_dir / TABLES_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read(support_dir: Path) -> tuple[dict | None, str]:
    path = support_dir / TABLES_FILE
    if not path.is_file():
        return None, "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        tables = {name: bytes.fromhex(payload["tables"][name]) for name in TABLES}
        check_tables(tables)
    except (OSError, ValueError, KeyError, TypeError, SupportError):
        return None, "invalid"
    return {"tables": tables, "source": payload.get("source", ""),
            "installed": payload.get("installed", "")}, "ready"


def load_tables(support_dir: Path) -> dict[str, bytes] | None:
    """The validated tables, or None if missing or not valid. Never raises."""
    found, _ = _read(support_dir)
    return found["tables"] if found else None


def status(support_dir: Path) -> dict:
    found, state = _read(support_dir)
    return {"state": state, "source": found["source"] if found else "",
            "installed": found["installed"] if found else ""}


def _delete(support_dir: Path, filename: str) -> None:
    for name in (filename, Path(filename).with_suffix(".tmp").name):
        try:
            (support_dir / name).unlink()
        except FileNotFoundError:
            pass


def remove(support_dir: Path) -> None:
    """All support files: the key tables and any sign-in values."""
    _delete(support_dir, TABLES_FILE)
    _delete(support_dir, SIGN_IN_FILE)


# PSN sign-in values (opt-in), stored separately from the tables ------------------------------

def save_sign_in(support_dir: Path, client: tuple[str, str], description: str) -> None:
    client_id, secret = check_client(*client)
    support_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": FORMAT,
        "pyremoteplay": PYREMOTEPLAY_VERSION,
        "source": description,
        "installed": time.strftime("%Y-%m-%d %H:%M"),
        "client_id": client_id,
        "client_secret": secret,
    }
    path = support_dir / SIGN_IN_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read_sign_in(support_dir: Path) -> tuple[dict | None, str]:
    path = support_dir / SIGN_IN_FILE
    if not path.is_file():
        return None, "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        client = check_client(payload["client_id"], payload["client_secret"])
    except (OSError, ValueError, KeyError, TypeError, SupportError):
        return None, "invalid"
    return {"client": client, "source": payload.get("source", ""),
            "installed": payload.get("installed", "")}, "ready"


def load_sign_in(support_dir: Path) -> tuple[str, str] | None:
    """(client ID, secret) if installed and valid, else None. Never raises."""
    found, _ = _read_sign_in(support_dir)
    return found["client"] if found else None


def sign_in_status(support_dir: Path) -> dict:
    found, state = _read_sign_in(support_dir)
    return {"state": state, "source": found["source"] if found else "",
            "installed": found["installed"] if found else ""}


def remove_sign_in(support_dir: Path) -> None:
    _delete(support_dir, SIGN_IN_FILE)


def ready() -> bool:
    """True when Remote Play can run: a source install, or a key-free build with tables loaded."""
    from . import keyfree  # pylint: disable=import-outside-toplevel
    return not keyfree.ACTIVE or keyfree.TABLES_OK
