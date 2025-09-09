import pyxel

class AssetManager:
    def __init__(self):
        self.tile_map = {}
        self.anim_map = {}
        self.decor_names = []
        self.load_assets()

    def load_assets(self):
        # Load tilemap assets into banks 1 and 2
        pyxel.images[1].load(0, 0, "static_assets/walls.png")
        pyxel.images[2].load(0, 0, "static_assets/floors.png")
        self.parse_tile_mapping("static_assets/walls.txt", 1)
        self.parse_tile_mapping("static_assets/floors.txt", 2)

        # Load all sprite assets into image bank 0 at different y-coordinates
        pyxel.images[0].load(0, 0, "sprite_assets/char_1.png")
        pyxel.images[0].load(0, 16, "sprite_assets/slime.png")
        pyxel.images[0].load(0, 32, "sprite_assets/spider.png")
        pyxel.images[0].load(0, 64, "static_assets/door_closed.png") # Door closed at (0, 64)
        pyxel.images[0].load(0, 80, "static_assets/door_open.png")   # Door open at (0, 80)
        # Decor atlas below doors
        pyxel.images[0].load(0, 96, "static_assets/decor.png")      # Decor starts at (0, 96)

        self.parse_anim_mapping("sprite_assets/char_1.txt", 0, "player", 0)
        self.parse_anim_mapping("sprite_assets/slime.txt", 0, "slime", 16)
        self.parse_anim_mapping("sprite_assets/spider.txt", 0, "spider", 32)
        self.parse_door_mapping("static_assets/door_closed.txt", 0, 64)
        self.parse_door_mapping("static_assets/door_open.txt", 0, 80)
        self.parse_decor_mapping("static_assets/decor.txt", 0, 96)

    def parse_tile_mapping(self, txt_file, img_bank):
        with open(txt_file, 'r') as f:
            for y, line in enumerate(f.readlines()):
                for x, name in enumerate(line.strip().split('\t')):
                    if name != '_':
                        self.tile_map[name] = (img_bank, x * 16, y * 16)

    def parse_anim_mapping(self, txt_file, img_bank, anim_name, base_y):
        self.anim_map[anim_name] = []
        with open(txt_file, 'r') as f:
            line = f.read()
            names = line.strip().replace('\t', ' ').split(' ')
            for x, name in enumerate(names):
                if name:
                    self.anim_map[anim_name].append((img_bank, x * 16, base_y))

    def parse_door_mapping(self, txt_file, img_bank, base_y):
        with open(txt_file, 'r') as f:
            line = f.read()
            names = line.strip().replace('\t', ' ').split(' ')
            for x, name in enumerate(names):
                if name:
                    self.tile_map[name] = (img_bank, x * 16, base_y)

    def parse_decor_mapping(self, txt_file, img_bank, base_y):
        # Tab-separated grid; supports multiple rows. Some rows may contain spaces in names; treat spaces as part of name.
        names_accum = []
        with open(txt_file, 'r') as f:
            for y, line in enumerate(f.readlines()):
                # Keep exact fields split by tab; trim newline
                fields = [field for field in line.rstrip('\n').split('\t')]
                for x, name in enumerate(fields):
                    if name and name != '_' and name.lower() != 'empty':
                        self.tile_map[name] = (img_bank, x * 16, base_y + y * 16)
                        names_accum.append(name)
        # Keep a list of available decor sprite names
        self.decor_names = names_accum

    def get_tile(self, name):
        return self.tile_map.get(name)

    def get_anim(self, name):
        return self.anim_map.get(name)
