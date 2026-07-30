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

    # This is a pure-Python per-subsample loop that runs on the first launch,
    # before the window is built, so the inner body is kept cheap: the ring
    # test compares squared distances, atan2 is only paid for inside the ring,
    # and the loop-invariant gradient deltas and math lookups are hoisted.
    dark_r, dark_g, dark_b = dark
    dr, dg, db = g1[0] - g0[0], g1[1] - g0[1], g1[2] - g0[2]
    g0r, g0g, g0b = g0
    ring_outer2 = ring_outer * ring_outer
    ring_inner2 = ring_inner * ring_inner
    atan2 = math.atan2
    inside = _inside_rounded_rect
    n = aa * aa
    span = 2 * size

    for y in range(size):
        for x in range(size):
            rr = gg = bb = aa_acc = 0.0
            for sy in range(aa):
                py = y + (sy + 0.5) / aa
                ddy = py - cy
                for sx in range(aa):
                    px = x + (sx + 0.5) / aa
                    if not inside(px, py, size, radius):
                        continue
                    t = (px + (size - py)) / span
                    t = 0.0 if t < 0 else 1.0 if t > 1 else t
                    ddx = px - cx
                    d2 = ddx * ddx + ddy * ddy
                    if (ring_inner2 <= d2 <= ring_outer2
                            and abs(atan2(ddy, ddx)) >= gap_half):
                        cr, cgc, cb = dark_r, dark_g, dark_b
                    else:
                        cr = g0r + dr * t
                        cgc = g0g + dg * t
                        cb = g0b + db * t
                    rr += cr
                    gg += cgc
                    bb += cb
                    aa_acc += 255
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
    """Make sure the window/tray icon exists, and return it.

    assets/icon.png is the real designed icon, checked into the repo —
    `_draw()` only ever ran to produce a stand-in before that existed, and now
    only runs again if the file is somehow missing (a broken checkout, a
    corrupted install), so the app still has something to show rather than
    crashing on a missing asset.
    """
    assets = Path(assets_dir)
    icon = assets / "icon.png"
    if not icon.exists():
        generate_icon(icon, 256)
    return icon


if __name__ == "__main__":
    # Redraws the stand-in — but only where the real, checked-in icon is
    # missing. Never overwrites it; delete the file first to regenerate one.
    here = Path(__file__).resolve().parent.parent / "assets"
    for name, size in (("icon.png", 256), ("tray.png", 32)):
        path = here / name
        if path.exists():
            print("kept", path)
        else:
            print("wrote", generate_icon(path, size))
