#!/usr/bin/env python3
"""
Repack a horizontal sprite strip into rows that fit within a 256px Pyxel image bank.

Example (skeleton attack):
  python3 tools/repack_strip_to_bank.py \
      sprite_assets/skeleton_attack.png \
      sprite_assets/skeleton_attack_packed.png \
      --frame-w 32 --frame-h 16 --frames 15

Requires: Pillow
"""

import argparse
from PIL import Image

BANK_W = 256

def repack(src_path: str, dst_path: str, frame_w: int, frame_h: int, frames: int):
    src = Image.open(src_path).convert("RGBA")
    sw, sh = src.size
    # Compute rows needed
    per_row = max(1, BANK_W // frame_w)
    rows = (frames + per_row - 1) // per_row
    out_w = BANK_W
    out_h = rows * frame_h
    out = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    for i in range(frames):
        sx = i * frame_w
        if sx >= sw:
            break
        sy = 0
        # Last frame may be partial if source width is short; clamp
        fw = min(frame_w, sw - sx)
        box = (sx, sy, sx + fw, sy + frame_h)
        tile = src.crop(box)
        dx = (i % per_row) * frame_w
        dy = (i // per_row) * frame_h
        out.paste(tile, (dx, dy))
    out.save(dst_path)
    print(f"Wrote {dst_path} size={out_w}x{out_h}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--frame-w', type=int, default=32)
    ap.add_argument('--frame-h', type=int, default=16)
    ap.add_argument('--frames', type=int, default=15)
    args = ap.parse_args()
    repack(args.src, args.dst, args.frame_w, args.frame_h, args.frames)

if __name__ == '__main__':
    main()

