# SPDX-License-Identifier: AGPL-3.0-only
import logging

import pytest

from ps5remote.app.main import Redact


def _filtered(msg, *args, extra=()):
    redact = Redact()
    redact.extra.extend(extra)
    record = logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)
    redact.filter(record)
    return record.getMessage()


@pytest.mark.parametrize("text, secret", [
    ("GET /redirect?code=AbC123&cid=1", "AbC123"),
    ("token=s3cr3t", "s3cr3t"),
    ('{"access_token": "eyJabc"}', "eyJabc"),
    ("client_secret='zzz'", "zzz"),
    ("PIN: 12345678", "12345678"),
    ("refresh_token=rt1 other", "rt1"),
    ("authorize?response_type=code&client_id=11111111-2222-3333-4444-555555555555&scope=x",
     "11111111-2222-3333-4444-555555555555"),
    ('{"client_id": "abcdef12-0000"}', "abcdef12-0000"),
])
def test_secrets_are_blanked(text, secret):
    out = _filtered(text)
    assert secret not in out and "<redacted>" in out


def test_args_are_redacted_too():
    out = _filtered("url %s", "http://x/?token=abc")
    assert "abc" not in out


def test_exact_values_are_blanked():
    out = _filtered("ws opened /ws?t=SESSIONTOKEN", extra=["SESSIONTOKEN"])
    assert "SESSIONTOKEN" not in out


def test_ordinary_lines_unchanged():
    assert _filtered("Connected in 0.8s") == "Connected in 0.8s"
