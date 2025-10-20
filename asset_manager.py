import os
import tempfile
import struct
import zlib
import binascii
import pyxel
from constants import TILE_SIZE

class AssetManager:
    def __init__(self):
        self.tile_map = {}
        self.anim_map = {}
        self.decor_names = []
        self.treasure_names = []
        self._tileset_chunk_span = {}
        self.load_assets()

    def load_assets(self):
        # Load tilemap assets into dedicated banks
        walls_png = "static_assets/walls.png"
        floors_png = "static_assets/floors.png"
        # Load tall atlases with horizontal chunking to stay within Pyxel's 256px height limit
        self._load_tileset(walls_png, img_bank=1)
        self._load_tileset(floors_png, img_bank=2)
        self.parse_tile_mapping("static_assets/walls.txt", 1, walls_png)
        # Floor atlas variants are stacked 3 rows tall per layout
        self.parse_tile_mapping("static_assets/floors.txt", 2, floors_png, rows_per_variant=3)

        # Load all sprite assets into image bank 0 at different y-coordinates
        pyxel.images[0].load(0, 0, "sprite_assets/char_1.png")
        pyxel.images[0].load(0, 16, "sprite_assets/slime.png")
        pyxel.images[0].load(0, 32, "sprite_assets/spider.png")
        pyxel.images[0].load(0, 64, "static_assets/door_closed.png") # Door closed at (0, 64)
        pyxel.images[0].load(0, 80, "static_assets/door_open.png")   # Door open at (0, 80)
        # Decor and treasure: keep in bank 0 but place at x=128 to avoid overlapping sprite strips
        try:
            decor_h = self._png_height("static_assets/decor.png")
        except Exception:
            decor_h = 0
        base_decor_x = 128
        base_decor_y = 0
        pyxel.images[0].load(base_decor_x, base_decor_y, "static_assets/decor.png")
        # Place treasure directly beneath decor (aligned to 16px rows)
        def _align16(v: int) -> int:
            return (v + 15) // 16 * 16
        base_treasure_x = 128
        base_treasure_y = _align16(base_decor_y + max(0, decor_h))
        pyxel.images[0].load(base_treasure_x, base_treasure_y, "static_assets/treasure.png")

        # Spinner animations: 16x16 strips for idle and attack
        # Place below doors at y=96/112
        spinner_idle_y = 96
        spinner_attack_y = 112
        try:
            pyxel.images[0].load(0, spinner_idle_y, "sprite_assets/spinner_idle.png")
            iw = self._png_width("sprite_assets/spinner_idle.png")
            frames = max(1, iw // 16)
            self._register_anim_strip("spinner_idle", 0, spinner_idle_y, frames, frame_w=16, base_x=0)
        except Exception:
            pass
        try:
            pyxel.images[0].load(0, spinner_attack_y, "sprite_assets/spinner_attack.png")
            iw = self._png_width("sprite_assets/spinner_attack.png")
            frames = max(1, iw // 16)
            self._register_anim_strip("spinner_attack", 0, spinner_attack_y, frames, frame_w=16, base_x=0)
        except Exception:
            pass

        phantom_idle_right_y = 128
        phantom_idle_left_y = 144
        try:
            pyxel.images[0].load(0, phantom_idle_right_y, "sprite_assets/phantom_idle_anim_right_strip_4.png")
            self._register_anim_strip("phantom_idle_right", 0, phantom_idle_right_y, 4, frame_w=16, base_x=0)
        except Exception:
            pass
        try:
            pyxel.images[0].load(0, phantom_idle_left_y, "sprite_assets/phantom_idle_anim_left_strip_4.png")
            self._register_anim_strip("phantom_idle_left", 0, phantom_idle_left_y, 4, frame_w=16, base_x=0)
        except Exception:
            pass

        self.parse_anim_mapping("sprite_assets/char_1.txt", 0, "player", 0)
        self.parse_anim_mapping("sprite_assets/slime.txt", 0, "slime", 16)
        self.parse_anim_mapping("sprite_assets/spider.txt", 0, "spider", 32)
        self.parse_door_mapping("static_assets/door_closed.txt", 0, 64)
        self.parse_door_mapping("static_assets/door_open.txt", 0, 80)
        self.parse_decor_mapping("static_assets/decor.txt", 0, base_decor_y, "static_assets/decor.png", base_x=base_decor_x)
        self.parse_treasure_mapping("static_assets/treasure.txt", 0, base_treasure_y, "static_assets/treasure.png", base_x=base_treasure_x)

    def parse_tile_mapping(self, txt_file, img_bank, png_path=None, rows_per_variant=None):
        rows: list[list[str]] = []
        with open(txt_file, 'r') as f:
            for raw in f.readlines():
                line = raw.rstrip('\n')
                if not line.strip():
                    continue
                rows.append(line.split('\t'))

        if not rows:
            return

        base_rows = len(rows)
        block_rows = max(1, rows_per_variant or base_rows)

        total_rows = None
        if png_path:
            total_rows = max(1, self._png_height(png_path) // 16)

        rows_per_bank = 256 // TILE_SIZE
        if total_rows is None:
            variant_count = 1
        else:
            variant_count = max(1, (total_rows + block_rows - 1) // block_rows)

        for variant in range(variant_count):
            for local_y in range(block_rows):
                if local_y >= base_rows:
                    break
                fields = rows[local_y]
                tile_y = variant * block_rows + local_y
                if total_rows is not None and tile_y >= total_rows:
                    break
                chunk_span = self._tileset_chunk_span.get(
                    img_bank,
                    self._png_width(png_path) if png_path else len(fields) * TILE_SIZE,
                )
                rows_per_chunk = rows_per_bank
                chunk_index = tile_y // rows_per_chunk
                row_in_chunk = tile_y % rows_per_chunk
                v = row_in_chunk * TILE_SIZE
                for x, name in enumerate(fields):
                    if not name or name == '_':
                        continue
                    u = x * TILE_SIZE + chunk_index * chunk_span
                    self.tile_map.setdefault(name, []).append((img_bank, u, v))

        if base_rows > block_rows:
            extra_rows = rows[block_rows:]
            # Map leftover definitions onto the last available row to keep names accessible.
            if total_rows is None:
                tile_y = block_rows - 1
            else:
                tile_y = max(0, min(total_rows - 1, variant_count * block_rows))
            chunk_span = self._tileset_chunk_span.get(img_bank, self._png_width(png_path) if png_path else len(rows[0]) * TILE_SIZE)
            rows_per_chunk = rows_per_bank
            for local_offset, fields in enumerate(extra_rows):
                extra_tile_y = tile_y + local_offset
                chunk_index = extra_tile_y // rows_per_chunk
                row_in_chunk = extra_tile_y % rows_per_chunk
                v = row_in_chunk * TILE_SIZE
                for x, name in enumerate(fields):
                    if not name or name == '_':
                        continue
                    u = x * TILE_SIZE + chunk_index * chunk_span
                    self.tile_map.setdefault(name, []).append((img_bank, u, v))

    def parse_anim_mapping(self, txt_file, img_bank, anim_name, base_y):
        self.anim_map[anim_name] = []
        with open(txt_file, 'r') as f:
            line = f.read()
            names = line.strip().replace('\t', ' ').split(' ')
            for x, name in enumerate(names):
                if name:
                    self.anim_map[anim_name].append((img_bank, x * 16, base_y))

    def _png_width(self, png_path: str) -> int:
        # Parse PNG header to get image width from IHDR
        with open(png_path, 'rb') as f:
            sig = f.read(8)
            if sig != b"\x89PNG\r\n\x1a\n":
                return 0
            # Read IHDR
            _len = int.from_bytes(f.read(4), 'big')
            _typ = f.read(4)
            if _typ != b'IHDR':
                return 0
            data = f.read(13)
            width = int.from_bytes(data[0:4], 'big')
            return width if width > 0 else 0

    def _png_height(self, png_path: str) -> int:
        # Parse PNG header to get image height from IHDR
        with open(png_path, 'rb') as f:
            sig = f.read(8)
            if sig != b"\x89PNG\r\n\x1a\n":
                return 0
            _len = int.from_bytes(f.read(4), 'big')
            _typ = f.read(4)
            if _typ != b'IHDR':
                return 0
            data = f.read(13)
            height = int.from_bytes(data[4:8], 'big')
            return height if height > 0 else 0

    def _load_tileset(self, png_path: str, img_bank: int):
        height = self._png_height(png_path)
        width = self._png_width(png_path)
        if height <= 256:
            pyxel.images[img_bank].load(0, 0, png_path)
            self._tileset_chunk_span[img_bank] = width
            return

        chunks = self._slice_png_vertically(png_path, max_rows=256)
        chunk_count = len(chunks)
        if chunk_count * width > 256:
            for path in chunks:
                os.remove(path)
            raise RuntimeError(
                f"Sliced tileset {png_path} exceeds Pyxel image width; reduce stacking or re-slice."
            )
        for idx, chunk_path in enumerate(chunks):
            x_offset = idx * width
            pyxel.images[img_bank].load(x_offset, 0, chunk_path)
            os.remove(chunk_path)
        self._tileset_chunk_span[img_bank] = width

    def _slice_png_vertically(self, png_path: str, max_rows: int = 256) -> list[str]:
        with open(png_path, 'rb') as f:
            data = f.read()

        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError(f"{png_path} is not a PNG file")

        pos = 8
        width = height = bit_depth = color_type = None
        compression = filter_method = interlace = None
        palette_chunks = []
        trns_chunk = None
        idat_data = b''

        while pos < len(data):
            length = int.from_bytes(data[pos:pos+4], 'big')
            chunk_type = data[pos+4:pos+8]
            chunk_data = data[pos+8:pos+8+length]
            pos += 12 + length

            if chunk_type == b'IHDR':
                width = int.from_bytes(chunk_data[0:4], 'big')
                height = int.from_bytes(chunk_data[4:8], 'big')
                bit_depth = chunk_data[8]
                color_type = chunk_data[9]
                compression = chunk_data[10]
                filter_method = chunk_data[11]
                interlace = chunk_data[12]
            elif chunk_type == b'PLTE':
                palette_chunks.append(chunk_data)
            elif chunk_type == b'tRNS':
                trns_chunk = chunk_data
            elif chunk_type == b'IDAT':
                idat_data += chunk_data
            elif chunk_type == b'IEND':
                break

        if width is None or height is None:
            raise RuntimeError(f"{png_path} missing IHDR chunk")
        if bit_depth != 8:
            raise RuntimeError(f"{png_path} uses unsupported bit depth {bit_depth}")

        if color_type == 0:      # Grayscale
            bytes_per_pixel = 1
        elif color_type == 2:    # Truecolor RGB
            bytes_per_pixel = 3
        elif color_type == 3:    # Indexed colour
            bytes_per_pixel = 1
        elif color_type == 4:    # Grayscale + alpha
            bytes_per_pixel = 2
        elif color_type == 6:    # Truecolor + alpha
            bytes_per_pixel = 4
        else:
            raise RuntimeError(f"{png_path} uses unsupported color format: {color_type}")

        raw = zlib.decompress(idat_data)
        row_stride = bytes_per_pixel * width + 1  # include filter byte

        chunks_paths: list[str] = []
        for start_row in range(0, height, max_rows):
            end_row = min(height, start_row + max_rows)
            rows = raw[start_row * row_stride:end_row * row_stride]
            chunk_height = end_row - start_row
            compressed = zlib.compress(rows)
            png_bytes = [b"\x89PNG\r\n\x1a\n"]
            png_bytes.append(self._build_chunk(b'IHDR', struct.pack('>IIBBBBB', width, chunk_height, bit_depth, color_type, compression, filter_method, interlace)))
            for plte in palette_chunks:
                png_bytes.append(self._build_chunk(b'PLTE', plte))
            if trns_chunk is not None:
                png_bytes.append(self._build_chunk(b'tRNS', trns_chunk))
            png_bytes.append(self._build_chunk(b'IDAT', compressed))
            png_bytes.append(self._build_chunk(b'IEND', b''))
            with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
                tmp.write(b''.join(png_bytes))
            chunks_paths.append(tmp.name)
        return chunks_paths

    def _build_chunk(self, chunk_type: bytes, chunk_data: bytes) -> bytes:
        length = len(chunk_data)
        crc = binascii.crc32(chunk_type)
        crc = binascii.crc32(chunk_data, crc) & 0xffffffff
        return (
            struct.pack('>I', length)
            + chunk_type
            + chunk_data
            + struct.pack('>I', crc)
        )

    def _register_anim_strip(self, anim_name: str, img_bank: int, base_y: int, frames: int, frame_w: int = 16, base_x: int = 0):
        if frames <= 0:
            frames = 1
        if frame_w <= 0:
            frame_w = 16
        self.anim_map[anim_name] = [(img_bank, base_x + x * frame_w, base_y) for x in range(frames)]

    def parse_door_mapping(self, txt_file, img_bank, base_y):
        with open(txt_file, 'r') as f:
            line = f.read()
            names = line.strip().replace('\t', ' ').split(' ')
            for x, name in enumerate(names):
                if name:
                    self.tile_map.setdefault(name, []).append((img_bank, x * 16, base_y))

    def parse_decor_mapping(self, txt_file, img_bank, base_y, png_path, base_x: int = 0):
        # Tab-separated grid; supports multiple rows. Some rows may contain spaces in names; treat spaces as part of name.
        names_accum = []
        max_rows = max(0, self._png_height(png_path) // 16)
        with open(txt_file, 'r') as f:
            for y, line in enumerate(f.readlines()):
                if max_rows and y >= max_rows:
                    # Skip rows not present in the PNG atlas
                    continue
                # Keep exact fields split by tab; trim newline
                fields = [field for field in line.rstrip('\n').split('\t')]
                for x, name in enumerate(fields):
                    if name and name != '_' and name.lower() != 'empty':
                        self.tile_map.setdefault(name, []).append((img_bank, base_x + x * 16, base_y + y * 16))
                        names_accum.append(name)
        # Keep a list of available decor sprite names
        self.decor_names = names_accum

    def parse_treasure_mapping(self, txt_file, img_bank, base_y, png_path, base_x: int = 0):
        names_accum = []
        max_rows = max(0, self._png_height(png_path) // 16)
        with open(txt_file, 'r') as f:
            for y, line in enumerate(f.readlines()):
                if max_rows and y >= max_rows:
                    continue
                fields = [field for field in line.rstrip('\n').split('\t')]
                for x, name in enumerate(fields):
                    if name and name != '_' and name.lower() != 'empty':
                        self.tile_map.setdefault(name, []).append((img_bank, base_x + x * 16, base_y + y * 16))
                        names_accum.append(name)
        self.treasure_names = names_accum

    def get_tile(self, name, variant_index: int = 0):
        entry = self.tile_map.get(name)
        if entry is None:
            return None
        if isinstance(entry, list):
            if not entry:
                return None
            if variant_index < len(entry):
                return entry[variant_index]
            return entry[-1]
        return entry

    def get_anim(self, name):
        return self.anim_map.get(name)

    def get_tile_variant_count(self, name: str) -> int:
        entry = self.tile_map.get(name)
        if entry is None:
            return 0
        if isinstance(entry, list):
            return len(entry)
        return 1

    def get_anim_widths(self, name):
        # Uniform widths for all frames as per registration
        seq = self.anim_map.get(name) or []
        if not seq:
            return None
        # Infer width from adjacent frames' U, default to 16
        widths = []
        for i in range(len(seq)):
            if i + 1 < len(seq):
                widths.append(seq[i+1][1] - seq[i][1])
            else:
                widths.append(16)
        return widths
