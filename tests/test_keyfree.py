# SPDX-License-Identifier: AGPL-3.0-only
"""The key-free import finder, run in a fresh Python (this one has already imported pyremoteplay)."""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pyremoteplay.keys as installed

from ps5remote import support

ROOT = Path(__file__).resolve().parent.parent

CHECK = textwrap.dedent("""
    import hashlib, json, sys
    from pathlib import Path
    from ps5remote import keyfree
    keyfree.install(Path(sys.argv[1]))
    import pyremoteplay, pyremoteplay.crypt as crypt, pyremoteplay.register as register
    import pyremoteplay.session as session, pyremoteplay.oauth as oauth, pyremoteplay.device
    import pyps4_2ndscreen.media_art as media_art
    from ps5remote import support, ps5
    sha = lambda b: hashlib.sha256(bytes(b)).hexdigest()
    out = {
        "tables_ok": keyfree.TABLES_OK,
        "ready": support.ready(),
        "hmac_ps5_ok": sha(crypt.HMAC_KEY_PS5) == support.TABLES["HMAC_KEY_PS5"][1],
        "reg_ps5_ok": sha(register.REG_KEY_0_PS5) == support.TABLES["REG_KEY_0_PS5"][1],
        "session_ps5_ok": all(sha(t) == support.TABLES[n][1] for n, t in
                               (("SESSION_KEY_0_PS5", session.SESSION_KEY_0_PS5),
                                ("SESSION_KEY_1_PS5", session.SESSION_KEY_1_PS5))),
        "ps4_empty": len(crypt.HMAC_KEY_PS4) == len(register.REG_KEY_0_PS4)
                     == len(session.SESSION_KEY_1_PS4) == 0,
        "ps5_empty": len(crypt.HMAC_KEY_PS5) == 0,
        "keys_is_stand_in": sys.modules["pyremoteplay.keys"].__spec__.origin == "keyfree stand-in",
        "oauth_is_stand_in": getattr(oauth, "__file__", None) is None,
        "pyps4_is_stand_in": getattr(sys.modules["pyps4_2ndscreen"], "__file__", None) is None,
    }
    try:
        oauth.get_user_account("x")
    except RuntimeError as err:
        out["oauth_message"] = str(err)
    try:
        import pyps4_2ndscreen.connection
        out["pyps4_connection_importable"] = True
    except ImportError:
        out["pyps4_connection_importable"] = False
    try:
        ps5.require_support()
        out["gate"] = "open"
    except ps5.SupportMissing:
        out["gate"] = "closed"
    print(json.dumps(out))
""")


def run(support_dir: Path) -> dict:
    done = subprocess.run([sys.executable, "-c", CHECK, str(support_dir)], cwd=ROOT,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_with_support_files(tmp_path):
    folder = tmp_path / "support"
    support.save(folder, {n: bytes(getattr(installed, n)) for n in support.TABLES}, "test")
    out = run(folder)
    assert out["tables_ok"] and out["ready"] and out["gate"] == "open"
    assert out["hmac_ps5_ok"] and out["reg_ps5_ok"] and out["session_ps5_ok"]
    assert out["ps4_empty"] and not out["ps5_empty"]
    assert out["keys_is_stand_in"] and out["oauth_is_stand_in"] and out["pyps4_is_stand_in"]
    assert "account ID" in out["oauth_message"]
    assert out["pyps4_connection_importable"] is False   # its key and seed never load


def test_without_support_files(tmp_path):
    out = run(tmp_path / "nothing-here")
    assert out["tables_ok"] is False and out["ready"] is False and out["gate"] == "closed"
    assert out["ps5_empty"] and out["ps4_empty"]
    assert out["keys_is_stand_in"]


def test_tampered_support_files_are_not_loaded(tmp_path):
    folder = tmp_path / "support"
    support.save(folder, {n: bytes(getattr(installed, n)) for n in support.TABLES}, "test")
    path = folder / support.TABLES_FILE
    payload = json.loads(path.read_text())
    payload["tables"]["HMAC_KEY_PS5"] = "00" * 16
    path.write_text(json.dumps(payload))
    out = run(folder)
    assert out["tables_ok"] is False and out["gate"] == "closed" and out["ps5_empty"]


def test_install_must_come_first():
    """In this process pyremoteplay is already imported, so install() refuses."""
    import pytest
    from ps5remote import keyfree
    with pytest.raises(RuntimeError, match="must run before"):
        keyfree.install(Path("x"))
    assert keyfree.ACTIVE is False
