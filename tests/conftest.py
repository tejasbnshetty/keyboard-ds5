# SPDX-License-Identifier: AGPL-3.0-only
"""Shared fixtures. No test touches the network, a PS5, or the real data/ folder."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ps5remote import config, rpsession

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch) -> Path:
    """Every test gets its own empty data folder; the real one (with secrets) is never read."""
    for var in ("PS5REMOTE_PSN_CLIENT_ID", "PS5REMOTE_PSN_CLIENT_SECRET", "PS5REMOTE_DATA_DIR"):
        monkeypatch.delenv(var, raising=False)
    for name in ("DATA_DIR", "LOG_DIR", "CONFIG_FILE", "PROFILES_FILE", "CUSTOM_DATA_DIR"):
        monkeypatch.setattr(config, name, getattr(config, name))
    # psn.py also looks for psn_client.json in these two folders.
    monkeypatch.setattr(config, "SOURCE_DATA_DIR", tmp_path / "source-data")
    monkeypatch.setattr(config, "LEGACY_USER_DIR", tmp_path / "legacy-appdata")
    monkeypatch.setattr(config, "RESOURCES", tmp_path / "resources")
    monkeypatch.setattr(rpsession, "EARLY_SESSION_ID", rpsession.EARLY_SESSION_ID)
    path = tmp_path / "data"
    config.set_data_dir(path)
    return path


ACCOUNT_ID = "AQAAAAAAAAA="  # user_id 1, as psn.fetch_account encodes it


@pytest.fixture
def paired(data_dir) -> dict:
    """A saved PS5 address, PSN user and pairing keys."""
    config.update(ps5_host="192.168.1.50", psn_user="tester")
    profiles = {"tester": {"id": ACCOUNT_ID, "hosts": {
        "AABBCCDDEEFF": {"type": "PS5", "data": {"RegistKey": "x", "RP-Key": "y"}}}}}
    config.PROFILES_FILE.write_text(json.dumps(profiles), encoding="utf-8")
    return {"host": "192.168.1.50", "user": "tester"}


@pytest.fixture
def psn_client(data_dir) -> tuple[str, str]:
    """Placeholder sign-in values in the test data folder."""
    data_dir.mkdir(parents=True, exist_ok=True)
    values = ("11111111-2222-3333-4444-555555555555", "test-secret")
    (data_dir / "psn_client.json").write_text(
        json.dumps({"client_id": values[0], "client_secret": values[1]}), encoding="utf-8")
    return values


@pytest.fixture
def fast_sleep(monkeypatch):
    """asyncio.sleep returns at once (still yields to the loop)."""
    real = asyncio.sleep

    async def sleep(_delay=0, result=None):
        return await real(0, result)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    return real
