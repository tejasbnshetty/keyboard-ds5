# Code provenance and licences

Where this project's code comes from, and what the licences of its sources mean.
*This is a summary, not legal advice.*

## How pyremoteplay is used

pyremoteplay 0.7.6 is installed **unmodified** from PyPI (`requirements.txt`).
This project **doesn't patch the installed package**, **doesn't vendor a copy**, and **doesn't
monkeypatch** its classes. Fixes are made by **subclassing at runtime** (`ps5remote/rpsession.py`,
`ps5remote/ps5.py`). Some of those subclass methods are modified copies of pyremoteplay methods,
listed below. Controller input is sent by this project's own code (`ps5remote/gamepad.py`)
through pyremoteplay's stream.

## File by file

| File | Origin |
|---|---|
| `ps5remote/__init__.py`, `config.py`, `remote.py`, `watch.py`, `keyremote.py`, `__main__.py` | **Original.** They call pyremoteplay's public API |
| `ps5remote/app/*` (incl. the setup wizard), `ps5remote/settings.py`, `ps5remote/keymaps.py`, `ps5remote/appmaps.py` (Windows app) | **Original** |
| `ps5remote/psn.py` | **Original code.** The redirect URL, scopes and login-URL parameters are Sony's values, taken from chiaki-ng (`gui/include/psnaccountid.h`). The OAuth **client ID/secret are not in the source or the git history**: sign-in is optional (the account ID can be entered by hand), and anyone who wants it supplies their own `psn_client.json` (see the README section "PSN sign-in values"). The account-ID encoding (8-byte little-endian, base64) is the same behaviour as pyremoteplay and chiaki-ng, written independently |
| `ps5remote/ps5.py` | **Original**, except `Device.create_session`, an adapted copy (~10 lines) of pyremoteplay `RPDevice.create_session`. Error-code values are protocol constants also listed in pyremoteplay and chiaki-ng |
| `ps5remote/rpsession.py` | **Mixed** (see below) |
| `ps5remote/gamepad.py` | **Original code.** The button IDs, the two-byte event form (ID + 0x20 while pressed), analog L2/R2 values, newest-first event history, and the 8 ms / 200 ms state intervals are protocol behaviour **looked up** in chiaki-ng (`lib/src/feedback.c`, `feedbacksender.c`). Packets are built with pyremoteplay's `RPStream.send_feedback` and `ControllerState` |
| `ps5remote/gameinput.py` | **Original** |
| `tests/*` | **Original** |
| `app_maps.json`, `psn_client.example.json`, `README.md`, `PROVENANCE.md` | **Original** |
| `setup.bat`, `app.bat`, `ps5.bat`, `build.bat`, `test.bat`, `run_app.py`, `ps5remote.spec`, `pytest.ini`, `requirements*.txt` | **Original** |

### `ps5remote/rpsession.py` in detail

| Part | Origin |
|---|---|
| `FastSession._start_stream` | **Modified copy** of pyremoteplay `Session._start_stream` (near-verbatim, plus skipping the network test and using our stream class) |
| `FastSession._handle_message` | **Rewrite** of pyremoteplay `Session._handle`. Heartbeat handling and session-ID parsing (including its UTF-16 workaround) follow pyremoteplay. Full 16-bit types and decrypting every payload are ours |
| `FastSession._handle` (message framing), `stop`, `start`, `_set_protected` | **Original** |
| `FastSession._display_a` / `_display_b` | **Close port** of chiaki-ng `ctrl.c` `ctrl_message_received_displaya` / `_displayb` (same state machine, about 15 lines of logic) |
| `FastSession._early_session_id` | **Reimplements chiaki-ng behaviour** (`ctrl_message_set_fallback_session_id`: seconds plus 48 random bytes, base64). No code copied |
| `Stream._send_big` (network-test branch) | **Modified copy** of pyremoteplay `RPStream._send_big`. The version value 9 comes from chiaki-ng `senkusha.c` |
| `Stream.send_disconnect` | **Original.** Uses pyremoteplay's `ProtoHandler`; the channel/flag values were checked against chiaki-ng |
| Constants (`CTRL_*` message types, MTU 1454, RTT 1, test version 9) | Protocol values **looked up** in chiaki-ng / pyremoteplay |

**Only looked up in chiaki-ng, not copied:** RP-Version strings, stream protocol version 12, the
launch-spec contents, the RP-Application-Reason codes, the disconnect message format, and the
fact that the PS5 sends its session ID late.

## Sony-derived material

Remote Play is Sony's protocol, so a working client needs some of Sony's values. This section
lists them by **name and purpose only**; no values are reproduced here.

**This repository's own code contains no cryptographic keys and no sign-in credentials.** It
only contains protocol constants (message types, button IDs, timings, URLs and error codes,
listed below). The key tables and sign-in credentials come from **pyremoteplay**, which you
install yourself from PyPI (`setup.bat` does this). They are not copied into this repository.
All of them are also published in chiaki-ng's source.

### Static key material (in pyremoteplay, `pyremoteplay/keys.py`)

| Name | Size | Purpose | Needed? | Also published in chiaki-ng (`lib/src/rpcrypt.c`) |
|---|---|---|---|---|
| `HMAC_KEY_PS5`, `HMAC_KEY_PS4` | 16 bytes each | Derive the cipher for a session's authentication headers and control channel | Yes, for every session | `hmac_key_ps5`, `hmac_key_ps4` |
| `SESSION_KEY_0_PS5`, `SESSION_KEY_0_PS4` | 3,584 bytes each | Derive the session key from the console's nonce and the pairing key | Yes, for every session | `keys_a_ps5`, `keys_a_ps4` |
| `SESSION_KEY_1_PS5`, `SESSION_KEY_1_PS4` | 3,584 bytes each | As above (second table) | Yes, for every session | `keys_b_ps5`, `keys_b_ps4` |
| `REG_KEY_0_PS5`, `REG_KEY_0_PS4` | 512 bytes each | Derive the registration key from the PIN while pairing | Only when pairing | `ps5_keys_0`, `ps4_keys_0` |
| `REG_KEY_1_PS5`, `REG_KEY_1_PS4` | 512 bytes each | As above (second table) | Only when pairing | `ps5_keys_1`, `ps4_keys_1` |

