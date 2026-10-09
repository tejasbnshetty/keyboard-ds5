# SPDX-License-Identifier: AGPL-3.0-only
"""Keyboard DS5: control a PS5 from a Windows PC with keyboard and mouse."""
import warnings

# Video decoding (PyAV/FFmpeg) is deliberately not installed; pyremoteplay warns about it on import.
warnings.filterwarnings("ignore", message="av not installed")
