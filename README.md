# PS5 Phone Remote

A small Python server on a Windows PC that controls a PS5 over Sony's Remote Play
protocol, so an iPhone web page can act as a TV-style remote. No video is decoded.

> **Status:** Phase 2 (command line: discover, sign in, pair, wake, rest mode, button
> presses, keyboard remote). The phone UI comes in later phases.

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

This stays connected, the same way the phone remote will. Keep the PowerShell window focused.

| Key | Button | Key | Button |
|---|---|---|---|
| Arrow keys | D-pad (hold to scroll) | Enter | Cross (select) |
| Backspace or Esc | Circle (back) | T / S | Triangle / Square |
| P | PS button | O | Options |
| Q / E | L1 / R1 | Z / C | L2 / R2 |
| X or Ctrl+C | Quit and disconnect | | |

- The first key press connects, and wakes the PS5 if needed. Each step is printed with a
  timestamp, along with how long connecting took.
- Holding an arrow key presses it once, then repeats after 0.4s at about 6 presses per second.
- If the session drops, you'll see a `!!` line saying so. The next key press reconnects.

### Press timing

Each press holds the button down for **80 ms** before releasing it. To experiment, change it
with `--ms`, for example `.\ps5.bat remote --ms 30` or `.\ps5.bat press cross --ms 200`. If
presses are sometimes ignored, raise it. Repeat speed is set in `ps5remote/remote.py`
(`REPEAT_DELAY`, `REPEAT_INTERVAL`).

### How the code is organised

- `ps5remote/remote.py`: the `Remote` class (connect, auto-wake, tap, hold/repeat,
  dropped-session detection, clean disconnect). The phone server reuses this.
- `ps5remote/keyremote.py`: the keyboard test mode.
- `ps5remote/ps5.py`: discovery, status, pairing, wake.

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
