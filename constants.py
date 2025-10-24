import os

TILE_SIZE = 16
MAP_WIDTH = 10
MAP_HEIGHT = 10
DOOR = "door"
MAX_FLOORS = max(1, int(os.getenv("DUNGEON_BREACH_ROOMS", "7")))
