# SPDX-License-Identifier: AGPL-3.0-only
"""Fail if a built public .exe (or one-folder build) contains Sony key material.

Usage:  python tools/check_keyfree.py dist\\KeyboardDS5            (one-folder build)
        python tools/check_keyfree.py dist\\KeyboardDS5.exe        (one-file build)

Reference values are read from the installed pyremoteplay and pyps4-2ndscreen packages (the
build machine has them). They are compared, never printed: the report names what was found and
where. Checked:
  - the 10 key tables (PS5 and PS4) from pyremoteplay.keys
  - the PSN client ID and secret (plain, base64, UTF-16) from pyremoteplay / pyps4-2ndscreen
  - pyps4-2ndscreen's PUBLIC_KEY and RANDOM_SEED
  - module names: the real pyremoteplay.keys / pyremoteplay.oauth / pyps4_2ndscreen must be
    absent, ps5remote.keyfree present; no psn_client.json or personal-build marker anywhere
Every file, every archive member and every compiled module is searched: raw bytes, zip members,
and compiled constants (lists of numbers are turned back into bytes, as bytes([0x..]) compiles).
Low-variety values (fewer than 8 distinct bytes, e.g. RANDOM_SEED) match unrelated binaries by
chance, so they are only searched for in compiled constants. Nothing is executed. Exit code 0 = clean, 1 = something found, 2 = couldn't check.
"""
from __future__ import annotations

import ast
import base64
import importlib.util
import io
import marshal
import re
import sys
import types
import warnings
import zipfile
import zlib
from pathlib import Path

FORBIDDEN_MODULES = ("pyremoteplay.keys", "pyremoteplay.oauth")
FORBIDDEN_PREFIXES = ("pyps4_2ndscreen",)
REQUIRED_MODULES = ("ps5remote.keyfree", "ps5remote.support")
FORBIDDEN_NAMES = ("psn_client.json", "PERSONAL_BUILD", "-personal.exe")


# Reference values (from the installed packages; never printed) -----------------------------

def _source(module: str) -> str:
    spec = importlib.util.find_spec(module)
    if not spec or not spec.origin:
        raise SystemExit(f"check_keyfree: {module} isn't installed on this machine (needed as the "
                         "reference).")
    return Path(spec.origin).read_text(encoding="utf-8")


def _literal_tables(source: str) -> dict[str, bytes]:
    tables = {}
    for stmt in ast.parse(source).body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            name, node = stmt.targets[0].id, stmt.value
            if isinstance(node, ast.Constant) and isinstance(node.value, (bytes, str)):
                tables[name] = node.value if isinstance(node.value, bytes) else node.value.encode()
            elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
                try:
                    tables[name] = bytes(ast.literal_eval(node.args[0]))
                except (ValueError, TypeError):
                    pass
            elif isinstance(node, ast.JoinedStr) or isinstance(node, ast.BinOp):
                continue
    return tables


