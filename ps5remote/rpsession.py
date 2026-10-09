"""Fixes to pyremoteplay's Remote Play session (the library is archived, so we patch by subclassing).

1. Network test ("Senkusha" in chiaki-ng). Before the real stream, pyremoteplay opens a test
   stream to measure MTU/RTT. Its handshake (BIG payload) sends client_version 7; chiaki-ng's
   Senkusha sends 9 (lib/src/senkusha.c), and current PS5 firmware rejects 7. pyremoteplay
   retransmits for 3 s, times out and falls back to MTU 1454 / RTT 1, the same values chiaki-ng
   falls back to. We skip the test and use those values directly, saving ~3 s per connect.
   NETWORK_TEST = True re-enables it, with the version fixed to 9.

2. Disconnect message. Session.stop() sets the shared stop event *before* calling Stream.stop(),
   which only sends the "Client Disconnecting" message if that event isn't set yet. So it was
   never sent. stop() here sends it first (the PS5 now answers "Client Shutdown"). Note the
   PS5 still takes ~9 s after any session ends before it accepts a new one; that's on its side.

3. Session ID wait. After authenticating, the PS5 takes ~2 s to send its session ID over the
   control connection, and nothing else can start until it arrives. chiaki-ng makes up a
   fallback ID (seconds + 48 random bytes, base64) when the PS5's doesn't come in time, and the
   PS5 accepts it. We use one after EARLY_SESSION_ID seconds, so the stream starts ~1.5 s
   sooner. Set it to None to always wait for the PS5's own ID.

4. Control messages. pyremoteplay reads only the low byte of the 16-bit message type (so it
   answers heartbeat *replies* as if they were requests) and ignores the "display" messages
   the PS5 sends when it switches to content that can't be streamed (protected video, e.g.
   streaming-app playback) and back. _handle() here reads the full type, keeps the
   decryption keystream in step for every message, and tracks that signal in
   `protected_content`, following chiaki-ng's ctrl.c.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time

from pyremoteplay.protobuf import ProtoHandler
from pyremoteplay.session import Session
from pyremoteplay.stream import RPStream

_LOGGER = logging.getLogger(__name__)

NETWORK_TEST = False
FIXED_MTU = 1454  # chiaki-ng's fallback (session.c); also pyremoteplay's default
FIXED_RTT = 1     # goes into the launch spec as "rtt": 1, matching chiaki-ng's 1000 us / 1000
TEST_CLIENT_VERSION = 9  # chiaki-ng senkusha.c: msg.big_payload.client_version = 9
EARLY_SESSION_ID: float | None = 0.3  # seconds after auth; None = wait for the PS5's (~2 s)

# Control-connection message types (chiaki-ng lib/src/ctrl.c)
CTRL_DISPLAYA = 0x01
CTRL_SESSION_ID = 0x33
CTRL_DISPLAYB = 0x16
CTRL_HEARTBEAT_REQ = 0xFE
CTRL_HEARTBEAT_REP = 0x1FE


class Stream(RPStream):
    def _send_big(self):
        if not self._is_test:
            return super()._send_big()
        data = ProtoHandler.big_payload(
            client_version=TEST_CLIENT_VERSION,
            session_key=self._session.session_id,
        )
        self.send_data(data, 1, 1)

    def send_disconnect(self) -> None:
        """Tell the PS5 we're leaving, so it frees the session immediately."""
        if self.state == RPStream.STATE_READY and self._protocol:
            try:
                # pyremoteplay's _disconnect() advances the sequence number twice and sends it
                # as a non-protocol packet, so the PS5 ignores it. Send it the way the working
                # heartbeat acks are sent (chiaki-ng: channel 1, flag 1).
                self.send_data(ProtoHandler.disconnect_payload(), 1, 1, proto=True)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("Couldn't send disconnect", exc_info=True)


