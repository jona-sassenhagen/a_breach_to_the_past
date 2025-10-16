#!/usr/bin/env python3
"""
Fix skeleton sprite PNGs for Pyxel colkey transparency by converting background black
to a chroma color (palette 14 pink), while preserving interior black linework.

How it works
- Treat each frame as 32x16 (width x height) tiles across the strip.
- Flood-fill from the frame edges over black-ish pixels to detect "background" black.
- Recolor only the background-connected black to pink (#FF77A8). Interior black remains black.

Usage
  # For 32x16 skeleton strips (per-frame flood)
  python3 tools/fix_skeleton_chroma.py sprite_assets/skeleton_idle.png sprite_assets/skeleton_attack.png

  # For a grid atlas (e.g., decor/treasure) of 16x16 tiles
  python3 tools/fix_skeleton_chroma.py static_assets/decor.png --tile-w 16 --tile-h 16

Requires
  Pillow (PIL): pip install Pillow

Note
- Pair this with setting Skeleton.colkey = 14 in code (already done) so pink is treated as transparent.
"""

import sys
from typing import List, Tuple, Optional

try:
    from PIL import Image
except Exception as e:
    print("This script requires Pillow. Install with: pip install Pillow", file=sys.stderr)
    raise

FRAME_W = 32  # used when images align to 32px frames
FRAME_H = 16

# Pyxel palette index 14 is pink: #FF77A8
CHROMA_RGB = (0xFF, 0x77, 0xA8)

# Consider these as black-ish threshold for background detection
def is_blackish(r: int, g: int, b: int, a: int) -> bool:
    # Allow slightly off blacks and ignore fully transparent pixels (they can stay as-is)
    if a == 0:
        return True
    return r < 16 and g < 16 and b < 16

def flood_recolor_background(frame_pixels, w: int, h: int):
    from collections import deque
    visited = [[False] * w for _ in range(h)]
    q = deque()

    # Seed queue with all edge pixels that are black-ish
    def try_enqueue(x: int, y: int):
        if 0 <= x < w and 0 <= y < h and not visited[y][x]:
            r, g, b, a = frame_pixels[x, y]
            if is_blackish(r, g, b, a):
                visited[y][x] = True
                q.append((x, y))

    for x in range(w):
        try_enqueue(x, 0)
        try_enqueue(x, h - 1)
    for y in range(h):
        try_enqueue(0, y)
        try_enqueue(w - 1, y)

    # BFS and recolor background-connected black-ish pixels to chroma
    while q:
        x, y = q.popleft()
        frame_pixels[x, y] = (*CHROMA_RGB, 255)
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not visited[ny][nx]:
                r, g, b, a = frame_pixels[nx, ny]
                if is_blackish(r, g, b, a):
                    visited[ny][nx] = True
                    q.append((nx, ny))

def process_file(path: str, tile_w: Optional[int] = None, tile_h: Optional[int] = None):
    img = Image.open(path).convert("RGBA")
    W, H = img.size

    px = img.load()

    if tile_w and tile_h:
        # Process as grid of tiles; flood-fill each tile separately from its borders
        tiles_x = max(1, W // tile_w)
        tiles_y = max(1, H // tile_h)
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                x0 = tx * tile_w
                y0 = ty * tile_h
                class TileView:
                    def __getitem__(self, key):
                        x, y = key
                        return px[x0 + x, y0 + y]
                    def __setitem__(self, key, val):
                        x, y = key
                        px[x0 + x, y0 + y] = val
                sub = TileView()
                flood_recolor_background(sub, tile_w, tile_h)
    elif H != FRAME_H:
        print(f"Warning: {path} has height {H}, expected {FRAME_H}. Proceeding anyway.")

    if W % FRAME_W == 0 and H >= FRAME_H:
        # Neat 32px frames: operate per frame
        frames = W // FRAME_W
        for i in range(frames):
            x0 = i * FRAME_W

            def frame_getitem(x, y):
                return px[x0 + x, y]

            def frame_setitem(x, y, val):
                px[x0 + x, y] = val

            class FrameView:
                def __getitem__(self, key):
                    x, y = key
                    return frame_getitem(x, y)

                def __setitem__(self, key, val):
                    x, y = key
                    frame_setitem(x, y, val)

            frame = FrameView()
            flood_recolor_background(frame, FRAME_W, min(FRAME_H, H))
    else:
        # Irregular strip width: flood across the entire image from borders
        class FullView:
            def __getitem__(self, key):
                x, y = key
                return px[x, y]

            def __setitem__(self, key, val):
                x, y = key
                px[x, y] = val

        full = FullView()
        flood_recolor_background(full, W, H)

    # Save in-place (use VCS for backup)
    img.save(path)
    print(f"Updated {path} -> chroma background set to {CHROMA_RGB}")

def main(argv: List[str]):
    if len(argv) < 2:
        print("Usage: python3 tools/fix_skeleton_chroma.py <png> [<png> ...] [--tile-w N --tile-h M]")
        sys.exit(1)
    # Naive option parsing to support grid mode
    args = argv[1:]
    tw = th = None
    if '--tile-w' in args:
        i = args.index('--tile-w')
        tw = int(args[i+1])
        del args[i:i+2]
    if '--tile-h' in args:
        i = args.index('--tile-h')
        th = int(args[i+1])
        del args[i:i+2]
    for p in args:
        process_file(p, tile_w=tw, tile_h=th)

if __name__ == "__main__":
    main(sys.argv)
