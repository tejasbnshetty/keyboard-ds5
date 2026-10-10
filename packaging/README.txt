Keyboard DS5
============

Control a PlayStation 5 from this PC: a TV-style remote, and keyboard-and-mouse controls for
games. Unofficial: not affiliated with, endorsed by, or supported by Sony Interactive
Entertainment. "PlayStation" and "PS5" are trademarks of Sony Interactive Entertainment Inc.

Start: run KeyboardDS5.exe from this folder (keep the _internal folder next to it).

First run
---------
1. Windows may say "Windows protected your PC" because the app isn't code-signed. Choose
   More info > Run anyway (only for a copy you downloaded from the project's GitHub page).
2. Setup step "Remote Play support files": the app needs five small key tables from
   pyremoteplay, an open-source library on PyPI. Click "Download from PyPI" (about 151 KB,
   checked against pinned checksums), or "I have the file..." if you already have the
   pyremoteplay 0.7.6 wheel, source archive or keys.py. Then click "Restart to finish".
3. Find your PS5 (it must be on the same network), enter your PSN account ID, and pair using
   the PIN from Settings > System > Remote Play > Link Device on the PS5. How to find your
   account ID is explained in the app and in the project README.
4. If Windows asks about network access, allow Private networks only.

Your settings and pairing are kept in %APPDATA%\KeyboardDS5. Logs: %APPDATA%\KeyboardDS5\logs.

More
----
Source code, full instructions and issues: https://github.com/tejasbnshetty/keyboard-ds5
Licence: AGPL-3.0-only (LICENSE). Code origins and Sony-derived material: PROVENANCE.md.
Third-party licences: THIRD-PARTY-NOTICES.txt.
