# SPDX-License-Identifier: AGPL-3.0-only
"""Release tooling: workflow guard rails, notices helpers, release notes, icon."""
import importlib.util
import struct
from pathlib import Path

import pytest
import yaml

import ps5remote

ROOT = Path(__file__).resolve().parent.parent


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The CI workflow can only build the public variant -------------------------------------------

@pytest.fixture(scope="module")
def workflow():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    return text, yaml.safe_load(text)


def test_workflow_pins_the_public_build(workflow):
    text, data = workflow
    job = data["jobs"]["build"]
    assert job["env"]["PS5REMOTE_PERSONAL"] == "0"
    assert 'PS5REMOTE_PERSONAL: "1"' not in text and "PS5REMOTE_PERSONAL=1" not in text
    assert "psn_client.json" not in [s.get("with", {}).get("path") for s in job["steps"]]


def test_workflow_refuses_personal_inputs_and_outputs(workflow):
    _, data = workflow
    names = [s.get("name", "") for s in data["jobs"]["build"]["steps"]]
    assert "Refuse personal-build inputs" in names and "Refuse personal-build outputs" in names
    assert names.index("Refuse personal-build inputs") < names.index("Build (public, key-free, one folder)")


def test_workflow_runs_tests_and_the_keyfree_check_before_releasing(workflow):
    text, data = workflow
    names = [s.get("name", "") for s in data["jobs"]["build"]["steps"]]
    assert names.index("Tests") < names.index("Build (public, key-free, one folder)")
    assert names.index("Package (licences, notices, key-free check, zip)") < names.index(
        "Create draft release (tags only)")
    assert "--draft" in text            # nothing is published without a manual step
    assert "attest-build-provenance" in text


def test_workflow_only_releases_from_tags(workflow):
    _, data = workflow
    on = data.get("on", data.get(True))
    assert set(on) == {"push", "workflow_dispatch"} and on["push"] == {"tags": ["v*"]}
    release = next(s for s in data["jobs"]["build"]["steps"] if s.get("name") == "Create draft release (tags only)")
    assert release["if"] == "startsWith(github.ref, 'refs/tags/')"


def test_tag_release_is_a_draft_pre_release(workflow):
    _, data = workflow
    release = next(s for s in data["jobs"]["build"]["steps"] if s.get("name") == "Create draft release (tags only)")
    assert "--draft" in release["run"] and "--prerelease" in release["run"]
    assert "(pre-release)" in release["run"]


def test_manual_run_uploads_an_artifact_without_releasing(workflow):
    _, data = workflow
    steps = data["jobs"]["build"]["steps"]
    upload = next(s for s in steps if s.get("name") == "Upload artifact (manual runs)")
    assert upload["if"] == "${{ !startsWith(github.ref, 'refs/tags/') }}"
    assert upload["uses"].startswith("actions/upload-artifact@") and upload["with"]["path"] == "release/"
    # the only step that talks to GitHub Releases is tag-only
    assert [s["name"] for s in steps if "gh release" in s.get("run", "")] == ["Create draft release (tags only)"]


def test_build_bat_refuses_while_the_app_is_running():
    text = (ROOT / "build.bat").read_text(encoding="utf-8")
    lines = text.splitlines()
    check = [i for i, line in enumerate(lines) if "tasklist" in line and "goto :running" in line]
    build = next(i for i, line in enumerate(lines) if "pyinstaller.exe" in line and "--noconfirm" in line)
    assert len(check) == 2 and all(i < build for i in check)   # both exe names, before building
    assert ":running" in lines and ":error" in lines
    assert lines.index(":running") < lines.index(":error")
    assert all(line.rstrip().endswith("goto :error") for line in lines if "pyinstaller.exe" in line
               and "||" in line)
    assert (ROOT / "build.bat").read_bytes().count(b"\r\n") == len(lines)   # CRLF throughout


def test_workflow_actions_are_pinned_to_commits(workflow):
    import re
    text, _ = workflow
    uses = re.findall(r"uses:\s*(\S+)", text)
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u) for u in uses), uses


def test_setuptools_is_kept_out_of_the_app():
    spec = (ROOT / "ps5remote.spec").read_text(encoding="utf-8")
    assert '"setuptools", "pkg_resources", "_distutils_hack"' in spec


