# SPDX-License-Identifier: AGPL-3.0-only
"""Write THIRD-PARTY-NOTICES.txt for a built one-folder release.

Usage:  python tools/third_party_notices.py dist\\KeyboardDS5 [-o dist\\KeyboardDS5\\THIRD-PARTY-NOTICES.txt]

The bundled Python packages are worked out from the build itself (the compiled modules in the
.exe and the files in _internal), mapped to installed distributions, and every licence/notice
file each one ships is included in full. A bundled package with no licence text fails the run
(add one under packaging/licenses/<name>.txt). Non-Python components are added from
packaging/notices/: CPython and the libraries built into it (OpenSSL, libffi, expat, zlib,
...), the Microsoft WebView2 SDK, the Microsoft C/C++ runtime and the PyInstaller bootloader.
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # for ps5remote (version and source URL)
NOTICES = ROOT / "packaging" / "notices"
FALLBACK = ROOT / "packaging" / "licenses"
LICENSE_FILE = re.compile(r"(?i)(^|/)(licen[cs]e|copying|notice)[^/]*$")
NOT_SHIPPED = {"pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes"}
WEBVIEW2_SDK = "1.0.3856.49"
RULE = "=" * 78


def bundled_top_levels(build: Path) -> set[str]:
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader  # pylint: disable=import-outside-toplevel
    tops: set[str] = set()
    for exe in build.glob("*.exe"):
        car = CArchiveReader(str(exe))
        for name in car.toc:
            data = car.extract(name) or b""
            if data[:4] == b"PYZ\0":
                tmp = Path(__file__).with_name(".notices.pyz")
                tmp.write_bytes(data)
                try:
                    tops |= {module.split(".")[0] for module in ZlibArchiveReader(str(tmp)).toc}
                finally:
                    tmp.unlink(missing_ok=True)
    internal = build / "_internal"
    for path in internal.rglob("*"):
        if path.is_file():
            parts = path.relative_to(internal).parts
            tops.add(parts[0].split(".")[0] if len(parts) > 1 else path.name.split(".")[0])
    return tops


def bundled_distributions(build: Path) -> dict[str, md.Distribution]:
    by_module = md.packages_distributions()
    found = {}
    for top in bundled_top_levels(build):
        for name in by_module.get(top, []):
            if name.lower() not in NOT_SHIPPED:
                found[name] = md.distribution(name)
    return dict(sorted(found.items(), key=lambda item: item[0].lower()))


def licence_label(dist: md.Distribution) -> str:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    text = (meta.get("License") or "").strip()
    if text and "\n" not in text and len(text) < 60:
        return text
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or []
                   if c.startswith("License ::")]
    return "; ".join(classifiers) or (text.splitlines()[0] if text else "see licence text below")


def licence_texts(dist: md.Distribution) -> list[tuple[str, str]]:
    texts = []
    for file in dist.files or []:
        if LICENSE_FILE.search(str(file).replace("\\", "/")):
            try:
                raw = Path(file.locate()).read_bytes()
            except OSError:
                continue
            texts.append((str(file), raw.decode("utf-8", errors="replace").strip()))
    fallback = FALLBACK / f"{dist.metadata['Name']}.txt"
    if not texts and fallback.is_file():
        texts.append((f"packaging/licenses/{fallback.name}", fallback.read_text(encoding="utf-8").strip()))
    return texts


def section(title: str, body: str) -> str:
    return f"{RULE}\n{title}\n{RULE}\n\n{body.strip()}\n\n"


def build_notices(build: Path) -> tuple[str, list[str]]:
    import ps5remote  # pylint: disable=import-outside-toplevel
    problems = []
    out = [
        f"Keyboard DS5 {ps5remote.__version__} - third-party notices\n\n"
        f"Keyboard DS5 is licensed under AGPL-3.0-only (see LICENSE). Source code:\n"
        f"{ps5remote.SOURCE_URL}\n\n"
        "This release bundles the software listed below, each under its own licence, reproduced in\n"
        "full. It does not contain Sony's Remote Play key tables or PSN sign-in values: see\n"
        "PROVENANCE.md, \"Sony-derived material\".\n\n"
    ]
    dists = bundled_distributions(build)
    out.append(section("Contents", "\n".join(
        [f"- {name} {dist.version} ({licence_label(dist)})" for name, dist in dists.items()]
        + ["- Python 3.11 runtime and the libraries built into it (OpenSSL, libffi, expat, zlib, ...)",
           f"- Microsoft WebView2 SDK {WEBVIEW2_SDK} (pywebview's WebView2 DLLs)",
           "- Microsoft Visual C++ runtime and Universal C runtime",
           "- PyInstaller bootloader"])))
    for name, dist in dists.items():
        texts = licence_texts(dist)
        if not texts:
            problems.append(f"{name} {dist.version}: no licence text found (add packaging/licenses/{name}.txt)")
            continue
        head = f"{name} {dist.version}\nLicence: {licence_label(dist)}"
        url = dist.metadata.get("Home-page") or next(
            (u.split(",", 1)[1].strip() for u in dist.metadata.get_all("Project-URL") or []), "")
        if url:
            head += f"\nProject: {url}"
        if name == "pyremoteplay":
            head += ("\nBundled without pyremoteplay/keys.py, oauth.py and __main__.py (the key tables are\n"
                     "fetched from PyPI by the user at first run). Unmodified source:\n"
                     "https://pypi.org/project/pyremoteplay/0.7.6/")
        body = "\n\n".join(f"--- {path} ---\n{text}" for path, text in texts)
        out.append(section(head, body))

    python_licence = Path(sys.base_prefix) / "LICENSE.txt"
    if python_licence.is_file():
        out.append(section(f"Python {sys.version.split()[0]} (python311.dll and standard library)",
                           python_licence.read_text(encoding="utf-8", errors="replace")))
    else:
        problems.append(f"Python's LICENSE.txt not found at {python_licence}")
    out.append(section("Software incorporated in Python (OpenSSL, libffi, expat, zlib, libmpdec, ...)\n"
                       "From CPython 3.11 Doc/license.rst",
                       (NOTICES / "cpython-3.11-license.rst").read_text(encoding="utf-8")))
    out.append(section(
        f"Microsoft WebView2 SDK {WEBVIEW2_SDK}\n(Microsoft.Web.WebView2.Core.dll, "
        "Microsoft.Web.WebView2.WinForms.dll, WebView2Loader.dll, via pywebview)",
        "--- LICENSE.txt ---\n"
        + (NOTICES / f"webview2-sdk-{WEBVIEW2_SDK}-LICENSE.txt").read_text(encoding="utf-8")
        + "\n\n--- NOTICE.txt ---\n"
        + (NOTICES / f"webview2-sdk-{WEBVIEW2_SDK}-NOTICE.txt").read_text(encoding="utf-8")))
    out.append(section(
        "Microsoft Visual C++ runtime and Universal C runtime\n"
        "(VCRUNTIME140.dll, ucrtbase.dll, api-ms-win-*.dll)",
        "These runtime files are redistributed with the Python runtime, as permitted by Microsoft's\n"
        "Visual Studio redistribution terms. Copyright (c) Microsoft Corporation."))
    try:
        bootloader = next(text for path, text in licence_texts(md.distribution("pyinstaller")))
        out.append(section("PyInstaller bootloader (GPL-2.0-or-later with the bootloader exception)",
                           bootloader))
    except (md.PackageNotFoundError, StopIteration):
        problems.append("PyInstaller's licence text not found")
    return "".join(out), problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("build", type=Path, help="the one-folder build, e.g. dist\\KeyboardDS5")
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args(argv)
    if not (args.build / "_internal").is_dir():
        print(f"third_party_notices: {args.build} isn't a one-folder build")
        return 2
    text, problems = build_notices(args.build)
    output = args.output or args.build / "THIRD-PARTY-NOTICES.txt"
    output.write_text(text, encoding="utf-8")
    print(f"Wrote {output} ({len(text) // 1024} KB)")
    for problem in problems:
        print(f"  MISSING: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
