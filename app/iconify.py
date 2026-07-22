from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path


def _inside_rounded_rect(px, py, size, r) -> bool:
    dx = dy = 0.0
    if px < r:
        dx = r - px
    elif px > size - r:
        dx = px - (size - r)
    if py < r:
        dy = r - py
    elif py > size - r:
        dy = py - (size - r)
    if dx == 0 and dy == 0:
        return True
    return dx * dx + dy * dy <= r * r


def _draw(size: int) -> bytearray:
    buf = bytearray(size * size * 4)
    radius = size * 0.22
    cx = cy = size / 2
    g0 = (0xF5, 0xF5, 0xF7)
    g1 = (0x9A, 0x9A, 0xA2)
    dark = (0x0B, 0x0B, 0x0D)
    ring_outer = size * 0.34
    ring_inner = size * 0.205
    gap_half = math.radians(38)
    aa = 2

    for y in range(size):
        for x in range(size):
            rr = gg = bb = aa_acc = 0.0
            for sy in range(aa):
                for sx in range(aa):
                    px = x + (sx + 0.5) / aa
                    py = y + (sy + 0.5) / aa
                    if not _inside_rounded_rect(px, py, size, radius):
                        continue
                    t = (px + (size - py)) / (2 * size)
                    t = 0.0 if t < 0 else 1.0 if t > 1 else t
                    cr = g0[0] + (g1[0] - g0[0]) * t
                    cgc = g0[1] + (g1[1] - g0[1]) * t
                    cb = g0[2] + (g1[2] - g0[2]) * t
                    ddx = px - cx
                    ddy = py - cy
                    dist = math.hypot(ddx, ddy)
                    ang = math.atan2(ddy, ddx)
                    if ring_inner <= dist <= ring_outer and abs(ang) >= gap_half:
                        cr, cgc, cb = dark
                    rr += cr
                    gg += cgc
                    bb += cb
                    aa_acc += 255
            n = aa * aa
            idx = (y * size + x) * 4
            buf[idx] = round(rr / n)
            buf[idx + 1] = round(gg / n)
            buf[idx + 2] = round(bb / n)
            buf[idx + 3] = round(aa_acc / n)
    return buf


def _png(rgba: bytearray, size: int) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    stride = size * 4
    raw = bytearray()
    for y in range(size):
        raw.append(0) 
        raw.extend(rgba[y * stride:(y + 1) * stride])
    idat = zlib.compress(bytes(raw), 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def generate_icon(path: Path | str, size: int = 256) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png(_draw(size), size))
    return path


def ensure_icons(assets_dir: Path | str) -> Path:
    assets = Path(assets_dir)
    icon = assets / "icon.png"
    tray = assets / "tray.png"
    if not icon.exists():
        generate_icon(icon, 256)
    if not tray.exists():
        generate_icon(tray, 32)
    return icon


if __name__ == "__main__":
    here = Path(__file__).resolve().parent.parent / "assets"
    print("wrote", generate_icon(here / "icon.png", 256))
    print("wrote", generate_icon(here / "tray.png", 32))
