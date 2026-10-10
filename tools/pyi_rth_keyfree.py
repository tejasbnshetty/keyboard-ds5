# SPDX-License-Identifier: AGPL-3.0-only
# PyInstaller runtime hook, added to public (key-free) builds only. It runs before run_app.py and
# marks the build, so run_app.py installs ps5remote.keyfree before pyremoteplay is imported.
import sys

sys._keyboardds5_keyfree = True  # pylint: disable=protected-access
