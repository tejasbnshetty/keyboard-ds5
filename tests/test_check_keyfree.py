# SPDX-License-Identifier: AGPL-3.0-only
"""tools/check_keyfree.py, on small synthetic inputs (the real build is checked by build.bat/CI).
Uses made-up needles: no real key material is written anywhere."""
import importlib.util
import marshal
import py_compile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_keyfree", ROOT / "tools" / "check_keyfree.py")
ck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ck)

NEEDLE = bytes(range(40, 72))            # 32 distinct bytes, made up
LOW_VARIETY = bytes([0, 0, 7, 0] * 4)    # 16 bytes, 2 distinct values, made up


def compiled(tmp_path, source: str, name="mod.py") -> Path:
    src = tmp_path / name
    src.write_text(source)
    out = tmp_path / (name + "c")
    py_compile.compile(str(src), cfile=str(out))
    src.unlink()
    return out


def scan(folder, needles):
    s = ck.Scan(needles)
    s.path(folder)
    return s


def test_finds_bytes_list_form_in_compiled_code(tmp_path):
    """The form that escapes a plain byte search: bytes([0x.., ...]) compiles to a tuple of ints."""
    compiled(tmp_path, f"T = bytes({list(NEEDLE)!r})\n")
    assert NEEDLE not in next(tmp_path.glob("*.pyc")).read_bytes()   # not visible as raw bytes
    assert "needle" in scan(tmp_path, {"needle": NEEDLE}).found


def test_finds_bytes_literal_and_strings(tmp_path):
    compiled(tmp_path, f"A = {NEEDLE!r}\nB = 'client-{NEEDLE.hex()}'\n")
    found = scan(tmp_path, {"literal": NEEDLE, "hex": NEEDLE.hex().encode()}).found
    assert set(found) == {"literal", "hex"}


def test_finds_values_in_nested_functions(tmp_path):
    compiled(tmp_path, f"def f():\n    def g():\n        return bytes({list(NEEDLE)!r})\n    return g\n")
    assert "needle" in scan(tmp_path, {"needle": NEEDLE}).found


def test_finds_raw_bytes_in_any_file_and_zip(tmp_path):
    import zipfile
    (tmp_path / "data.bin").write_bytes(b"xx" + NEEDLE + b"yy")
    with zipfile.ZipFile(tmp_path / "lib.zip", "w") as z:
        z.writestr("inner/thing.dat", b"--" + NEEDLE)
    found = scan(tmp_path, {"needle": NEEDLE}).found["needle"]
    assert any("data.bin" in w for w in found) and any("lib.zip!inner/thing.dat" in w for w in found)


def test_low_variety_values_only_count_in_compiled_code(tmp_path):
    (tmp_path / "native.pyd").write_bytes(b"\x01" + LOW_VARIETY + b"\x02")   # chance match
    assert "seed" not in scan(tmp_path, {"seed": LOW_VARIETY}).found
    compiled(tmp_path, f"RANDOM_SEED = {LOW_VARIETY!r}\n")
    assert "seed" in scan(tmp_path, {"seed": LOW_VARIETY}).found


def test_clean_folder_has_no_findings(tmp_path):
    compiled(tmp_path, "X = b'nothing to see'\n")
    (tmp_path / "other.dll").write_bytes(b"MZ" + bytes(100))
    assert scan(tmp_path, {"needle": NEEDLE}).found == {}


def test_report_never_contains_values(tmp_path):
    compiled(tmp_path, f"T = {NEEDLE!r}\n")
    clean, lines = ck.check(tmp_path, {"made-up value": NEEDLE})
    report = "\n".join(lines)
    assert not clean and "FOUND  made-up value" in report
    assert NEEDLE.hex() not in report and repr(NEEDLE) not in report


def test_personal_build_files_fail_the_check(tmp_path):
    (tmp_path / "psn_client.json").write_text("{}")
    (tmp_path / "KeyboardDS5-personal.exe").write_bytes(b"MZ")
    clean, lines = ck.check(tmp_path, {"needle": NEEDLE})
    assert not clean
    assert any("personal-build files" in line and "psn_client.json" in line for line in lines)


def test_not_a_pyinstaller_build_fails(tmp_path):
    (tmp_path / "readme.txt").write_text("hello")
    clean, lines = ck.check(tmp_path, {"needle": NEEDLE})
    assert not clean and any("no compiled modules" in line for line in lines)


def test_reference_values_cover_everything():
    """20 reference values from the installed packages; labels only (values never shown)."""
    needles = ck.reference_needles()
    labels = set(needles)
    for table in ("HMAC_KEY_PS5", "REG_KEY_0_PS5", "REG_KEY_1_PS5", "SESSION_KEY_0_PS5",
                  "SESSION_KEY_1_PS5", "HMAC_KEY_PS4", "REG_KEY_0_PS4", "REG_KEY_1_PS4",
                  "SESSION_KEY_0_PS4", "SESSION_KEY_1_PS4"):
        assert f"key table {table}" in labels
    for label in ("PSN client ID", "PSN client secret", "PSN client secret (base64)",
                  "pyps4-2ndscreen RANDOM_SEED", "pyps4-2ndscreen PUBLIC_KEY"):
        assert label in labels
    assert all(len(v) >= 8 for v in needles.values())


def test_cli_usage_errors(tmp_path, capsys):
    assert ck.main([]) == 2
    assert ck.main([str(tmp_path / "missing")]) == 2
