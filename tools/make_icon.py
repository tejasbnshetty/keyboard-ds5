# SPDX-License-Identifier: AGPL-3.0-only
"""Draw the app icon (assets/keyboardds5.ico): four keycaps in an inverted T (the WASD /
arrow-key cluster) on a rounded square. Original artwork; no third-party marks or shapes.

Pure Python (no image libraries): shapes are rasterised with 4x4 supersampling, written as
PNGs and packed into a multi-size .ico.   Usage:  python tools/make_icon.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZES = (16, 24, 32, 48, 64, 128, 256)
SAMPLES = 4

BACKGROUND = (0x3B, 0x5B, 0xDB)     # blue
BACKGROUND_EDGE = (0x2A, 0x43, 0xA8)
KEY = (0xF4, 0xF6, 0xFB)
KEY_SIDE = (0xB9, 0xC2, 0xDA)       # the keycap's lower lip
KEY_HIGHLIGHT = (0x9F, 0xE8, 0xC9)  # the top key (W / up), mint

# Shapes on a 0..1 canvas: (x0, y0, x1, y1, corner radius, colour)
KEY_W, KEY_H, GAP, LIP = 0.215, 0.215, 0.04, 0.035
ROW2_Y = 0.535
ROW1_Y = ROW2_Y - KEY_H - GAP
LEFT = 0.5 - 1.5 * KEY_W - GAP


def _keys():
    shapes = []
    positions = [(0.5 - KEY_W / 2, ROW1_Y, KEY_HIGHLIGHT)] + [
        (LEFT + i * (KEY_W + GAP), ROW2_Y, KEY) for i in range(3)]
    for x, y, top in positions:
        shapes.append((x, y + LIP, x + KEY_W, y + KEY_H + LIP, 0.045, KEY_SIDE))   # lip
        shapes.append((x, y, x + KEY_W, y + KEY_H, 0.045, top))                    # face
    return shapes


SHAPES = [(0.02, 0.03, 0.98, 0.99, 0.22, BACKGROUND_EDGE),     # bottom edge
          (0.02, 0.02, 0.98, 0.96, 0.22, BACKGROUND)] + _keys()


def _inside(px: float, py: float, x0, y0, x1, y1, r) -> bool:
    if not (x0 <= px <= x1 and y0 <= py <= y1):
        return False
    cx = min(max(px, x0 + r), x1 - r)
    cy = min(max(py, y0 + r), y1 - r)
    return (px - cx) ** 2 + (py - cy) ** 2 <= r * r


def render(size: int) -> bytes:
    """RGBA pixels, row by row."""
    out = bytearray()
    n = SAMPLES * SAMPLES
    for y in range(size):
        for x in range(size):
            acc_r = acc_g = acc_b = acc_a = 0.0
            for sy in range(SAMPLES):
                for sx in range(SAMPLES):
                    px = (x + (sx + 0.5) / SAMPLES) / size
                    py = (y + (sy + 0.5) / SAMPLES) / size
                    colour = None
                    for x0, y0, x1, y1, r, c in SHAPES:
                        if _inside(px, py, x0, y0, x1, y1, r):
                            colour = c
                    if colour:
                        acc_r += colour[0]
                        acc_g += colour[1]
                        acc_b += colour[2]
                        acc_a += 1
            if acc_a:
                out += bytes((round(acc_r / acc_a), round(acc_g / acc_a), round(acc_b / acc_a),
                              round(255 * acc_a / n)))
            else:
                out += b"\0\0\0\0"
    return bytes(out)


def png(size: int, rgba: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\0" + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def ico(images: dict[int, bytes]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    entries, data = b"", b""
    offset = 6 + 16 * len(images)
    for size, image in images.items():
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(image), offset + len(data))
        data += image
    return header + entries + data


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    images = {size: png(size, render(size)) for size in SIZES}
    out = root / "assets" / "keyboardds5.ico"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(ico(images))
    (root / "assets" / "keyboardds5-256.png").write_bytes(images[256])
    print(f"Wrote {out} ({', '.join(map(str, SIZES))} px)")


if __name__ == "__main__":
    main()
