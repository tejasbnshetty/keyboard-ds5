# Keyboard DS5

Control a PlayStation 5 from a Windows PC over the Remote Play protocol: a TV-style remote
for menus and streaming apps, and keyboard-and-mouse controls for games. It sends controller
input only. No video is streamed or decoded, so it's light and connects in about a second.

- **Remote:** every controller button on screen and on your keyboard, plus wake and rest mode.
- **Gaming:** WASD moves the left stick, the mouse aims with the right stick, and mouse
  buttons and the wheel are bindable. Includes analog triggers and a live stick visualiser.
- **Profiles:** fully remappable keys, mouse buttons and wheel, with profiles you switch
  with one key.
- **Easy setup:** a setup wizard finds the console, signs in to PSN and pairs, and a
  command-line tool is included for scripting.
- **Fast connect:** about 1 s instead of the usual 5 s, with automatic wake from rest mode.

> **Disclaimer:** This is an unofficial project. It is not affiliated with, endorsed by, or
> supported by Sony Interactive Entertainment. "PlayStation", "PS5", "PS4" and "Remote Play"
> are trademarks of Sony Interactive Entertainment Inc. It uses an unofficial implementation of
> the Remote Play protocol, which may stop working after a firmware update and may be against
> Sony's terms of service. Use it at your own risk. No PSN sign-in values are included: you
> supply your own (see [PSN sign-in values](#psn-sign-in-values)).

## Compatibility

| | |
|---|---|
| **PC** | Windows 10 or 11, Python 3.11. The app window uses Microsoft Edge WebView2, which is built into Windows 11 and current Windows 10 |
| **PS5** | Supported. Remote Play must be enabled on the console |
| **PS4** | Not supported yet. PS4 Remote Play uses the same protocol, and the underlying library supports it, so support is likely possible. But this app currently only finds and pairs PS5 consoles, and it hasn't been tried on a PS4 |
| **Network** | PC and console on the same local network (not a guest Wi-Fi) |

Only one Remote Play session can be open at a time, so close the official PS Remote Play app
while using this one.

## Quick start

1. **Install Python 3.11** if you don't have it (`py -3.11 --version` to check):

   ```powershell
   winget install -e --id Python.Python.3.11
   ```

   Then open a new PowerShell window.

2. **Install the project.** In the project folder:

   ```powershell
   .\setup.bat
   ```

   This creates a virtual environment in `.venv` and installs pinned dependencies.

3. **Have your PSN account ID ready.** Pairing needs it. Either
   [find your account ID](#finding-your-account-id) and type it into the wizard, or set up
   [PSN sign-in values](#psn-sign-in-values) so the wizard can sign in and read it for you.

4. **Start the app:**

   ```powershell
   .\app.bat
   ```

   On first run, a setup wizard walks you through finding the console, signing in and pairing.

Prefer a standalone program? See [Building the .exe](#building-the-exe).

## Setup wizard

Each step has plain instructions, Back / Next, and a **Retry** button after an error. The
[public .exe](#public-build-key-free) starts with one extra step, **Remote Play support files**
([what and why](#remote-play-support-files-public-build)): download them from PyPI or choose
the file, then **Restart to finish**. Running from source skips it.

1. **Find PS5:** searches your network and lists the consoles it finds. You can also enter
   the IP address (on the PS5: **Settings → Network → Connection Status → View Connection
   Status → IPv4 Address**).
2. **Account:** give the app your PSN account ID, in one of two ways:
   - **Enter my account ID instead:** type the number, or its 12-character encoded form ending
     in `=` ([how to find it](#finding-your-account-id)). An optional name is shown in the app.
     If sign-in values aren't set up, or in the public .exe, this is the only option shown.
   - **Sign in with PlayStation** (needs [sign-in values](#psn-sign-in-values)): opens Sony's
     sign-in page and closes itself when you're done. If that doesn't work, use **Paste the
     address instead**. Copy the address of the page the browser lands on (it may look blank
     or show an error, which is normal) and paste it.

   Only your account ID is kept. Your password never touches the app, and Sony's token is
   discarded.
3. **Pair:** on the PS5, go to **Settings → System → Remote Play**, turn on **Enable Remote
   Play**, choose **Link Device**, and type the 8-digit PIN shown on the TV.
4. **Rest mode (optional):** to wake the console from the app, turn on **Stay Connected to the
   Internet** and **Enable Turning On PS5 from Network** under **Settings → System → Power
   Saving → Features Available in Rest Mode**. Then use **Test rest mode** and **Test wake**.
5. **Done:** press the PS button to try it, then open the remote.

Nothing is saved until pairing succeeds, so a failed PIN or an abandoned wizard leaves an
existing pairing untouched. Later, **Settings → PS5 & account** lets you re-pair (optionally
keeping your PSN account), run the full setup again, or sign out and delete the pairing.

## Using the app

### Remote tab

- **Status bar:** console power (On / Asleep / Not reachable), the running game or app, and
  whether a session is connected.
- **On-screen controller:** every button, including L3, R3 and Touchpad. Hold a direction to
  scroll. A tag under each button shows the key or mouse input that presses it in the
  current profile, and buttons light up while held. Hover a button to see all of its inputs.
- **Wake**, **Rest mode** and **Disconnect.**
- **Keyboard:** works while the window is focused. The first press connects (waking the
  console if needed), and the session disconnects after 2 minutes idle (configurable).
- **Gaming panel:** live view of both sticks, L2/R2 pressure and held buttons, and the mouse
  capture button.

**Streaming apps:** while any Remote Play session is open, the PS5 blacks out video playing in
streaming apps (the video keeps playing; the picture returns about 3 s after disconnecting).
Menus stay visible. So use the remote to navigate streaming apps, and disconnect during
playback. The app shows a warning when a known streaming app is running.

### Gaming: WASD and mouse

Choose the **Gaming** profile and press **F1** (or click **Capture mouse**) to capture the
mouse. A captured mouse moves the right stick in **every** profile, including your own. The
profile only decides what keys and mouse buttons do. The pointer is hidden while captured.
**Esc** or **F1** releases it, and so does switching windows or minimising.

In a gaming profile, buttons stay down for as long as you hold their key.

| Input | Does | Input | Does |
|---|---|---|---|
| W A S D | Left stick (diagonals are normalised) | Mouse | Right stick |
| Left Alt (hold) | Walk: left stick at half tilt | Arrow keys | D-pad |
| Space | Cross | C | Circle |
| E | Square | R | Triangle |
| Left Shift | L3 | V | R3 |
| Q / wheel down | L1 | F / wheel up | R1 |
| Right click | L2 | Left click | R2 |
| Tab | Touchpad | Enter | Options |
| Esc | Release the mouse | F1 | Capture / release the mouse |

Mouse buttons and the wheel act only while the mouse is captured. A **Light L2/R2** action is
available to bind: while its key is held, triggers press only part way.

**Nothing gets stuck:** all buttons are released and both sticks centred whenever the mouse is
released, the window loses focus or closes, the profile changes, or the session drops.

#### Mouse settings and tuning

The right stick follows the mouse's *speed*: moving at 2000 counts per second (at sensitivity
1.0) is full tilt, and the stick re-centres when the mouse stops. Adjust in **Settings →
Gaming**:

| Setting | Default | What it does |
|---|---|---|
| Sensitivity X / Y | 1.0 / 1.0 | Higher turns faster for the same hand movement |
| Response curve | Linear | Exponential gives finer control for small movements |
| Outer limit | 1.0 | The most the stick tilts |
| Anti-deadzone | 0 | The least tilt for any movement, to get past the game's own deadzone |
| Smoothing | 35 ms | Averages movement over this long: steadier, but adds lag |
| Return to centre | 60 ms | How quickly the stick re-centres once the mouse stops |
| Invert Y | Off | Mouse forward looks down |
| Walk tilt | 0.5 | Left-stick tilt while Walk is held |
| Light trigger | 0.4 | L2/R2 pressure while Light L2/R2 is held |
| Stick updates per second | 120 | Up to 125 |
| Mouse capture key | F1 | |

Tips:
- **Turning feels capped:** a stick can only tilt so far, and the game decides how fast
  full tilt turns. Set the **game's own** camera sensitivity high, and turn off any aim
  acceleration or ramp-up. Then use our sensitivity to taste.
- **Small movements do nothing:** raise **Anti-deadzone**. Start at 0.15 and go up in 0.05
  steps until a slight nudge just moves the camera.
- **Use the visualiser.** If the right dot hits the edge on ordinary turns, you're at the
  game's maximum: raise the game's sensitivity and lower ours. If the dot stays near the
  middle and turning is slow, raise ours.
- **Snappier aim:** lower Smoothing (e.g. 25 ms). **Camera drifts after stopping:** lower
  Return to centre (e.g. 40 ms).

### Keys tab and profiles

Every action is listed with the inputs bound to it: buttons, D-pad, left-stick directions,
Walk, Light L2/R2, and right-stick directions for keys. Click **+**, then press a key, click a
mouse button or turn the wheel. An action can have several inputs. Click a binding to remove
it. Changes save straight away.

Each profile has one option, **Gaming profile**: buttons stay down while held. Off, each press
is a tap and held directions repeat, which suits menus. The captured mouse aims with the right
stick in every profile either way.

Built-in profiles: **Menus** (arrows + Enter/Backspace) and **Gaming** (WASD + mouse).

**Your own profiles:** click **New profile**, name it (up to 24 characters), and choose what it
starts with:
- a copy of the current profile;
- the default Menus or Gaming layout;
- nothing bound, in gaming style or menu style.

Then bind its keys. **Rename** and **Delete profile** act on the current profile. **Reset to
defaults** restores the built-in profiles and removes your own. You can have up to 12
profiles. Switch between them with the dropdown or **F2**.

### Settings tab

Press duration, idle disconnect, hold-repeat delay and speed, safe connect, the profile and
mouse-capture hotkeys (which can't be bound in a profile), the gaming settings above, and
**PS5 & account**.

**Remote Play support files** (public .exe only): where the support files came from, plus
**Re-download from PyPI**, **Choose file…**, **Remove support files** and **Restart to apply**.

**About** (top-right corner, or at the bottom of Settings): the version, licence notice,
links to the source code, licence and code origins, and the disclaimer. `--version` works
from the command line too.

## Command-line tool

Everything also works from PowerShell with `.\ps5.bat <command>`:

| Command | Does |
|---|---|
| `discover [--ip ADDRESS]` | Find the console on the network (or use an address) and save it |
| `login` | Sign in to PSN (once). Paste the address the browser lands on |
| `pair [--pin PIN]` | Pair using the PIN from **Link Device** |
| `status` | Show whether the console is awake, asleep or unreachable, and the running app |
| `wake [--no-wait]` / `standby` | Wake from / enter rest mode |
| `press BUTTON [--ms N]` | Connect, press one button, disconnect |
| `remote [--ms N]` | Live keyboard remote in the terminal |
| `app [options]` | Open the app with logs in the terminal (options below) |
| `probe-display [--seconds N]` | Report when the console switches to protected (blanked) video |

Buttons: `up down left right cross circle triangle square options ps l1 r1 l2 r2 l3 r3 touchpad`.
Global options: `-v` for more detail, `--safe-connect` to wait for the console's own session ID
(about 1.5 s slower; only needed if fast connect misbehaves).

**Keyboard remote** (`.\ps5.bat remote`, window focused):

| Key | Button | Key | Button |
|---|---|---|---|
| Arrow keys | D-pad (hold to scroll) | Enter | Cross |
| Backspace or Esc | Circle | T / S | Triangle / Square |
| P | PS button | O | Options |
| Q / E | L1 / R1 | Z / C | L2 / R2 |
| X or Ctrl+C | Quit | | |

Each press holds the button for 80 ms. If presses are sometimes missed, raise it with `--ms`.

**App options** (also accepted by the .exe):

```powershell
.\ps5.bat app --debug        # verbose logs and devtools (right-click > Inspect)
.\ps5.bat app --browser      # use your default browser instead of the app window
.\ps5.bat app --setup        # run the setup wizard (current pairing kept unless the new one works)
.\ps5.bat app --data-dir DIR # use a separate data folder
```

## Finding your account ID

Your PSN account ID is a number (up to 20 digits), not your online ID. The wizard also accepts
the same ID encoded as 12 characters ending in `=`. A wrong ID does no harm: the console just
refuses to pair.

- **Sony's website, in your own browser.** Sign in at playstation.com, press F12 to open the
  developer tools, choose **Network**, and reload the page. Search the requests for
  `basicProfile` (the one ending in `/users/me`). Its response contains `"accountId"`. This
  only reads your own data from Sony's site, but Sony may change the site, so the details can
  move.
- **chiaki-ng.** The open-source [chiaki-ng](https://github.com/streetpea/chiaki-ng) Remote Play
  app can sign in to PSN and shows the encoded form.
- **Third-party lookup websites** can find the ID from an online ID. They aren't run by Sony
  or by this project, so use them at your own discretion.

## PSN sign-in values

Optional, and only when running from source or in a personal build: the public .exe has no PSN
sign-in. Instead of [typing your account ID](#finding-your-account-id), the wizard can sign in
to PSN through Sony's Remote Play sign-in page and read the account ID for you. That page
requires an OAuth client ID and secret. **This project doesn't include them**: they aren't in
its source code or git history, and you add them yourself.

**Where to find them.** Sony doesn't issue these to individuals. They are the official PS
Remote Play app's values, and open-source Remote Play clients include them in their source:
- [pyremoteplay](https://github.com/ktnrg45/pyremoteplay): `pyremoteplay/oauth.py`
  (`__CLIENT_ID` and `__CLIENT_SECRET`). After running `.\setup.bat` you already have this file
  at `.venv\Lib\site-packages\pyremoteplay\oauth.py`. Its secret is **base64-encoded**: use
  the `client_secret_base64` field below.
- [chiaki-ng](https://github.com/streetpea/chiaki-ng): `gui/include/psnaccountid.h`.

Using them is subject to Sony's terms; see the disclaimer at the top.

**Option 1: a `psn_client.json` file (recommended).** Copy `psn_client.example.json` to
`psn_client.json` in your data folder (see [Your data](#your-data)), and fill in:

```json
{
  "client_id": "<client ID>",
  "client_secret": "<client secret>"
}
```

If your secret is base64-encoded (as in pyremoteplay), use `"client_secret_base64":
"<encoded secret>"` instead of `"client_secret"`. The app decodes it.

**Option 2: environment variables**

```powershell
$env:PS5REMOTE_PSN_CLIENT_ID = "<your client ID>"
$env:PS5REMOTE_PSN_CLIENT_SECRET = "<your client secret>"
```

The app checks the environment variables first, then `psn_client.json` in the data folder, then
`data\psn_client.json` in the project folder (when running from source). The .exe only reads its
own data folder, plus the values built into a personal build. Without values, the wizard offers
account-ID entry instead. `psn_client.json` is gitignored. Never commit or share it.

## Building the .exe

You can package the app as a program that runs without Python or a terminal: handy for a
desktop shortcut, or for running it on another PC. **No prebuilt downloads are published yet**,
so build it yourself from the source.

### Public build (key-free)

1. **Do the [Quick start](#quick-start) steps 1 and 2** (Python and `.\setup.bat`). Setup
   installs PyInstaller, which does the packaging.
2. **Build.** In the project folder:

   ```powershell
   .\build.bat public
   ```

   This takes a minute or two and creates:
   - `dist\KeyboardDS5\`: the app as one folder. Run `KeyboardDS5.exe` and keep the
     `_internal` folder next to it. The folder also holds `LICENSE.txt`, `PROVENANCE.md`,
     `README.txt` and `THIRD-PARTY-NOTICES.txt` (the licences of everything bundled).
   - `dist\KeyboardDS5-<version>-windows-x64.zip`, its `.sha256`, and `check_keyfree.txt`.
3. **Run `dist\KeyboardDS5\KeyboardDS5.exe`.** On first run it opens the setup wizard, starting
   with [Remote Play support files](#remote-play-support-files-public-build). If you've already
   paired from source, it finds the project's `data` folder and offers to copy it (the original
   stays). After that you can move the `KeyboardDS5` folder anywhere.

**What "key-free" means.** The public build contains **no Sony key tables and no PSN sign-in
values**. It leaves out pyremoteplay's `keys.py` and `oauth.py` and all of pyps4-2ndscreen, and
gets the five PS5 tables at first run instead. It has no PSN sign-in; you type your account ID.
`build.bat` checks every build with `tools\check_keyfree.py`, which searches every file,
archive member and compiled constant for the key tables, the sign-in values and
pyps4-2ndscreen's key material, comparing them without printing them. The build fails if
anything is found.

### Remote Play support files (public build)

Remote Play needs five small key tables for the PS5 (see PROVENANCE.md,
[Sony-derived material](PROVENANCE.md#sony-derived-material)). Running from source, they come
from the pyremoteplay package that `setup.bat` installs. The public build asks for them in the
first setup step:

- **Download from PyPI.** Only when you click. The app fetches
  [pyremoteplay 0.7.6](https://pypi.org/project/pyremoteplay/0.7.6/) (the wheel, or the source
  archive if that fails) from `files.pythonhosted.org` over HTTPS, and checks it against a pinned
  SHA-256. It reads the five PS5 tables out of `keys.py` **as data, never running it**, checks
  each table against its own pinned SHA-256, and stores them in
  `%APPDATA%\KeyboardDS5\data\support\`.
- **I have the file…** Choose the pyremoteplay 0.7.6 wheel (`.whl`), source archive (`.tar.gz`)
  or its `keys.py`. The same checks apply, and a changed file is rejected. This needs the app
  window; `--browser` mode can only download.
- Then **Restart to finish**: pyremoteplay reads the tables when it starts, so the app relaunches
  itself.

The stored tables are checked again every time the app starts. **Settings → Remote Play support
files** shows where they came from, and can re-download, choose a file, or remove them.

### Personal build

`.\build.bat` without `public` makes `dist\KeyboardDS5-personal.exe` (one file) if
`data\psn_client.json` exists. It contains the full libraries, so it has the key tables and
pyremoteplay's copy of the sign-in values, plus **your** `psn_client.json`. It needs no
support-files step and keeps PSN sign-in. It's for your own PC only: it says "personal build" in
its title bar, and must never be shared or uploaded (`dist\` and `*-personal.exe` are
gitignored). Personal builds are refused in CI. Neither build contains pairing data.

### Release workflow

`.github/workflows/release.yml` builds the public variant only. It:
1. refuses any personal-build input or output;
2. runs the tests;
3. builds, packages and runs the key-free check;
4. attests where the zip came from.

Pushing a tag `vX.Y.Z` that matches the app version creates a **draft** release for review; it
is published only by pressing Publish on GitHub. A manual run builds the zip as a workflow
artifact without creating a release.

### Good to know

- The .exe accepts the same options as `.\ps5.bat app` (e.g. `KeyboardDS5.exe --setup`), and
  writes its logs to `%APPDATA%\KeyboardDS5\logs`.
- It isn't code-signed, so Windows SmartScreen may say "Windows protected your PC" the first
  time. Choose **More info → Run anyway**, but only for a build you made yourself or trust.
- The PC running it needs Microsoft Edge WebView2 (built into Windows 11 and current Windows
  10).
- Rebuild after updating the source. The app doesn't update itself.

## Your data

| Running | Data folder | Logs |
|---|---|---|
| From source (`app.bat`, `ps5.bat`) | `data\` in the project folder | `logs\` in the project folder |
| The .exe | `%APPDATA%\KeyboardDS5\data` | `%APPDATA%\KeyboardDS5\logs` |
| With `--data-dir DIR` | `DIR` | `DIR\logs` |

- `config.json`: the console's address, your PSN online ID and app settings.
- `profiles.json`: your PSN account ID and the pairing keys. **Don't share it**: anyone on your
  network with it could control your console.
- `keymaps.json`: your profiles and bindings.
- `support\remoteplay-tables.json` (public .exe only): the five Remote Play key tables, where
  they came from, and when. Checked against pinned hashes every time the app starts.

To start over, delete the data folder or use **Sign out & forget everything**.

On first run, the .exe looks for older data and **asks before copying it**: first in
`%APPDATA%\PS5Remote\data` (the folder name before the project was renamed), then a `data`
folder next to the .exe, one folder up or two up (the project's own `data` folder when the
.exe is in `dist\KeyboardDS5\`). It copies and never moves, so the old folder stays
until you delete it. If you say no, it won't ask again.

### Privacy and security

- The app's internal web server listens on **127.0.0.1 only**, so other devices can't reach it.
  The interface needs a random per-run token, a matching Origin and a local Host header.
- No password or PSN access token is ever stored. Only the account ID and pairing keys are.
- Logs never contain keys, tokens, sign-in codes or the PIN. Every log line passes through a
  redaction filter.
- The public .exe only goes online for the console on your network, plus PyPI when **you** click
  Download in the support-files step. There's no telemetry and no update check. Running from
  source, signing in to PSN (if set up) also contacts Sony's sign-in servers.

### Firewall

No inbound rule is needed: everything starts from the PC, and Windows allows the replies. If
Windows asks about network access, allow **Private networks** only. If the console search
finds nothing but entering the IP address works, add this narrow rule (PowerShell as
administrator; use the path to `KeyboardDS5.exe`, or to `.venv\Scripts\pythonw.exe` when running
from source):

```powershell
New-NetFirewallRule -DisplayName "Keyboard DS5 - console search replies" -Direction Inbound -Action Allow -Profile Private -Protocol UDP -LocalPort 9303 -RemoteAddress LocalSubnet -Program "C:\path\to\KeyboardDS5.exe"
```

### Keep the console's address fixed

Routers can hand out new addresses after a reboot, which breaks the saved console address. A
**DHCP reservation** fixes it:

1. Find the console's **MAC Address** under **Settings → Network → Connection Status → View
   Connection Status**.
2. Open your router's admin page (usually the "Default Gateway" address from `ipconfig`, such
   as `http://192.168.1.1`).
3. Find "DHCP Reservation" (or "Address Reservation" / "Static Lease"), and add the MAC address
   with its current IP.

If the address does change, run the setup again or `.\ps5.bat discover`.

## Troubleshooting

- **No console found:** it must be on, or in rest mode with "Stay Connected to the Internet"
  on, and on the same network as the PC. Try entering the IP address, and see
  [Firewall](#firewall).
- **"Sony rejected the sign-in code":** the code expires within a minute or two and works
  once. Sign in again and paste the address promptly.
- **Pairing failed:** keep the Link Device screen open. The PIN changes every time it opens.
- **"Remote Play isn't enabled for your account" (0x80108b12):** on the PS5, **Settings →
  System → Remote Play → Enable Remote Play**, plus the switch next to your user if shown.
  No need to pair again.
- **"Another Remote Play app is already connected":** close the PS Remote Play app on other
  devices. After any session ends, the console needs about 9 seconds before it accepts a new
  one, and the app waits and retries automatically.
- **Wake does nothing:** check the two rest-mode settings in the wizard's step 4.
- **A press does nothing:** some screens ignore input briefly. Try a longer press duration
  (Settings, or `--ms 150`).
- **WASD doesn't move the character:** the current profile doesn't bind keys to the left
  stick (Menus doesn't). Choose **Gaming**, or bind them in the Keys tab.
- **The mouse doesn't aim:** capture it first with F1. Mouse movement only counts while the
  green "Mouse captured" bar shows.
- **Mouse won't capture:** click inside the window first, and wait a second after pressing
  Esc before capturing again. As a fallback, try `.\ps5.bat app --browser`.
- **"Couldn't download pyremoteplay from PyPI":** check the internet connection, or download
  `pyremoteplay-0.7.6-py3-none-any.whl` from
  [PyPI](https://pypi.org/project/pyremoteplay/0.7.6/#files) yourself and use **I have the
  file…**.
- **"…checksum doesn't match" / "…doesn't match the expected table":** the file isn't the
  pinned pyremoteplay 0.7.6, or it was changed or damaged. Use the original from PyPI.
- **"Remote Play support files aren't installed yet" / "…aren't loaded":** add them in
  **Settings → Remote Play support files**, then restart the app.
- **"Connected, but the PS5 never finished starting the session":** usually another Remote
  Play app is connected; close it and try again. If it keeps happening after a PS5 system
  update, the update may have changed the Remote Play protocol. Check this project's page for
  a newer version or an open issue.
- **More detail:** run `.\ps5.bat app --debug` (or `.\ps5.bat -v <command>`), and check
  `logs\app.log`.

## How it works

The app is a small local web server (`aiohttp`) shown in a desktop window (`pywebview`).
Buttons, keys, mouse movement and setup steps travel over one WebSocket. The server keeps one
Remote Play session open and sends controller state: buttons as events (with analog L2/R2),
and stick positions at up to 125 updates a second.

It builds on [pyremoteplay](https://github.com/ktnrg45/pyremoteplay) 0.7.6, a pure-Python
Remote Play implementation that installs without a compiler. That project is archived, so this
one adds fixes by subclassing (the installed package is never modified), using
[chiaki-ng](https://github.com/streetpea/chiaki-ng) as the reference for current firmware:

| Area | What this project changes |
|---|---|
| Connect time | Skips a network test that current firmware rejects, and uses a fallback session ID after 0.3 s instead of waiting ~2 s. About 1 s instead of 5.5 s (`--safe-connect` restores the wait) |
| Disconnect | Sends the "client disconnecting" message, which the library never sent, so the console ends the session cleanly |
| Controller | Own sender: analog triggers, correct L3/R3/Touchpad/PS/Options events, rate-limited sticks resent every 200 ms, all sent from one thread |
| Control messages | Full 16-bit message types, and tracking of the console's "protected content" messages |
| Sign-in | Uses the current PSN sign-in link; keys are always saved to the app's data folder, never the library's default location |
| Installation | Uses `netifaces-plus` (prebuilt wheels) in place of `netifaces`, which needs a compiler on Python 3.11 |

Details are in `ps5remote/rpsession.py` and `ps5remote/gamepad.py`.

<details>
<summary>Experimental: Watch mode (disabled)</summary>

Watch mode tried to control video playback without the picture blacking out, by connecting
only for each action (connect, press, disconnect). Because every action is a full reconnect and
the console needs ~9 s between sessions, it proved unreliable, so it's switched off. The code is
kept in `ps5remote/watch.py`. To experiment, add `"features": {"watch_mode": true}` to
`config.json`. **M** then toggles it in `.\ps5.bat remote`.

</details>

## Development

| Path | Contents |
|---|---|
| `ps5remote/remote.py` | `Remote`: connect, auto-wake, retries, taps, hold-to-repeat, held gaming state, drop and idle detection |
| `ps5remote/gamepad.py` | Controller wire format and rate-limited sending |
| `ps5remote/gameinput.py` | Keys to sticks, mouse speed to right stick, modifiers |
| `ps5remote/rpsession.py` | Session fixes on top of pyremoteplay |
| `ps5remote/ps5.py`, `psn.py` | Discovery, status, pairing, wake; PSN sign-in |
| `ps5remote/settings.py`, `keymaps.py`, `config.py` | Settings, input profiles, data folder |
| `ps5remote/support.py`, `keyfree.py` | Remote Play support files (pinned hashes only) and the public build's import stand-ins |
| `ps5remote/app/` | The Windows app: `server.py`, `wizard.py`, `main.py`, and the `web/` interface |
| `ps5remote/__main__.py`, `keyremote.py` | The command-line tool and terminal keyboard remote |
| `ps5remote/watch.py`, `appmaps.py`, `app_maps.json` | Watch mode (disabled) and the streaming-app list |
| `tools/` | Build checks and packaging: `check_keyfree.py`, `third_party_notices.py`, `package_release.py`, `release_notes.py`, `make_icon.py` |
| `packaging/`, `assets/` | Release README and notes template, stored third-party notice texts, the icon |
| `tests/` | Offline test suite: no console or network needed |

Run the tests with `.\test.bat` (any pytest options can follow). To also check the pinned
PyPI download for real, set `KEYBOARDDS5_NETWORK_TESTS=1` first.

## Licence and credits

Licensed under **AGPL-3.0-only** (see [LICENSE](LICENSE)). Built on
[pyremoteplay](https://github.com/ktnrg45/pyremoteplay) (GPL-3.0), with protocol behaviour from
[chiaki-ng](https://github.com/streetpea/chiaki-ng) (AGPL-3.0). See
[PROVENANCE.md](PROVENANCE.md) for where each part of the code comes from and what the licences
mean.
