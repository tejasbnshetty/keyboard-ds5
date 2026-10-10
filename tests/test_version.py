# SPDX-License-Identifier: AGPL-3.0-only
import re
import sys

import pytest

import ps5remote
from ps5remote import __main__ as cli
from ps5remote.app import main as app_main


def test_version_format():
    assert re.fullmatch(r"\d+\.\d+\.\d+", ps5remote.__version__)
    assert ps5remote.LICENSE_URL.startswith(ps5remote.SOURCE_URL)
    assert ps5remote.PROVENANCE_URL.startswith(ps5remote.SOURCE_URL)


def test_app_version_flag(capsys):
    with pytest.raises(SystemExit) as done:
        app_main.parse_args(["--version"])
    assert done.value.code == 0
    out = capsys.readouterr().out
    assert ps5remote.__version__ in out and ps5remote.SOURCE_URL in out


def test_cli_version_flag(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ps5.bat", "--version"])
    with pytest.raises(SystemExit) as done:
        cli.main()
    assert done.value.code == 0
    out = capsys.readouterr().out
    assert ps5remote.__version__ in out and "AGPL-3.0-only" in out
