import pyxel
from map_layout import get_layout
from constants import TILE_SIZE, MAP_WIDTH, MAP_HEIGHT

# Tile types (now strings)
FLOOR = "floor_center"
PIT = "pit"


def is_walkable_tile(tile_name, door_info):
    if tile_name == PIT:
        return False
    if door_info and door_info.get('state') == 'closed':
        return False
    if tile_name and tile_name.startswith('floor'):
        return True
    if door_info and door_info.get('state') == 'open':
        return True
    return False

class Tilemap:
    def __init__(self, asset_manager, variant_index: int = 0):
        self.asset_manager = asset_manager
        floor_variants = asset_manager.get_tile_variant_count("floor_center") or 1
        wall_variants = asset_manager.get_tile_variant_count("horizontal") or 1
        self.variant_count = max(1, min(floor_variants, wall_variants))
        self.variant_index = variant_index % self.variant_count
        self.tiles = get_layout()
        self.tile_states = {}

        # Initialize door states: two at top row, two at bottom row; none at left/right
        self.top_door_xs = [MAP_WIDTH // 3, MAP_WIDTH - 1 - MAP_WIDTH // 3]
        self.bottom_door_xs = list(self.top_door_xs)
        for x in self.top_door_xs:
            self.tile_states[(x, 0)] = {'state': 'closed', 'orientation': 'horizontal'}
        for x in self.bottom_door_xs:
            self.tile_states[(x, MAP_HEIGHT - 1)] = {'state': 'closed', 'orientation': 'horizontal'}

    def is_open_door(self, x: int, y: int) -> bool:
        info = self.tile_states.get((x, y))
        return bool(info and info.get('state') == 'open')

    def is_closed_horizontal_door(self, x: int, y: int) -> bool:
        info = self.tile_states.get((x, y))
        return bool(info and info.get('state') == 'closed' and info.get('orientation') == 'horizontal')

    def draw(self):
        for y in range(MAP_HEIGHT):
            for x in range(MAP_WIDTH):
                tile_name = self.tiles[y][x]
                
                # Always draw the base tile first
                if tile_name == PIT:
                    pyxel.rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE, 0)
                else:
                    tile_asset = self.asset_manager.get_tile(tile_name, self.variant_index)
                    if tile_asset:
                        img_bank, u, v = tile_asset
                        pyxel.blt(x * TILE_SIZE, y * TILE_SIZE, img_bank, u, v, TILE_SIZE, TILE_SIZE, 0)
                    else:
                        pyxel.rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE, 11) # Error tile

                # Then, draw door or burning state on top if applicable
                if (x,y) in self.tile_states and self.tile_states[(x,y)] == 'burning':
                    pyxel.rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE, 8)
                elif (x,y) in self.tile_states and 'state' in self.tile_states[(x,y)]:
                    door_info = self.tile_states[(x,y)]
                    if door_info['state'] == 'closed':
                        asset_name = f"door_closed_{door_info['orientation']}"
                    else:
                        asset_name = f"door_open_{door_info['orientation']}"
                    tile_asset = self.asset_manager.get_tile(asset_name, self.variant_index)
                    if tile_asset:
                        img_bank, u, v = tile_asset
                        pyxel.blt(x * TILE_SIZE, y * TILE_SIZE, img_bank, u, v, TILE_SIZE, TILE_SIZE, 0)
