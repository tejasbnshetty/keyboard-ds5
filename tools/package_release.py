# SPDX-License-Identifier: AGPL-3.0-only
"""Turn the one-folder public build into a release zip.

Usage:  python tools/package_release.py dist\\KeyboardDS5 [--out dist]

1. Adds LICENSE, PROVENANCE.md and packaging/README.txt to the folder.
2. Writes THIRD-PARTY-NOTICES.txt (tools/third_party_notices.py); fails if any licence is missing.
3. Runs the key-free check (tools/check_keyfree.py); fails if anything is found. The report is
   saved as <out>/check_keyfree.txt.
4. Zips the folder as <out>/KeyboardDS5-<version>-windows-x64.zip with sorted entries and fixed
   timestamps, so the same build always gives the same zip, and writes its SHA-256 to a
   .sha256 file.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import check_keyfree  # noqa: E402  pylint: disable=wrong-import-position
import third_party_notices  # noqa: E402  pylint: disable=wrong-import-position

FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def main(argv: list[str]) -> int:
    import ps5remote  # pylint: disable=import-outside-toplevel
    parser = argparse.ArgumentParser(description="Package the public build as a release zip.")
    parser.add_argument("build", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args(argv)
    build: Path = args.build
    if not (build / "KeyboardDS5.exe").is_file() or not (build / "_internal").is_dir():
        print(f"package_release: {build} isn't the one-folder public build")
        return 2

    for source, name in ((ROOT / "LICENSE", "LICENSE.txt"), (ROOT / "PROVENANCE.md", "PROVENANCE.md"),
                         (ROOT / "packaging" / "README.txt", "README.txt")):
        shutil.copyfile(source, build / name)

    notices, problems = third_party_notices.build_notices(build)
    (build / "THIRD-PARTY-NOTICES.txt").write_text(notices, encoding="utf-8")
    if problems:
        print("Third-party notices are incomplete:\n  " + "\n  ".join(problems))
        return 1
    print("Wrote THIRD-PARTY-NOTICES.txt")

    clean, lines = check_keyfree.check(build)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "check_keyfree.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    if not clean:
        return 1

    zip_path = args.out / f"KeyboardDS5-{ps5remote.__version__}-windows-x64.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(p for p in build.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(f"KeyboardDS5/{path.relative_to(build).as_posix()}", FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (zip_path.parent / (zip_path.name + ".sha256")).write_text(f"{digest}  {zip_path.name}\n",
                                                                encoding="utf-8")
    print(f"Wrote {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)\nSHA-256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
