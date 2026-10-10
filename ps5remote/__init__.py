# SPDX-License-Identifier: AGPL-3.0-only
"""Keyboard DS5: control a PS5 from a Windows PC with keyboard and mouse."""
import warnings

__version__ = "0.1.0"
APP_NAME = "Keyboard DS5"
SOURCE_URL = "https://github.com/tejasbnshetty/keyboard-ds5"
LICENSE_URL = f"{SOURCE_URL}/blob/main/LICENSE"
PROVENANCE_URL = f"{SOURCE_URL}/blob/main/PROVENANCE.md"

# Video decoding (PyAV/FFmpeg) is deliberately not installed; pyremoteplay warns about it on import.
warnings.filterwarnings("ignore", message="av not installed")