def reference_needles() -> dict[str, bytes]:
    """label -> bytes to look for. Labels are safe to print; values never are."""
    needles = {}
    keys = _literal_tables(_source("pyremoteplay.keys"))
    for name in ("HMAC_KEY_PS5", "REG_KEY_0_PS5", "REG_KEY_1_PS5", "SESSION_KEY_0_PS5",
                 "SESSION_KEY_1_PS5", "HMAC_KEY_PS4", "REG_KEY_0_PS4", "REG_KEY_1_PS4",
                 "SESSION_KEY_0_PS4", "SESSION_KEY_1_PS4"):
        needles[f"key table {name}"] = keys[name]
    rp_oauth = _source("pyremoteplay.oauth")
    client_id = re.search(r'__CLIENT_ID = "([^"]+)"', rp_oauth).group(1)
    secret_b64 = re.search(r'__CLIENT_SECRET = "([^"]+)"', rp_oauth).group(1)
    secret = base64.b64decode(secret_b64).decode()
    for label, value in (("PSN client ID", client_id), ("PSN client secret", secret),
                         ("PSN client secret (base64)", secret_b64)):
        needles[label] = value.encode()
        needles[label + " (UTF-16)"] = value.encode("utf-16-le")
    ps4_oauth = _literal_tables(_source("pyps4_2ndscreen.oauth"))
    if ps4_oauth.get("CLIENT_SECRET"):
        needles["PSN client secret (pyps4-2ndscreen)"] = ps4_oauth["CLIENT_SECRET"]
    connection = _literal_tables(_source("pyps4_2ndscreen.connection"))
    for name in ("RANDOM_SEED", "PUBLIC_KEY"):
        if connection.get(name):
            needles[f"pyps4-2ndscreen {name}"] = connection[name]
    # The PEM body without line breaks, in case it's stored differently.
    pem = needles.get("pyps4-2ndscreen PUBLIC_KEY", b"")
    body = b"".join(line for line in pem.splitlines() if line and not line.startswith(b"-----"))
    if body:
        needles["pyps4-2ndscreen PUBLIC_KEY (body)"] = body[:64]
    return {label: value for label, value in needles.items() if len(value) >= 8}


# Walking a build ---------------------------------------------------------------------------

def _as_code(data: bytes) -> types.CodeType | None:
    """Unmarshal data if it is a compiled code object; None otherwise."""
    try:
        value = marshal.loads(data)
    except (ValueError, EOFError, TypeError):
        return None
    return value if isinstance(value, types.CodeType) else None

def _code_blobs(code: types.CodeType):
    """Every constant in a code object (recursively) as bytes, incl. tuples of small ints."""
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            yield from _code_blobs(const)
        elif isinstance(const, bytes):
            yield const
        elif isinstance(const, str):
            yield const.encode("utf-8", "surrogatepass")
        elif isinstance(const, (tuple, frozenset)):
            items = list(const)
            if items and all(type(x) is int and 0 <= x <= 255 for x in items):
                yield bytes(items)
            for item in items:
                if isinstance(item, (bytes, str)):
                    yield item if isinstance(item, bytes) else item.encode("utf-8", "surrogatepass")
                elif isinstance(item, types.CodeType):
                    yield from _code_blobs(item)


class Scan:
    def __init__(self, needles: dict[str, bytes]):
        self.needles = needles
        # Low-variety values (e.g. a 16-byte seed made of 2 byte values) occur by chance inside
        # unrelated binaries, so those are only looked for in compiled Python constants.
        self.code_only = {label for label, value in needles.items() if len(set(value)) < 8}
        self.found: dict[str, set[str]] = {}
        self.modules: set[str] = set()
        self.names: list[str] = []
        self.entries = 0

    def _hit(self, label: str, where: str) -> None:
        self.found.setdefault(label, set()).add(where)

    def blob(self, data: bytes, where: str, compiled: bool = False) -> None:
        self.entries += 1
        for label, needle in self.needles.items():
            if label in self.code_only and not compiled:
                continue
            if needle in data:
                self._hit(label, where)
        if data[:4] == b"PK\x03\x04":
            self.zip(data, where)

    def code(self, code: types.CodeType, where: str) -> None:
        joined = b"\0".join(_code_blobs(code))
        self.blob(joined, where, compiled=True)

    def zip(self, data: bytes, where: str) -> None:
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            return
        for info in archive.infolist():
            member = archive.read(info)
            self.names.append(f"{where}!{info.filename}")
            name = info.filename
            code = _as_code(member[16:]) if name.endswith(".pyc") else None
            if code is not None:
                self.code(code, f"{where}!{name}")
            else:
                self.blob(member, f"{where}!{name}")

    def pyinstaller_exe(self, path: Path) -> None:
        from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader  # pylint: disable=import-outside-toplevel
        try:
            car = CArchiveReader(str(path))
        except Exception:  # pylint: disable=broad-except
            return   # not a PyInstaller executable
        for name in car.toc:
            self.names.append(f"{path.name}!{name}")
            data = car.extract(name) or b""
            where = f"{path.name}!{name}"
            if data[:4] == b"PYZ\0":
                tmp = Path(__file__).with_name(".check_keyfree.pyz")
                tmp.write_bytes(data)
                try:
                    pyz = ZlibArchiveReader(str(tmp))
                    for module in pyz.toc:
                        self.modules.add(module)
                        try:
                            code = pyz.extract(module)
                            if not isinstance(code, types.CodeType):
                                raise TypeError
                            self.code(code, f"{where}:{module}")
                        except Exception:  # pylint: disable=broad-except
                            raw = pyz.extract(module, raw=True) or b""
                            try:
                                raw = zlib.decompress(raw)
                            except zlib.error:
                                pass
                            self.blob(raw, f"{where}:{module}")
                finally:
                    tmp.unlink(missing_ok=True)
                continue
            code = _as_code(data)   # entry scripts and runtime hooks are marshalled code
            if code is not None:
                self.code(code, where)
            self.blob(data, where)

    def path(self, target: Path) -> None:
        files = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file())
        for file in files:
            rel = str(file.relative_to(target.parent if target.is_file() else target))
            self.names.append(rel)
            data = file.read_bytes()
            self.blob(data, rel)
            if file.suffix.lower() == ".exe":
                self.pyinstaller_exe(file)
            if file.suffix.lower() == ".pyc":
                code = _as_code(data[16:])
                if code is not None:
                    self.code(code, rel)


