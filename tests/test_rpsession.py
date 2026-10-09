# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import time

import pytest

from ps5remote import rpsession
from ps5remote.rpsession import FastSession


class _PlainCipher:
    """Decrypt is the identity, but counts calls (every payload must be decrypted)."""

    def __init__(self):
        self.calls = 0

    def decrypt(self, data):
        self.calls += 1
        return data


@pytest.fixture
def session():
    s = FastSession("192.168.1.50", {"id": "AQAAAAAAAAA=", "hosts": {}})
    s._cipher = _PlainCipher()
    s._ready_event = asyncio.Event()
    s._hb_last = time.time()
    s.hb_sent = []
    s._send_hb_response = lambda: s.hb_sent.append("response")
    s._send_hb_request = lambda: s.hb_sent.append("request")
    return s


def msg(msg_type: int, payload: bytes = b"") -> bytes:
    return len(payload).to_bytes(4, "big") + msg_type.to_bytes(2, "big") + b"\x00\x00" + payload


def test_split_and_merged_messages_are_framed(session):
    seen = []
    session.on_ctrl_message = lambda t, p: seen.append((t, p))
    data = msg(0x50, b"abc") + msg(0x51) + msg(0x52, b"xy")
    session._handle(data[:5])
    session._handle(data[5:13])
    session._handle(data[13:])
    assert seen == [(0x50, b"abc"), (0x51, b""), (0x52, b"xy")]
    assert session._ctrl_buf == b""


def test_full_16_bit_type_is_read(session):
    session._handle(msg(rpsession.CTRL_HEARTBEAT_REP))  # 0x1FE: low byte alone would be 0xFE
    assert session.hb_sent == []


def test_heartbeat_request_is_answered(session):
    session._handle(msg(rpsession.CTRL_HEARTBEAT_REQ))
    assert session.hb_sent == ["response"]


def test_every_payload_is_decrypted(session):
    session._handle(msg(0x99, b"ignored") + msg(0x98, b"also"))
    assert session._cipher.calls == 2


def test_session_id_first_one_wins(session):
    session._handle(msg(rpsession.CTRL_SESSION_ID, b"\x00\x00FIRST"))
    assert session.session_id == b"FIRST"
    assert session._ready_event.is_set()
    session._handle(msg(rpsession.CTRL_SESSION_ID, b"\x00\x00SECOND"))
    assert session.session_id == b"FIRST"


def test_non_utf8_session_id_is_kept(session):
    session._handle(msg(rpsession.CTRL_SESSION_ID, b"\x00\x00\xff\xfe"))
    assert session.session_id
    session.session_id.decode()  # usable as text


def test_protected_content_state_machine(session):
    changes = []
    session.on_protected_change = changes.append
    assert session.protected_content is None
    session._handle(msg(rpsession.CTRL_DISPLAYA, b"\x01"))      # can't display (A)
    session._handle(msg(rpsession.CTRL_DISPLAYB, b"\x00\x00"))  # confirmed (B)
    assert session.protected_content is True
    session._handle(msg(rpsession.CTRL_DISPLAYB, b"\x01\xff"))  # B clear
    session._handle(msg(rpsession.CTRL_DISPLAYA, b"\x00"))      # A clear
    assert session.protected_content is False
    assert changes == [True, False]


def test_display_b_alone_does_nothing(session):
    session._handle(msg(rpsession.CTRL_DISPLAYB, b"\x00\x00"))
    assert session.protected_content is None


def test_stale_heartbeat_sends_request(session):
    session._hb_last = time.time() - 10
    session._handle(msg(0x77))
    assert session.hb_sent == ["request"]


def test_early_session_id_used_when_ps5_is_slow(session, monkeypatch):
    monkeypatch.setattr(rpsession, "EARLY_SESSION_ID", 0.01)
    session._state = FastSession.State.RUNNING
    asyncio.run(session._early_session_id())
    assert session.session_id and session._ready_event.is_set()


def test_early_session_id_not_used_when_ps5_was_quick(session, monkeypatch):
    monkeypatch.setattr(rpsession, "EARLY_SESSION_ID", 0.01)
    session._state = FastSession.State.RUNNING
    session._session_id = b"FROMPS5"
    asyncio.run(session._early_session_id())
    assert session.session_id == b"FROMPS5"


def test_network_test_is_skipped(session, monkeypatch):
    made = {}

    class FakeStream:
        def __init__(self, sess, stop_event, is_test, cb_stop, mtu, rtt):
            made.update(is_test=is_test, mtu=mtu, rtt=rtt)

        async def async_connect(self):
            pass

        def stop(self):
            pass

    async def go():
        session._loop = asyncio.get_running_loop()
        session._stop_event = asyncio.Event()
        session._session_id = b"ID"
        session._start_stream(test=True)
        await asyncio.sleep(0)

    monkeypatch.setattr(rpsession, "Stream", FakeStream)
    asyncio.run(go())
    assert made == {"is_test": False, "mtu": rpsession.FIXED_MTU, "rtt": rpsession.FIXED_RTT}
