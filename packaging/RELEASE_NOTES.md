## Keyboard DS5 {version} (pre-release)

Control a PS5 from a Windows PC: a TV-style remote for menus and streaming apps, and
keyboard-and-mouse controls for games (WASD and mouse aiming, analog triggers, remappable
profiles). Sends controller input only; no video is streamed.

> **Pre-release.** This is the first public build. It has been tested on one PC and one PS5;
> expect rough edges, and please report problems on the Issues page.

> **Unofficial.** Not affiliated with, endorsed by, or supported by Sony Interactive
> Entertainment. "PlayStation", "PS5" and "Remote Play" are trademarks of Sony Interactive
> Entertainment Inc. It uses an unofficial implementation of the Remote Play protocol, which may
> stop working after a PS5 system update. Using it may breach the PlayStation Terms of Service
> (for example their rules on reverse engineering, circumventing authentication and automated
> access), and Sony may restrict or suspend accounts or consoles that breach them. Use it at your
> own risk.

### Requirements

- Windows 10 or 11, 64-bit, with Microsoft Edge WebView2 (built into Windows 11 and current
  Windows 10).
- A PS5 on the same network, with **Settings → System → Remote Play → Enable Remote Play** on.

### Download

**{zip}** ({size_mb} MB)

SHA-256: `{sha256}`

Check it in PowerShell: `(Get-FileHash .\{zip}).Hash.ToLower()`. This file was built by this
repository's GitHub Actions workflow from tag `v{version}`. To verify that with the GitHub CLI:
`gh attestation verify {zip} --repo {repo}`.

### Install and first run

1. Unzip anywhere and run `KeyboardDS5\KeyboardDS5.exe` (keep the `_internal` folder next to it).
2. **"Windows protected your PC"**: the app isn't code-signed yet. Choose **More info → Run
   anyway**, but only for a file you downloaded from this page and whose SHA-256 matches.
3. **Remote Play support files** (first setup step): the app needs five small key tables from
   [pyremoteplay {pyremoteplay}](https://pypi.org/project/pyremoteplay/{pyremoteplay}/), an
   open-source library on PyPI (GPL-3.0). Click **Download from PyPI** (about 151 KB, checked
   against pinned SHA-256 checksums, read as data and never run), or **I have the file…** if you
   already have the wheel, the source archive or its `keys.py`. Then **Restart to finish**.
4. **Optional: Sign in with PlayStation.** Off by default. Tick **Also enable Sign in with
   PlayStation** in that step, or choose **Enable Sign in with PlayStation** later on the Account
   step. The app then also reads the PS Remote Play app's sign-in values from the same
   pyremoteplay package (checked the same way). This uses the PS Remote Play app's sign-in
   identity, as chiaki-ng does. Without it, you type your **PSN account ID**; the app explains
   how to find it.
5. Find your PS5 and pair with the PIN from **Settings → System → Remote Play → Link Device** on
   the PS5.
6. If Windows Firewall asks, allow **Private networks** only (not Public).

Settings and pairing are stored in `%APPDATA%\KeyboardDS5`. The app contacts only your PS5, PyPI
when you click Download, and Sony's sign-in page if you enabled and use sign-in. No telemetry,
no update checks.

### What's inside

- No Sony key tables and no PSN sign-in values. The build was checked by `tools/check_keyfree.py`:

```
{check}
```

- `LICENSE.txt` (AGPL-3.0-only), `PROVENANCE.md` (code origins and Sony-derived material),
  `THIRD-PARTY-NOTICES.txt` (licences of everything bundled), `README.txt` (quick start).
- Source code: {source_url} (tag `v{version}`).

### Known limits

- PS5 only (PS4 isn't supported yet).
- While connected, the PS5 blacks out video playing in streaming apps; use the remote for their
  menus.
- No automatic updates: check this page for new versions, especially after a PS5 system update.
- Not code-signed, so SmartScreen warns, and some antivirus tools may flag it.
