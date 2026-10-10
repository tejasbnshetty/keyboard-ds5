# SPDX-License-Identifier: AGPL-3.0-only
"""Fill packaging/RELEASE_NOTES.md for a packaged release.

Usage:  python tools/release_notes.py dist [--repo owner/name]  > notes.md
(dist is the folder tools/package_release.py wrote the zip, .sha256 and check_keyfree.txt to.)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def render(out_dir: Path, repo: str) -> str:
    import ps5remote  # pylint: disable=import-outside-toplevel
    from ps5remote import support  # pylint: disable=import-outside-toplevel
    zip_path = out_dir / f"KeyboardDS5-{ps5remote.__version__}-windows-x64.zip"
    sha_file = zip_path.parent / (zip_path.name + ".sha256")
    check = (out_dir / "check_keyfree.txt").read_text(encoding="utf-8").strip()
    if "RESULT: PASS" not in check:
        raise SystemExit("release_notes: the key-free check didn't pass; not writing notes")
    template = (ROOT / "packaging" / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    return template.format(
        version=ps5remote.__version__, zip=zip_path.name,
        size_mb=f"{zip_path.stat().st_size / 1e6:.1f}",
        sha256=sha_file.read_text(encoding="utf-8").split()[0],
        repo=repo, source_url=ps5remote.SOURCE_URL, check=check,
        pyremoteplay=support.PYREMOTEPLAY_VERSION)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--repo", default="tejasbnshetty/keyboard-ds5")
    args = parser.parse_args(argv)
    sys.stdout.write(render(args.out_dir, args.repo))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
