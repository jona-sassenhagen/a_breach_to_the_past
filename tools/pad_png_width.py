#!/usr/bin/env python3
"""
Pad a PNG's width to a target multiple of N by adding columns on the right.
Preserves height and pixel data; new columns are filled with a chosen color.

Usage:
  python3 tools/pad_png_width.py sprite_assets/skeleton_attack.png --to 480 --color FF77A8

Requires: Pillow (pip install Pillow)
"""

import argparse
from PIL import Image

def pad_png_width(path: str, target: int, color: tuple[int,int,int,int]):
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    if w >= target:
        print(f"{path}: width {w} >= target {target}; no change")
        return
    out = Image.new("RGBA", (target, h), color)
    out.paste(img, (0, 0))
    out.save(path)
    print(f"{path}: padded {w} -> {target}")

def parse_color(s: str) -> tuple[int,int,int,int]:
    s = s.strip().lstrip('#')
    if len(s) == 6:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
        return (r,g,b,255)
    elif len(s) == 8:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
        a = int(s[6:8], 16)
        return (r,g,b,a)
    else:
        raise ValueError("Color must be RRGGBB or RRGGBBAA")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('png', help='Path to PNG to pad')
    ap.add_argument('--to', type=int, default=480, help='Target width (default 480)')
    ap.add_argument('--color', default='FF77A8', help='Pad color hex (default FF77A8)')
    args = ap.parse_args()
    color = parse_color(args.color)
    pad_png_width(args.png, args.to, color)

if __name__ == '__main__':
    main()