The PS4 tables are present because pyremoteplay supports both consoles; this app only uses the
PS5 ones. The stream's handshake key and elliptic-curve key are generated fresh for each
session, not stored.

### Sign-in credentials

| Name | Where | Purpose | Needed? | Also published in |
|---|---|---|---|---|
| PS Remote Play OAuth client ID and secret | pyremoteplay `oauth.py` (secret base64-encoded); pyps4-2ndscreen `oauth.py` | Sign in to PSN to read the account ID | **No.** The account ID can be entered by hand, and this app never uses pyremoteplay's copy (it reads your own `psn_client.json` instead, if any) | chiaki-ng `gui/include/psnaccountid.h` |

### Other key-like values in dependencies

| Name | Where | Purpose | Needed? |
|---|---|---|---|
| `PUBLIC_KEY` (RSA public key) and `RANDOM_SEED` (16 bytes) | pyps4-2ndscreen `connection.py` | PS4 Second Screen protocol | **No.** Never used by this app (only pyps4-2ndscreen's Store lookup is imported by pyremoteplay, and this app switches that off) |

### Protocol constants (not secret)

| What | Where | Also in |
|---|---|---|
| Remote Play version strings, `RP-*` header names, user agent, ports, discovery messages | pyremoteplay `const.py`, `session.py`, `ddp.py` | chiaki-ng |
| Stream message schema (`takion.proto`, compiled into `takion_pb2.py`) and packet formats | pyremoteplay | chiaki-ng `lib/protobuf/takion.proto` |
| PSN sign-in URLs, scopes and login-URL parameters | **this repo**, `ps5remote/psn.py` | chiaki-ng, pyremoteplay |
| Control-message types, fixed MTU / RTT, network-test version, display-message handling | **this repo**, `ps5remote/rpsession.py` | chiaki-ng |
| Button IDs, event format, analog-trigger values, send intervals | **this repo**, `ps5remote/gamepad.py` | chiaki-ng, pyremoteplay |
| Remote Play error codes | **this repo**, `ps5remote/ps5.py` | chiaki-ng, pyremoteplay |

**In a PyInstaller build:** every .exe bundles pyremoteplay, so it contains all the key tables
and pyremoteplay's copy of the sign-in credentials, plus pyps4-2ndscreen's `PUBLIC_KEY` and
`RANDOM_SEED`. A personal build also contains the builder's own `psn_client.json`.

## Licences

**This project is licensed under AGPL-3.0-only** (see `LICENSE`; every source file carries
`SPDX-License-Identifier: AGPL-3.0-only`), because it includes code ported from chiaki-ng,
which is AGPL-3.0-only.

| Project | Licence | Source |
|---|---|---|
| pyremoteplay | **GPL-3.0** | `LICENSE` (GNU GPL v3); setup.py classifier "GPLv3" |
| chiaki-ng | **AGPL-3.0-only with an OpenSSL linking exception** | `LICENSES/AGPL-3.0-only-OpenSSL.txt`; source files carry SPDX `LicenseRef-AGPL-3.0-only-OpenSSL` |
| pyps4-2ndscreen (dependency) | LGPL-2.0-or-later | package metadata |
| Other dependencies | Permissive: MIT, BSD, Apache-2.0, PSF; MPL-2.0 for certifi | package metadata |
| pywebview / PyInstaller (Windows app build) | BSD-3-Clause / GPL-2.0 with a bootloader exception (doesn't restrict the built .exe) | package metadata |

### (a) If you only use it yourself

**No obligations.** GPL and AGPL only apply when you distribute the software, or (AGPL) let
*other people* use a modified version over a network. Using it yourself, on your own devices and
network, needs nothing.

### (b) If you share or publish the source, or a bundled .exe

This applies to anyone who distributes this project.

- **The project is AGPL-3.0-only** because the display state machine (and arguably the
  fallback-ID logic) is ported from chiaki-ng, which is AGPL-3.0-only. Anyone distributing it, or
  a modified version, must offer the complete source under AGPL-3.0. That includes offering it to
  people who use a modified version over a network (for example, if its web interface is served
  to other people's devices).
- **pyremoteplay (GPL-3.0):** the app imports and subclasses it, and a PyInstaller .exe bundles
  it. GPL-3.0 §13 explicitly allows combining GPL-3.0 code with AGPL-3.0 code, so the combined
  work is distributed under AGPL-3.0 with pyremoteplay keeping its own GPL-3.0 terms.
- **pyps4-2ndscreen (LGPL):** fine, as long as its source is available and it can be replaced.
- **Not a licence issue, but a risk:** the Remote Play protocol, its key tables and the PSN
  client ID/secret are Sony's. Publishing them, or an app containing them, may conflict with
  Sony's terms. This repository doesn't contain them (see
  [Sony-derived material](#sony-derived-material)), but every PyInstaller build bundles
  pyremoteplay, so **distributing any .exe also distributes the key tables and pyremoteplay's
  copy of the client values**. The public build (`build.bat public`) doesn't add the builder's own
  `psn_client.json`; a personal build (`KeyboardDS5-personal.exe`) does, and must never be
  distributed.
- With any .exe release, include `LICENSE`, this file, and the third-party licence notices of the
  bundled dependencies.