def check(target: Path, needles: dict[str, bytes] | None = None) -> tuple[bool, list[str]]:
    scan = Scan(reference_needles() if needles is None else needles)
    scan.path(target)
    lines, clean = [], True
    lines.append(f"Checked {target}: {len(scan.names)} files/entries, {len(scan.modules)} "
                 f"compiled modules, {len(scan.needles)} reference values.")
    for label in scan.needles:
        where = scan.found.get(label)
        if where:
            clean = False
            lines.append(f"  FOUND  {label}: in {', '.join(sorted(where)[:5])}")
        else:
            lines.append(f"  ok     {label}: not present")
    for module in FORBIDDEN_MODULES:
        present = module in scan.modules
        clean &= not present
        lines.append(f"  {'FOUND ' if present else 'ok    '} module {module}: "
                     f"{'bundled' if present else 'not bundled'}")
    pyps4 = sorted(m for m in scan.modules if m.startswith(FORBIDDEN_PREFIXES))
    clean &= not pyps4
    lines.append(f"  {'FOUND ' if pyps4 else 'ok    '} pyps4-2ndscreen modules: "
                 f"{', '.join(pyps4) if pyps4 else 'none bundled'}")
    for module in REQUIRED_MODULES:
        present = module in scan.modules
        clean &= present
        lines.append(f"  {'ok    ' if present else 'MISSING'} module {module}: "
                     f"{'bundled' if present else 'not bundled (is this the key-free build?)'}")
    bad_names = sorted(n for n in scan.names if any(f.lower() in n.lower() for f in FORBIDDEN_NAMES))
    clean &= not bad_names
    lines.append(f"  {'FOUND ' if bad_names else 'ok    '} personal-build files: "
                 f"{', '.join(bad_names[:5]) if bad_names else 'none'}")
    if not scan.modules:
        clean = False
        lines.append("  ERROR  no compiled modules found: is this a PyInstaller build?")
    lines.append("RESULT: " + ("PASS - no Sony key material found" if clean else "FAIL"))
    return clean, lines


def main(argv: list[str]) -> int:
    warnings.filterwarnings("ignore", message="av not installed")
    if len(argv) != 1:
        print(__doc__)
        return 2
    target = Path(argv[0])
    if not target.exists():
        print(f"check_keyfree: {target} doesn't exist")
        return 2
    clean, lines = check(target)
    print("\n".join(lines))
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
