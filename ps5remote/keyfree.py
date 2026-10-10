# SPDX-License-Identifier: AGPL-3.0-only
"""The key-free public build: stand-ins for the modules left out of it.

The public .exe excludes pyremoteplay.keys, pyremoteplay.oauth and pyps4-2ndscreen (see
ps5remote.spec). install() runs before pyremoteplay is first imported and adds an import finder:

- pyremoteplay.keys: the five PS5 tables from the support files in the data folder (see
  support.py), or empty values if they aren't installed yet. PS4 tables are always empty.
  pyremoteplay reads these names when it's imported, so newly installed support files take
  effect after a restart. Until then the app refuses to connect or pair (support.ready()).
- pyremoteplay.oauth: sign-in isn't part of the public build.
- pyps4_2ndscreen(.media_art): only the PlayStation Store lookup is imported by pyremoteplay,
  and this app switches it off (ps5.Device).

Source installs never call install(); they use the installed packages unchanged.
"""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import sys
from pathlib import Path

ACTIVE = False
TABLES_OK = False
SUPPORT_DIR: Path | None = None

NO_SIGN_IN = ("PSN sign-in isn't part of this build. Enter your account ID in the setup wizard "
              "instead.")


def _fill_keys(module) -> None:
    global TABLES_OK  # pylint: disable=global-statement
    from . import support  # pylint: disable=import-outside-toplevel
    tables = support.load_tables(SUPPORT_DIR) if SUPPORT_DIR else None
    TABLES_OK = tables is not None
    for name in support.TABLES:
        setattr(module, name, tables[name] if tables else b"")
    for name in support.PS4_NAMES:
        setattr(module, name, b"")


def _no_sign_in(*_args, **_kwargs):
    raise RuntimeError(NO_SIGN_IN)


async def _async_no_sign_in(*_args, **_kwargs):
    raise RuntimeError(NO_SIGN_IN)


def _fill_oauth(module) -> None:
    module.get_login_url = _no_sign_in
    module.get_user_account = _no_sign_in
    module.async_get_user_account = _async_no_sign_in
    module.prompt = _no_sign_in


def _fill_pyps4(module) -> None:
    module.__doc__ = "Stand-in: pyps4-2ndscreen isn't part of the public build."


async def _no_store_lookup(*_args, **_kwargs):
    return None


class _ResultItem:
    """Stand-in for pyps4_2ndscreen.media_art.ResultItem (Store lookups are off)."""


def _fill_media_art(module) -> None:
    module.async_search_ps_store = _no_store_lookup
    module.ResultItem = _ResultItem


STAND_INS = {
    "pyremoteplay.keys": _fill_keys,
    "pyremoteplay.oauth": _fill_oauth,
    "pyps4_2ndscreen": _fill_pyps4,
    "pyps4_2ndscreen.media_art": _fill_media_art,
}


class _StandInFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):  # noqa: ARG002
        if fullname not in STAND_INS:
            return None
        return importlib.machinery.ModuleSpec(fullname, self, origin="keyfree stand-in",
                                              is_package=fullname == "pyps4_2ndscreen")

    def create_module(self, spec):  # noqa: ARG002
        return None

    def exec_module(self, module):
        STAND_INS[module.__name__](module)


def install(support_dir: Path) -> None:
    """Call before anything imports pyremoteplay."""
    global ACTIVE, SUPPORT_DIR  # pylint: disable=global-statement
    already = [name for name in STAND_INS if name in sys.modules]
    if already:
        raise RuntimeError(f"keyfree.install() must run before importing {', '.join(already)}")
    SUPPORT_DIR = Path(support_dir)
    ACTIVE = True
    sys.meta_path.insert(0, _StandInFinder())
