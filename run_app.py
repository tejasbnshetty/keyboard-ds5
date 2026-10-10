# SPDX-License-Identifier: AGPL-3.0-only
"""Entry point for the PyInstaller build (ps5remote.spec). For development use app.bat."""
import argparse
import sys


def _prepare_keyfree() -> None:
    """Public build: serve pyremoteplay's key tables from the support files in the data folder.
    Must run before anything imports pyremoteplay, so the data folder is worked out first."""
    from ps5remote import config, keyfree  # neither imports pyremoteplay

    early = argparse.ArgumentParser(add_help=False)
    early.add_argument("--data-dir")
    known, _ = early.parse_known_args(sys.argv[1:])
    if known.data_dir:
        config.set_data_dir(known.data_dir)
    keyfree.install(config.DATA_DIR / "support")


if __name__ == "__main__":
    if getattr(sys, "_keyboardds5_keyfree", False):   # set by tools/pyi_rth_keyfree.py
        _prepare_keyfree()
    from ps5remote.app.main import main

    main()