def test_spec_refuses_personal_builds_in_ci():
    spec = (ROOT / "ps5remote.spec").read_text(encoding="utf-8")
    assert 'personal and (os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))' in spec
    assert '"pyremoteplay.keys", "pyremoteplay.oauth"' in spec and '"pyps4_2ndscreen"' in spec


# Notices and release notes ----------------------------------------------------------------------

def test_licence_file_pattern():
    notices = load_tool("third_party_notices")
    for path in ("pkg-1.0.dist-info/LICENSE", "x.dist-info/licenses/LICENSE.APACHE", "a/COPYING.txt",
                 "b.dist-info/NOTICE"):
        assert notices.LICENSE_FILE.search(path), path
    for path in ("pkg/licensing.py", "pkg/README.md", "pkg/notifications.py"):
        assert not notices.LICENSE_FILE.search(path), path


def test_every_runtime_dependency_has_licence_text():
    """Each installed runtime package has a licence file or a fallback in packaging/licenses."""
    import importlib.metadata as md
    notices = load_tool("third_party_notices")
    for line in (ROOT / "requirements.txt").read_text().splitlines() + \
            (ROOT / "requirements-app.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line or "==" not in line:
            continue
        name = line.split("==")[0]
        if name.lower() in notices.NOT_SHIPPED:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        assert notices.licence_texts(dist), f"{name}: no licence text"


def test_stored_notice_sources_are_present():
    notices = ROOT / "packaging" / "notices"
    sdk = (notices / "webview2-sdk-1.0.3856.49-LICENSE.txt").read_text(encoding="utf-8")
    assert "Copyright (C) Microsoft Corporation" in sdk and "Redistributions in binary form" in sdk
    assert "OpenSSL" in (notices / "cpython-3.11-license.rst").read_text(encoding="utf-8")


def test_release_notes_render(tmp_path):
    notes = load_tool("release_notes")
    version = ps5remote.__version__
    zip_name = f"KeyboardDS5-{version}-windows-x64.zip"
    (tmp_path / zip_name).write_bytes(b"x" * 2_000_000)
    (tmp_path / (zip_name + ".sha256")).write_text(f"{'ab' * 32}  {zip_name}\n")
    (tmp_path / "check_keyfree.txt").write_text("Checked ...\nRESULT: PASS - no Sony key material found\n")
    text = notes.render(tmp_path, "owner/repo")
    assert f"Keyboard DS5 {version}" in text and "ab" * 32 in text
    assert "gh attestation verify" in text and "owner/repo" in text
    assert "RESULT: PASS" in text and "Not affiliated with" in text and "{" not in text.split("```")[0]
    assert "Pre-release" in text and "Terms of Service" in text
    assert "More info → Run\n   anyway" in text and "Private networks" in text
    assert "Sign in with PlayStation" in text and "no PSN sign-in in this build" not in text


def test_release_notes_write_utf8_to_a_cp1252_console(tmp_path, monkeypatch):
    import io
    import sys
    notes = load_tool("release_notes")
    zip_name = f"KeyboardDS5-{ps5remote.__version__}-windows-x64.zip"
    (tmp_path / zip_name).write_bytes(b"x")
    (tmp_path / (zip_name + ".sha256")).write_text(f"{'ab' * 32}  {zip_name}\n")
    (tmp_path / "check_keyfree.txt").write_text("RESULT: PASS\n")
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))
    assert notes.main([str(tmp_path), "--repo", "owner/repo"]) == 0
    sys.stdout.flush()
    assert "More info → Run" in raw.getvalue().decode("utf-8")


def test_release_notes_refuse_a_failed_check(tmp_path):
    notes = load_tool("release_notes")
    zip_name = f"KeyboardDS5-{ps5remote.__version__}-windows-x64.zip"
    (tmp_path / zip_name).write_bytes(b"x")
    (tmp_path / (zip_name + ".sha256")).write_text(f"{'ab' * 32}  {zip_name}\n")
    (tmp_path / "check_keyfree.txt").write_text("RESULT: FAIL\n")
    with pytest.raises(SystemExit):
        notes.render(tmp_path, "owner/repo")


# Icon -------------------------------------------------------------------------------------------

def test_icon_has_all_sizes():
    data = (ROOT / "assets" / "keyboardds5.ico").read_bytes()
    _, kind, count = struct.unpack("<HHH", data[:6])
    sizes = sorted((data[6 + 16 * i] or 256) for i in range(count))
    assert kind == 1 and sizes == [16, 24, 32, 48, 64, 128, 256]
