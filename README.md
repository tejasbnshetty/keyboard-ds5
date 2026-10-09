# PS5 Phone Remote

A small Python server on a Windows PC that controls a PS5 over Sony's Remote Play
protocol, so an iPhone web page can act as a TV-style remote. No video is decoded.

> **Status:** Windows app (Phase 3), built on the command-line core from Phases 1–2. Watch mode
> is benched. The iPhone page comes later and will reuse the app's web interface.
> Code origins and licences: [PROVENANCE.md](PROVENANCE.md).

> **Disclaimer:** This is an unofficial, personal project. It is not affiliated with, endorsed
> by, or supported by Sony Interactive Entertainment. "PlayStation", "PS5" and "Remote Play"
> are trademarks of Sony Interactive Entertainment Inc. It uses an unofficial implementation of
> the Remote Play protocol, which may stop working after a firmware update and may be against
> Sony's terms of service. Use it at your own risk. No PSN sign-in values are included: you
> supply your own (see "PSN sign-in values").

## About the library

This uses [pyremoteplay](https://github.com/ktnrg45/pyremoteplay) 0.7.6. The repository is
**archived** (last code change Aug 2022), so it gets no fixes. We use it because:

- Its PS5 protocol details (RP-Version `1.0`, stream protocol version 12, launch spec) match
  [chiaki-ng](https://github.com/streetpea/chiaki-ng), which is actively maintained and works
  with current PS5 firmware.
- It is pure Python and installs on Windows without a compiler.

Known risks and workarounds:

| Problem | Workaround in this project |
|---|---|
| Depends on `netifaces`, which needs Visual Studio to build on Python 3.11 | Uses `netifaces-plus` (prebuilt wheels) and installs with `--no-deps` |
| Its PSN login link stopped working (issue #25) | Our own login (`ps5remote/psn.py`) uses chiaki-ng's current link |
| `Profiles.save()` writes secrets to `~/.pyremoteplay` by default | We always save to `data/` |
| One user reported "Version not accepted" after a 2023 firmware update (issue #22, unanswered) | Not seen here: a full session works on our PS5 |
| Its standby wait loop has an inverted comparison | We wait for the session to close ourselves |
| It looks up the running game on the PlayStation Store after each status check | Turned off (`ps5.Device`) |
| Its network test sends handshake version 7; the PS5 rejects it ("Version not accepted" ×10), then it times out after 3 s | Test skipped; fixed MTU 1454 / RTT 1, chiaki-ng's fallback values (`rpsession.py`) |
| Its "disconnect" message was never sent (stop-flag ordering bug), and was malformed | Fixed; the PS5 now answers "Client Shutdown" |
| It waits ~2 s for the PS5's session ID before starting the stream | Uses a chiaki-ng-style fallback ID after 0.3 s (`--safe-connect` turns this off) |
| It reads only the low byte of control message types and ignores the PS5's "protected content" messages | Full control-message handling (`rpsession.FastSession._handle`) |

All of these patches are in `ps5remote/rpsession.py`, with notes on each.

### Connect time

| Step | Before | Now |
|---|---|---|
| Status check + session request + auth | 0.4 s | 0.4 s |
| Wait for the PS5's session ID | 2.0 s | 0.3 s (fallback ID) |
| Network test (rejected, then timed out) | 3.0 s | skipped |
| Stream handshake | 0.05 s | 0.05 s |
| **Total** | **5.5 s** | **0.6–1.1 s** |

After any session ends, the PS5 takes about **9 seconds** before it accepts a new one. Connects
during that window are refused as "in use", and the remote retries automatically. This happens
on the PS5's side and can't be fixed from here.

## Setup

You need **Python 3.11** (already installed on this PC). Check with:

```powershell
py -3.11 --version
```

If it's missing, run `winget install -e --id Python.Python.3.11` and open a new PowerShell window.

Then, in this folder:

```powershell
.\setup.bat
```

This creates a virtual environment in `.venv` and installs the pinned versions from `requirements.txt`.

## Phase 1: connect to your PS5

Run each command in PowerShell from this folder.

### 1. Find the PS5

```powershell
.\ps5.bat discover
```

This saves the PS5's address. If nothing is found, it lets you type the IP address in.
To find the IP on the PS5, go to **Settings → Network → Connection Status → View Connection Status**
and look for "IPv4 Address". To set it directly:

```powershell
.\ps5.bat discover --ip 192.168.1.50
```

### 2. Sign in to PSN (once)

```powershell
.\ps5.bat login
```

1. A browser opens Sony's sign-in page. Sign in with the account you use on the PS5.
2. You end up on a page whose address starts with
   `https://remoteplay.dl.playstation.net/remoteplay/redirect?code=`. The page may be blank
   or show an error. That's expected.
3. Copy the **whole address** from the address bar (Ctrl+L, then Ctrl+C), paste it into
   PowerShell and press Enter. Do this quickly, because the code expires after a minute or two.

This only reads your numeric account ID. Your password never touches this program, and the
sign-in token is discarded straight away.

### 3. Pair with the PS5

The PS5 must be fully on (not in rest mode).

1. On the PS5, go to **Settings → System → Remote Play** and turn on **Enable Remote Play**.
2. Select **Link Device**. An 8-digit number appears on the TV. Leave that screen open.
3. On the PC, run:

   ```powershell
   .\ps5.bat pair
   ```

   Then type the number.

### 4. Test rest mode and wake

```powershell
.\ps5.bat status
.\ps5.bat standby     # PS5 light turns orange
.\ps5.bat status      # should say asleep
.\ps5.bat wake        # PS5 turns back on
```

For wake to work, enable these on the PS5 under **Settings → System → Power Saving →
Features Available in Rest Mode**:

- **Stay Connected to the Internet**: On
- **Enable Turning On PS5 from Network**: On

## Phase 2: button presses

### One press

```powershell
.\ps5.bat press ps
```

This connects, presses one button and disconnects. If the PS5 is asleep, it wakes it first and
shows progress while it waits. Buttons: `up down left right cross circle triangle square
options ps l1 r1 l2 r2`.

### Keyboard remote

```powershell
.\ps5.bat remote
```

Keep the PowerShell window focused. This is the live remote ("Browse mode"), for the home
screen, games and menus, including menus inside streaming apps. It stays connected and
disconnects after 2 minutes idle.

**Streaming apps:** while a Remote Play session is open, a playing video in a streaming app goes
black on the TV. The video keeps playing, and the picture returns about 3 s after disconnecting.
Menus stay visible. (Tested in the Apple TV app only.) So use the remote for menus there, not
during playback. A playback mode was tried and benched; see
[Benched: Watch mode](#benched-watch-mode).

| Key | Button | Key | Button |
|---|---|---|---|
| Arrow keys | D-pad (hold to scroll) | Enter | Cross (select) |
| Backspace or Esc | Circle (back) | T / S | Triangle / Square |
| P | PS button | O | Options |
| Q / E | L1 / R1 | Z / C | L2 / R2 |
| X or Ctrl+C | Quit and disconnect | | |

- The first key press connects, and wakes the PS5 if needed.
- Holding an arrow key presses it once, then repeats after 0.4 s at about 6 presses per second.
- If the session drops, you'll see a `!!` line. The next key press reconnects.

### Press timing

Each press holds the button down for **80 ms** before releasing it. To experiment, change it
with `--ms`, for example `.\ps5.bat remote --ms 30` or `.\ps5.bat press cross --ms 200`. If
presses are sometimes ignored, raise it. Repeat speed is set in `ps5remote/remote.py`
(`REPEAT_DELAY`, `REPEAT_INTERVAL`).

### Playback signal (diagnostic only)

The PS5 sends a control message when it switches to content it can't stream (protected video)
and back. The remote tracks it as `Remote.protected_content`, but **nothing relies on it**:
modes are switched by hand. It hasn't been seen on a real PS5 yet. To look for it, run
`.\ps5.bat probe-display --seconds 120` during playback.

### How the code is organised

- `ps5remote/remote.py`: the `Remote` class (connect, auto-wake, tap, hold/repeat,
  dropped-session detection, clean disconnect). The phone server reuses this.
- `ps5remote/rpsession.py`: fixes to pyremoteplay's session (faster connect, working
  disconnect, control messages, playback signal).
- `ps5remote/watch.py`: Watch mode, **benched** (bursts, batching, the 9 s countdown, smart play/pause,
  app maps, post-wait test). Reusable by the Windows app.
- `ps5remote/keyremote.py`: keyboard front end only (key mapping and printing).
- `ps5remote/app/`: the Windows app (`server.py` web server, `wizard.py` setup wizard, `main.py` window and launch options, `web/` interface).
- `ps5remote/settings.py`, `ps5remote/keymaps.py`: app settings and keyboard profiles.
- `ps5remote/appmaps.py`: reads `app_maps.json` (streaming-app list, benched Watch-mode maps).
- `app_maps.json`: per-app button maps for Watch mode.
- `ps5remote/ps5.py`: discovery, status, pairing, wake.

## Windows app

A window with the remote, keyboard control, key remapping, profiles and settings. It has its own
setup wizard, so the command-line Phase 1 steps are optional.

```powershell
.\setup.bat        # once, to install the app's extra packages
.\app.bat          # opens the window (no console)
.\ps5.bat app      # same, with live logs in this terminal (see "Launching from the terminal")
```

### First-run setup wizard

If there's no pairing yet, the app opens a five-step wizard instead of the remote. Each step has
plain instructions, a progress bar, and Back / Next. A **Retry** button appears after an error.

1. **Find PS5:** it searches the network automatically and lists the consoles it finds. You can
   also type the IP address instead.
2. **Sign in:** "Sign in with PlayStation" opens Sony's page in an app window, and the window
   closes by itself once you're signed in. If that doesn't work (or you close the window), use
   **Paste the address instead**: copy the address of the page your browser ends on (it may look
   blank, that's normal) and paste it. Only your account ID is kept, never Sony's token.
3. **Pair:** open Settings → System → Remote Play → Link Device on the PS5 and type the 8-digit
   PIN. Errors say what went wrong: the PIN was rejected, the Link Device screen isn't open (or
   the PIN expired), or the PS5 isn't reachable or is in rest mode.
4. **Rest mode settings:** the two Power Saving options that Wake needs, with **Test rest mode**
   and **Test wake** buttons. You can skip this step.
5. **Done:** **Press the PS button** to try it, then **Open the remote**.

**Nothing is saved until pairing succeeds.** A failed PIN, or closing the wizard halfway, leaves
any existing pairing exactly as it was.

**Settings → PS5 & account:**
- **Change PS5 / re-pair:** the wizard without the rest-mode step. You can keep your current
  PSN account.
- **Run setup again:** the full wizard.
- **Sign out & forget everything:** after you confirm, deletes the pairing keys, your account ID
  and the PS5 address. Your settings and key maps are kept.

### Using the app

**Remote tab**
- **Status bar:** PS5 power (On / Asleep / Not reachable), the running app or game, and a
  connected indicator.
- **On-screen buttons:** the controller's buttons. Hold a direction to scroll.
- **Wake** and **Rest mode** (asks for confirmation), plus a **Disconnect** button.
- **Keyboard:** works while the window is focused, using the current profile's keys. It stays
  connected, repeats a held direction, and disconnects when idle (2 minutes by default). When
  the PS5 is still freeing the last session, a blue bar shows "you can connect in N s".
- **Streaming apps:** when the running app is in `app_maps.json`, a yellow note warns that
  connecting will black out its video.

**Keys tab:** click a button, then press a key to bind it. If the key is already used, it offers
to move it. Changes save straight away. You can add and delete profiles, and **Reset to
defaults** restores "Menus" (the command-line keys) and "Games" (WASD + IJKL).

**Profiles:** switch with the dropdown, or with the profile hotkey (**F2** by default).

**Settings tab:** press duration, idle timeout (0 = never), hold-repeat delay and speed, safe
connect, the profile hotkey, and PS5 & account.

### Where data is kept

| Running as | Data (pairing, settings, key maps) | Logs |
|---|---|---|
| Source (`app.bat`, `ps5.bat`) | `data\` in this folder | `logs\` in this folder |
| The .exe | `%APPDATA%\PS5Remote\data` | `%APPDATA%\PS5Remote\logs` |
| `--data-dir DIR` (testing) | `DIR` | `DIR\logs` |

On the .exe's first run with no pairing, it looks for an older `data` folder next to the .exe
and one folder up (so `dist\` inside this project works). If it finds one, it asks before
copying it. It copies; the original stays. If you say no, it won't ask again for that data
folder. To see the first run again, delete `%APPDATA%\PS5Remote`.

### Launching from the terminal (for testing)

```powershell
.\ps5.bat app                          # window + live logs here
.\ps5.bat app --debug                  # verbose logs + devtools (right-click > Inspect)
.\ps5.bat app --browser                # use your default browser instead of the window; Ctrl+C stops
.\ps5.bat app --setup                  # force the wizard; your pairing is kept unless the new one works
.\ps5.bat app --data-dir $env:TEMP\ps5test   # a separate, empty data folder (clean-state testing)
```

The .exe accepts the same options, e.g. `dist\PS5Remote-personal.exe --setup`, but it has no
terminal to show logs in. With `--browser`, sign-in always uses the paste method.

Logs never contain keys, tokens, sign-in codes or the PIN. pyremoteplay is held at INFO level
even with `--debug`, because it logs keys at DEBUG. Every log line also passes through a filter
that blanks `code=`, `token=`, `pin=` and `client_secret` values and this run's session token.

### PSN sign-in values

Signing in to PSN needs an OAuth client ID and secret for Sony's Remote Play sign-in page.
**This project doesn't include them**: they're not in the source code or the git history. If
you build from this repository, you supply your own values. Only use values you're entitled to
use.

**Option 1: a `psn_client.json` file (recommended)**

1. Copy `psn_client.example.json` to a file named `psn_client.json` in your **data folder**:
   - running from source: `data\psn_client.json` in this project folder (create the `data`
     folder if needed)
   - running the .exe: `%APPDATA%\PS5Remote\data\psn_client.json`
2. Open it and replace the placeholders with your client ID and secret:

   ```json
   {
     "client_id": "<your client ID>",
     "client_secret": "<your client secret>"
   }
   ```

   (The `_help` line from the example can stay or go.)
3. Restart the app. In the setup wizard, the "Sign in with PlayStation" button is then enabled.
   Without the file, the wizard says "Sign-in isn't configured".

`psn_client.json` is gitignored everywhere, so it won't be committed by accident. Never commit
or share it.

**Option 2: environment variables** (instead of the file):

```powershell
$env:PS5REMOTE_PSN_CLIENT_ID = "<your client ID>"
$env:PS5REMOTE_PSN_CLIENT_SECRET = "<your client secret>"
.\ps5.bat app
```

These apply to that PowerShell window only. To set them permanently, use **Settings → System →
About → Advanced system settings → Environment Variables**.

The app looks for the values in this order: the environment variables, then `psn_client.json`
in the data folder, then `data\psn_client.json` in this project (so `--data-dir` test runs still
work), and finally inside a personal .exe (see below).

### Building the .exe

```powershell
.\build.bat           # PERSONAL build: dist\PS5Remote-personal.exe, with your sign-in values
.\build.bat public    # dist\PS5Remote.exe, without them (users add their own psn_client.json)
```

The personal build bundles `data\psn_client.json`. It prints a **DO NOT DISTRIBUTE** warning,
and its window title and top bar say "personal build". Never share, upload or commit it (`dist\`
and `*-personal.exe` are gitignored). Neither build contains your pairing data (checked).

### How the app works

`ps5remote/app/server.py` runs a small web server on **127.0.0.1 only**. The window
(`ps5remote/app/main.py`, pywebview with Edge WebView2) shows the page from
`ps5remote/app/web/`. The setup wizard's server side is `ps5remote/app/wizard.py`. Buttons, keys
and setup steps travel over one WebSocket. The same page is meant to be served to the iPhone
later.

## Security

Checked on 2026-10-09:

| Check | Result |
|---|---|
| App server reachable from other devices | **No.** It listens on 127.0.0.1 only (tested from the PC's LAN address) |
| Controlling it without the session token | **Refused.** The WebSocket needs a random per-run token, the right Origin, and a local Host header. 28 server tests + 30 wizard tests |
| Credentials in the interface, logs, code, build or .exe | **None.** The account ID, sign-in code and PIN never reach the interface or the logs (tested). The public .exe contains no Sony values |
| Sony sign-in values in the source or git history | **None.** You supply your own gitignored `psn_client.json` (see "PSN sign-in values") |
| Stored PSN access token | **None.** Only the account ID and pairing keys are stored |
| File permissions on the data and log folders | Only your account, SYSTEM and Administrators (normal) |
| Dependency vulnerabilities (pip-audit) | None (protobuf upgraded to 5.29.6) |
| Static code scan (bandit) | 2 low-severity notes, both harmless: Sony's token URL mistaken for a password, and an intentionally ignored error when closing the sign-in window. The client secret is no longer flagged (it's out of the code) |
| **Windows Firewall** | **Action needed, see below** |

### Firewall

**Does the app need an inbound rule?** No, with one possible exception. Everything the app does
starts from the PC (status checks, waking, pairing, the Remote Play session), and Windows
Firewall automatically lets the replies back in. The window's own server is on 127.0.0.1, which
the firewall doesn't filter.

- **Tested:** a status check worked from a brand-new program with no firewall rule.
- **The possible exception:** the **network search** (step 1 of the wizard). It sends a
  broadcast and the PS5 replies directly. Windows normally allows those replies too, but this
  couldn't be isolated on this PC (see McAfee below). If the search ever finds nothing while
  typing the IP address works, add this one narrow rule (PowerShell as administrator, Private
  networks only, replies from your own network only):

  ```powershell
  New-NetFirewallRule -DisplayName "PS5 Remote - PS5 search replies" -Direction Inbound -Action Allow -Profile Private -Protocol UDP -LocalPort 9303 -RemoteAddress LocalSubnet -Program "$env:USERPROFILE\Downloads\remote-ps5\remote-ps5\dist\PS5Remote-personal.exe"
  ```

**If Windows shows "Windows Security has blocked some features of this app" for PS5Remote:**
tick **Private networks** only, **untick Public networks**, and click **Allow access**. Clicking
**Cancel** is also fine: the app works without it, except possibly the network search.

**McAfee is creating rules automatically.** McAfee is registered as this PC's firewall. During
testing, every new program got a Windows Firewall "Allow" rule for **both Private and Public**
networks within about 3 seconds, without any prompt. That's how the Public rules below appeared.
Consider changing McAfee's firewall setting from automatically allowing programs to asking you.

**Rules to remove** (they allow inbound connections on Public networks): your global
`python.exe` / `pythonw.exe` (which covers *any* Python program), `PS5Remote.exe` in the project
folder, and two test programs from this session (`fwtest_ps5.exe`, `fwprobe2.exe`). Open
**PowerShell as administrator** and run:

```powershell
Get-NetFirewallApplicationFilter | Where-Object { $_.Program -match 'python3?11\\pythonw?\.exe$|remote-ps5\\ps5remote\.exe$|\\fwtest_ps5\.exe$|\\fwprobe2\.exe$' } | Get-NetFirewallRule | Where-Object { $_.Direction -eq 'Inbound' } | Remove-NetFirewallRule
```

Then set your home Wi-Fi to Private: **Settings → Network & internet → Wi-Fi → your home Wi-Fi
network → Network profile type → Private**.

## Benched: Watch mode

**Status: benched (disabled).** The code is kept but switched off. It reappears only when
`data/config.json` contains `"features": {"watch_mode": true}`: then **M** toggles it in
`.\ps5.bat remote`, and `--post-wait-test` works.

### What it was for

Controlling a playing video without the picture going black. Holding a Remote Play session open
blanks streaming-app video on the TV (Apple TV app), so Watch mode never held one: each action
connected, pressed, and disconnected straight away.

### What was built

- **Bursts** (`ps5remote/watch.py`, plus `Remote.open_burst` / `press` / `end_burst` in
  `remote.py`). Each burst prints a timing breakdown.
- **Batching:** a 300 ms collect window before connecting. Presses made during a burst joined it.
- **The PS5's ~9 s reconnect gap:** predicted from when the last session ended
  (`Remote.free_in`), with a "sending in N s" countdown and automatic sending. Pressing
  play/pause again before it was sent cancelled both.
- **Play/pause:** a best-guess PLAYING/PAUSED state on top of the Cross toggle.
- **Smart play:** resuming from paused skipped back 10 or 20 s first. Smart pause had an
  optional skip-back.
- **Seeks:** 10 s with Left/Right, 30 s with Shift+arrows or `[` `]`.
- **Home:** H pressed PS, then returned to Browse mode.
- **Per-app button maps** (`app_maps.json`), picked from the running-app name. Apple TV
  play/pause was confirmed; everything else is unverified.
- **Post-press wait test:** `--post-wait-test` swept the wait from 600 ms down to 0 ms.
- Settings flags (`--smart-play`, `--smart-pause`, `--post-wait`, `--collect`, `--gap`,
  `--app`, `--save-settings`), stored under `"watch"` in `data/config.json`.

Logic tests against a simulated PS5 passed. The real PS5 behaved differently.

### What was tested and what went wrong

Tested on the real PS5 in the Apple TV app. Reported result: **too many disconnections, and
not controlled.** Every action costs a full connect/disconnect cycle, each one blanks the
picture again, and the ~9 s gap means actions pile up behind countdowns. That made it feel
unpredictable during playback.

### Ideas to revisit

- **Fewer cycles:** keep one burst session open for a few seconds after an action, so follow-up
  presses reuse it, and accept a short blackout instead of many.
- **Only play/pause plus a long seek:** fewer, more predictable actions instead of fine seeking.
- **A clearer state machine in the UI:** show "connecting / sending / picture returning /
  locked for N s" so it never feels uncontrolled.
- **Another control path:** HDMI-CEC from the TV, or the streaming app's own phone remote
  (if it has one), wouldn't blank the picture at all.
- **Re-measure the reconnect gap** on newer PS5 firmware. If it shrinks, bursts get much more
  usable.
- **Playback detection:** `Remote.protected_content` (the PS5's "can't display" control message)
  is still tracked but unused. It could drive automatic switching once confirmed on a real PS5.

## Your saved settings and secrets

Everything is stored in `data/`, which is excluded from git (see `.gitignore`):

- `data/config.json`: the PS5 address and your PSN online ID
- `data/profiles.json`: your PSN account ID and the PS5 pairing keys. **Don't share this file.**
  Anyone on your network who has it could control your PS5.

The program never prints these values. To start over, delete the `data` folder.

## Give the PC and PS5 fixed IP addresses

Your router normally hands out addresses (DHCP), and they can change after a reboot. If that
happens, the phone bookmark and saved PS5 address stop working. The fix is a **DHCP
reservation**, which tells the router to always give a device the same address.

1. **Find each device's MAC address.**
   - PC: run `ipconfig /all` in PowerShell. Under your Wi-Fi or Ethernet adapter, note the
     **Physical Address** (e.g. `A4-5E-60-xx-xx-xx`) and **IPv4 Address**.
   - PS5: go to **Settings → Network → Connection Status → View Connection Status** and note
     the **MAC Address** for Wi-Fi or LAN (whichever you use) and the **IPv4 Address**.
2. **Open your router's admin page.** It's usually `http://192.168.1.1` or `http://192.168.0.1`
   (run `ipconfig` and use the "Default Gateway" address). The login is often printed on a
   sticker on the router.
3. **Find the reservation setting.** It's usually called "DHCP Reservation", "Address
   Reservation", "Static Lease" or "LAN → DHCP Server". Add one entry per device: the MAC
   address and the IP it currently has.
4. **Save, then restart** the PC and PS5 (or just wait). Check that the addresses stayed the same.

If your PS5's address changes, run `.\ps5.bat discover` again.

## Troubleshooting

- **"No PS5 found"**: The PS5 must be on or in rest mode with "Stay Connected to the
  Internet" on. The PC must be on the same network (not a guest Wi-Fi). Windows Firewall can
  block replies on networks set to "Public". Use `discover --ip` as a workaround.
- **"Sony rejected the sign-in code"**: The code expired or was already used. Run
  `.\ps5.bat login` again and paste the address faster.
- **"Pairing failed"**: The Link Device screen must still be showing on the PS5, and the PIN
  changes every time that screen opens.
- **"Remote Play isn't enabled for your account" (code 0x80108b12)**: On the PS5, open
  Settings → System → Remote Play and turn on **Enable Remote Play**. If a switch is listed
  next to your user, turn that on too. Then retry. You don't need to pair again.
- **"Remote Play connection failed" / "never finished starting"**: Close any other Remote
  Play app connected to the PS5 (only one session is allowed at a time). Run with `-v` for
  more detail, e.g. `.\ps5.bat -v standby`. Verbose logs never include your keys.
- **Wake does nothing**: Check the rest-mode settings in step 4.
- **"Another Remote Play app is already connected"**: Only one Remote Play session can be open
  at a time. Close the PS Remote Play app on your phone or PC. After a dropped session the PS5
  can hold on to the old one for a while, so the remote keeps retrying for up to 25 seconds.
- **A press does nothing**: Try a longer press, e.g. `--ms 150`. Some screens (such as the
  PS5 home screen while a game is loading) ignore input for a moment.
