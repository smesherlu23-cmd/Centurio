'use strict';
/*
 * Dependency-free PNG icon generator for Centurio.
 * Draws the "C" mark on a light diagonal gradient rounded square,
 * matching the logo in the design mock (linear-gradient(140deg,#f5f5f7,#9a9aa2)).
 *
 * Usage: node scripts/gen-icon.js [size] [outPath]
 * Generates assets/icon.png (256) and assets/tray.png (32) by default.
 */
const zlib = require('zlib');
const fs = require('fs');
const path = require('path');

function lerp(a, b, t) { return a + (b - a) * t; }

// Draw an RGBA buffer (width*height*4) for the icon at a given size.
function draw(size) {
  const buf = Buffer.alloc(size * size * 4, 0); // transparent
  const radius = size * 0.22;          // rounded-square corner radius
  const cx = size / 2, cy = size / 2;

  // Gradient endpoints (#f5f5f7 -> #9a9aa2), 140deg.
  const g0 = [0xf5, 0xf5, 0xf7];
  const g1 = [0x9a, 0x9a, 0xa2];
  const dark = [0x0b, 0x0b, 0x0d];

  // Ring ("C") geometry.
  const ringOuter = size * 0.34;
  const ringInner = size * 0.205;
  // Opening on the right side of the C: hide samples whose angle is within ±38° of 0.
  const gapHalf = (38 * Math.PI) / 180;

  const AA = 2; // supersampling per axis for smooth edges
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let rB = 0, gB = 0, bB = 0, aB = 0;
      for (let sy = 0; sy < AA; sy++) {
        for (let sx = 0; sx < AA; sx++) {
          const px = x + (sx + 0.5) / AA;
          const py = y + (sy + 0.5) / AA;

          // Rounded-rect mask.
          if (!insideRoundedRect(px, py, size, radius)) continue;

          // Base gradient colour (t along the 140deg axis).
          const t = clamp01((px + (size - py)) / (2 * size));
          let cr = lerp(g0[0], g1[0], t);
          let cg = lerp(g0[1], g1[1], t);
          let cb = lerp(g0[2], g1[2], t);

          // "C" ring on top.
          const dx = px - cx, dy = py - cy;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const ang = Math.atan2(dy, dx);
          const inRing = dist >= ringInner && dist <= ringOuter;
          const inGap = Math.abs(ang) < gapHalf;
          if (inRing && !inGap) {
            cr = dark[0]; cg = dark[1]; cb = dark[2];
          }

          rB += cr; gB += cg; bB += cb; aB += 255;
        }
      }
      const n = AA * AA;
      const idx = (y * size + x) * 4;
      buf[idx] = Math.round(rB / n);
      buf[idx + 1] = Math.round(gB / n);
      buf[idx + 2] = Math.round(bB / n);
      buf[idx + 3] = Math.round(aB / n);
    }
  }
  return buf;
}

function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }

function insideRoundedRect(px, py, size, r) {
  const minx = 0, miny = 0, maxx = size, maxy = size;
  // distance to nearest corner region
  let dx = 0, dy = 0;
  if (px < minx + r) dx = minx + r - px; else if (px > maxx - r) dx = px - (maxx - r);
  if (py < miny + r) dy = miny + r - py; else if (py > maxy - r) dy = py - (maxy - r);
  if (dx === 0 && dy === 0) return true;
  return dx * dx + dy * dy <= r * r;
}

// --- Minimal PNG encoder (RGBA, no palette) ---
function crc32(buf) {
  let c = ~0;
  for (let i = 0; i < buf.length; i++) {
    c ^= buf[i];
    for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xEDB88320 & -(c & 1));
  }
  return (~c) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const typeBuf = Buffer.from(type, 'ascii');
  const body = Buffer.concat([typeBuf, data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body), 0);
  return Buffer.concat([len, body, crc]);
}

function encodePNG(rgba, size) {
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8;   // bit depth
  ihdr[9] = 6;   // colour type RGBA
  ihdr[10] = 0;  // compression
  ihdr[11] = 0;  // filter
  ihdr[12] = 0;  // interlace

  // Add filter byte (0) per scanline.
  const stride = size * 4;
  const raw = Buffer.alloc((stride + 1) * size);
  for (let y = 0; y < size; y++) {
    raw[y * (stride + 1)] = 0;
    rgba.copy(raw, y * (stride + 1) + 1, y * stride, y * stride + stride);
  }
  const idat = zlib.deflateSync(raw, { level: 9 });
  return Buffer.concat([
    sig,
    chunk('IHDR', ihdr),
    chunk('IDAT', idat),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

function generate(size, outPath) {
  const rgba = draw(size);
  const png = encodePNG(rgba, size);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, png);
  console.log(`wrote ${outPath} (${size}x${size}, ${png.length} bytes)`);
}

const assetsDir = path.join(__dirname, '..', 'assets');
if (process.argv[2] && process.argv[3]) {
  generate(parseInt(process.argv[2], 10), process.argv[3]);
} else {
  generate(256, path.join(assetsDir, 'icon.png'));
  generate(32, path.join(assetsDir, 'tray.png'));
  generate(16, path.join(assetsDir, 'tray-16.png'));
}
