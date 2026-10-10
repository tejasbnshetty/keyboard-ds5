## Keyboard DS5 {version}

Control a PS5 from a Windows PC: a TV-style remote for menus and streaming apps, and
keyboard-and-mouse controls for games. Sends controller input only; no video.

> **Unofficial.** Not affiliated with, endorsed by, or supported by Sony Interactive
> Entertainment. "PlayStation", "PS5" and "Remote Play" are trademarks of Sony Interactive
> Entertainment Inc. It uses an unofficial implementation of the Remote Play protocol, which may
> stop working after a PS5 system update and may be against Sony's terms of service. Use it at
> your own risk.

### Download

**{zip}** ({size_mb} MB), Windows 10 or 11 (64-bit).

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
4. Find your PS5, enter your **PSN account ID** (the app explains how to find it; there's no PSN
   sign-in in this build), and pair with the PIN from **Settings → System → Remote Play → Link
   Device** on the PS5.
5. If Windows Firewall asks, allow **Private networks** only.

Settings and pairing are stored in `%APPDATA%\KeyboardDS5`.

### What's inside

- No Sony key tables, no PSN sign-in values. The build was checked by `tools/check_keyfree.py`:

```
{check}
```

- `LICENSE.txt` (AGPL-3.0-only), `PROVENANCE.md` (code origins and Sony-derived material),
  `THIRD-PARTY-NOTICES.txt` (licences of everything bundled).
- Source code: {source_url} (tag `v{version}`).

### Known limits

- PS5 only (PS4 isn't supported yet).
- While connected, the PS5 blacks out video playing in streaming apps; use the remote for their
  menus.
- No automatic updates: check this page for new versions, especially after a PS5 system update.
- Not code-signed, so SmartScreen warns, and some antivirus tools may flag it.