class FastSession(Session):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # None = no display message seen yet; True = PS5 showing protected (blanked) content.
        self.protected_content: bool | None = None
        self._cant_display_a = False
        self._cant_display_b = False
        # Called as on_protected_change(bool) from the event loop. Set by remote.Remote.
        self.on_protected_change = None
        # Called as on_ctrl_message(type, payload) for every control message (probe/debugging).
        self.on_ctrl_message = None
        self._ctrl_buf = b""

    async def start(self, wakeup=True, autostart=True) -> bool:
        task = None
        if EARLY_SESSION_ID is not None:
            task = asyncio.get_running_loop().create_task(self._early_session_id())
        try:
            return await super().start(wakeup, autostart)
        finally:
            if task and not task.done():
                task.cancel()

    async def _early_session_id(self) -> None:
        # Wait until authenticated (state RUNNING), then give the PS5 EARLY_SESSION_ID seconds.
        give_up = time.monotonic() + 10
        while self.state != Session.State.RUNNING:
            if self.is_stopped or time.monotonic() > give_up:
                return
            await asyncio.sleep(0.01)
        await asyncio.sleep(EARLY_SESSION_ID)
        if not self.session_id and not self.is_stopped:
            fallback = f"{int(time.monotonic())}{base64.b64encode(os.urandom(48)).decode()}"
            self._session_id = fallback.encode()
            _LOGGER.debug("Using early fallback session ID")
            self._ready_event.set()

    def _handle(self, data: bytes):
        """Replaces Session._handle (see note 4 at the top). TCP may deliver several messages
        at once or split one, so frame them by the 4-byte payload length in each header."""
        self._ctrl_buf += data
        while len(self._ctrl_buf) >= 8:
            size = int.from_bytes(self._ctrl_buf[0:4], "big")
            if len(self._ctrl_buf) < 8 + size:
                return  # wait for the rest
            message, self._ctrl_buf = self._ctrl_buf[:8 + size], self._ctrl_buf[8 + size:]
            self._handle_message(message)

    def _handle_message(self, data: bytes):
        payload = data[8:]
        if payload:
            # Decrypt every payload, even ones we ignore, so the keystream stays in step.
            payload = self._cipher.decrypt(payload)
        msg_type = int.from_bytes(data[4:6], "big")
        if self.on_ctrl_message:
            self.on_ctrl_message(msg_type, payload)

        if msg_type == CTRL_HEARTBEAT_REQ:
            self._hb_last = time.time()
            self._send_hb_response()
        elif msg_type == CTRL_HEARTBEAT_REP:
            self._hb_last = time.time()
        elif msg_type == CTRL_SESSION_ID:
            # Arrives after our early fallback ID too; keep whichever came first.
            if not self.session_id:
                session_id = payload[2:]
                try:
                    session_id.decode()
                except UnicodeDecodeError:
                    session_id = b"".join(chr(c).encode() for c in session_id)
                self._session_id = session_id
                self._ready_event.set()
        elif msg_type == CTRL_DISPLAYA and payload:
            self._display_a(payload)
        elif msg_type == CTRL_DISPLAYB and len(payload) >= 2:
            self._display_b(payload)
        else:
            _LOGGER.debug("Ctrl message type %#x (%d bytes) ignored", msg_type, len(payload))

        if time.time() - self._hb_last > 5:
            self._send_hb_request()

    # Same state machine as chiaki-ng ctrl.c (ctrl_message_received_displaya / _displayb).
    def _display_a(self, payload: bytes) -> None:
        if payload[0] == 0x01:
            self._cant_display_a = True
        elif payload[0] == 0x00 and not self._cant_display_b:
            self._cant_display_a = False
            self._set_protected(False)

    def _display_b(self, payload: bytes) -> None:
        all_clear = payload[0] == 0x01 and payload[1] == 0xFF
        if self._cant_display_a and not all_clear and not self._cant_display_b:
            self._cant_display_b = True
            self._set_protected(True)
        if self._cant_display_b and all_clear:
            self._cant_display_b = False

    def _set_protected(self, value: bool) -> None:
        changed = value != self.protected_content
        self.protected_content = value
        _LOGGER.debug("PS5 display: %s", "protected content (blanked)" if value else "streamable")
        if changed and self.on_protected_change:
            self.on_protected_change(value)

    def _start_stream(self, test=True, mtu=None, rtt=None):
        if test and not NETWORK_TEST:
            test, mtu, rtt = False, FIXED_MTU, FIXED_RTT
        # Same as Session._start_stream, but builds our Stream subclass.
        if not self.session_id:
            _LOGGER.error("Session ID not received")
            return
        stop_event = self._stop_event if not test else asyncio.Event()
        cb_stop = self._cb_stop_test if test else None
        self._stream = Stream(self, stop_event, is_test=test, cb_stop=cb_stop, mtu=mtu, rtt=rtt)
        if not test and self.receiver:
            self._stream.add_receiver(self.receiver)
        self.loop.create_task(self._stream.async_connect())
        if test:
            self.loop.create_task(self._wait_for_test(stop_event))

    def stop(self):
        stream = self._stream
        if isinstance(stream, Stream) and not self.is_stopped:
            stream.send_disconnect()
        super().stop()
