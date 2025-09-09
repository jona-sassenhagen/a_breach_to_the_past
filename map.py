import pyxel
from map_layout import get_layout
from constants import TILE_SIZE, MAP_WIDTH, MAP_HEIGHT, DOOR

# Tile types (now strings)
FLOOR = "floor_center"
WALL = "horizontal"
PIT = "pit"

class Tilemap:
    def __init__(self, asset_manager):
        self.asset_manager = asset_manager
        self.tiles = get_layout()
        self.tile_states = {}

        # Initialize door states with correct orientation
        for y in range(MAP_HEIGHT):
            for x in range(MAP_WIDTH):
                # Check if this is a door location based on map_layout's logic
                is_door_location = False
                if (y == 0 or y == MAP_HEIGHT - 1) and x == MAP_WIDTH // 2: is_door_location = True # Top/Bottom door
                if (x == 0 or x == MAP_WIDTH - 1) and y == MAP_HEIGHT // 2: is_door_location = True # Left/Right door

                if is_door_location:
                    if y == 0 or y == MAP_HEIGHT - 1: # Top or bottom wall
                        self.tile_states[(x,y)] = {'state': 'closed', 'orientation': 'horizontal'}
                    elif x == 0 or x == MAP_WIDTH - 1: # Left or right wall
                        self.tile_states[(x,y)] = {'state': 'closed', 'orientation': 'vertical'}

    def draw(self):
        for y in range(MAP_HEIGHT):
            for x in range(MAP_WIDTH):
                tile_name = self.tiles[y][x]
                
                # Always draw the base tile first
                if tile_name == PIT:
                    pyxel.rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE, 0)
                else:
                    tile_asset = self.asset_manager.get_tile(tile_name)
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
                    tile_asset = self.asset_manager.get_tile(asset_name)
                    if tile_asset:
                        img_bank, u, v = tile_asset
                        pyxel.blt(x * TILE_SIZE, y * TILE_SIZE, img_bank, u, v, TILE_SIZE, TILE_SIZE, 0)
