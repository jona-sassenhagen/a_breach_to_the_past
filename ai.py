from typing import List, Optional, Tuple, Dict
from collections import deque

from constants import MAP_WIDTH, MAP_HEIGHT
from map import is_walkable_tile


def init_ai(enemy, player, enemies: List):
    # Initialize or refresh hate map
    hate: Dict[object, int] = getattr(enemy, 'hate_map', None) or {}
    # Ensure player entry at least 1
    if player not in hate:
        hate[player] = 1
    else:
        hate[player] = max(1, hate[player])
    # Ensure entries for other enemies (except self)
    for e in enemies:
        if e is enemy:
            continue
        hate.setdefault(e, 0)
    enemy.hate_map = hate


def begin_turn(enemy, player, enemies: List, initiative: Optional[List] = None):
    # Normalize hate state
    init_ai(enemy, player, enemies)
    # Remove entries for things no longer present or dead, except keep player
    keys = list(enemy.hate_map.keys())
    for k in keys:
        if k is player:
            continue
        if k not in enemies or getattr(k, 'hp', 0) <= 0:
            enemy.hate_map.pop(k, None)

    # Select current target with tie-breakers
    enemy.current_target = select_target(enemy, player, enemies, initiative)


def select_target(enemy, player, enemies: List, initiative: Optional[List] = None):
    # Consider player and all alive enemies except self
    candidates = []
    for e in [player] + list(enemies):
        if e is enemy:
            continue
        if getattr(e, 'hp', 0) <= 0:
            continue
        candidates.append(e)
    if not candidates:
        return None
    # Max hate value
    hate = enemy.hate_map
    max_val = max(hate.get(c, 0 if c is not player else 1) for c in candidates)
    top = [c for c in candidates if (hate.get(c, 0 if c is not player else 1) == max_val)]
    # If player ties, choose player
    if player in top:
        return player
    # Otherwise, deterministic order fallback
    if initiative:
        for i in initiative:
            if i in top:
                return i
    # Fallback to given enemies order
    for e in enemies:
        if e in top:
            return e
    return top[0]


def adjust_hate_on_hit(attacker, victim, damage, player):
    # Only enemies maintain hate; ignore if attacker has no hate_map
    if not hasattr(attacker, 'hate_map'):
        return
    if damage <= 0:
        return
    delta = 2 * damage
    # Decrease attacker's hate toward the victim
    cur = attacker.hate_map.get(victim, 0 if victim is not player else 1)
    new_val = cur - delta
    floor = 1 if victim is player else 0
    attacker.hate_map[victim] = max(floor, new_val)

    # If victim is an enemy with a hate_map (not the player) and attacker is an enemy, increase their hate toward attacker
    if hasattr(victim, 'hate_map') and victim is not player:
        victim.hate_map[attacker] = victim.hate_map.get(attacker, 0) + delta


def get_attack_positions_adjacent(enemy, target) -> List[Tuple[int, int]]:
    positions = []
    for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
        tx, ty = target.x + dx, target.y + dy
        if 0 <= tx < MAP_WIDTH and 0 <= ty < MAP_HEIGHT:
            tile = enemy.tilemap.tiles[ty][tx]
            door_info = enemy.tilemap.tile_states.get((tx, ty))
            if is_walkable_tile(tile, door_info):
                positions.append((tx, ty))
    return positions


def _tile_occupied(enemy, x: int, y: int, all_entities: List) -> bool:
    for e in all_entities:
        if e is enemy:
            continue
        if e.occupies(x, y):
            return True
    return False


def _pathfinding_avoid_entities(enemy, goal_x: int, goal_y: int, all_entities: List) -> Optional[List[Tuple[int, int]]]:
    start = (enemy.x, enemy.y)
    q = deque([[start]])
    visited = set([start])

    def _footprint_clear(x: int, y: int) -> bool:
        for i in range(enemy.width):
            for j in range(enemy.height):
                tx, ty = x + i, y + j
                if not (0 <= tx < MAP_WIDTH and 0 <= ty < MAP_HEIGHT):
                    return False
                tile = enemy.tilemap.tiles[ty][tx]
                door_info = enemy.tilemap.tile_states.get((tx, ty))
                if not is_walkable_tile(tile, door_info):
                    return False
                for e in all_entities:
                    if e is enemy:
                        continue
                    if e.occupies(tx, ty):
                        return False
        return True

    while q:
        path = q.popleft()
        x, y = path[-1]
        if (x, y) == (goal_x, goal_y):
            return path
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx, ny = x + dx, y + dy
            if (nx, ny) in visited:
                continue
            if not _footprint_clear(nx, ny):
                continue
            visited.add((nx, ny))
            q.append(path + [(nx, ny)])
    return None


def find_closest_attack_position(enemy, target, all_entities: List) -> Optional[List[Tuple[int, int]]]:
    candidates = enemy.get_attack_positions(target)
    best_path = None
    best_len = 10 ** 9
    for (gx, gy) in candidates:
        if _tile_occupied(enemy, gx, gy, all_entities):
            continue
        path = _pathfinding_avoid_entities(enemy, gx, gy, all_entities)
        if path and len(path) < best_len:
            best_len = len(path)
            best_path = path
    return best_path


def move_towards_target(enemy, target, all_entities: List):
    if target is None:
        return
    path = find_closest_attack_position(enemy, target, all_entities)
    if not path:
        return
    for i in range(1, min(len(path), enemy.move_speed + 1)):
        if enemy.move(path[i][0] - enemy.x, path[i][1] - enemy.y, all_entities):
            enemy.x, enemy.y = path[i]
        else:
            break


def get_attack_positions_slime(enemy, target) -> List[Tuple[int, int]]:
    # Same row or column with clear LoS; prefer even distance so slime can shoot every second tile
    positions: List[Tuple[int, int]] = []
    y = target.y
    for x in range(MAP_WIDTH):
        tile = enemy.tilemap.tiles[y][x]
        door_info = enemy.tilemap.tile_states.get((x, y))
        if not is_walkable_tile(tile, door_info):
            continue
        blocked = False
        if x < target.x:
            rng = range(x + 1, target.x)
        else:
            rng = range(target.x + 1, x)
        for cx in rng:
            t = enemy.tilemap.tiles[y][cx]
            d = enemy.tilemap.tile_states.get((cx, y))
            if not is_walkable_tile(t, d):
                blocked = True
                break
        if not blocked and (abs(x - target.x) % 2 == 0):
            positions.append((x, y))

    x = target.x
    for y in range(MAP_HEIGHT):
        tile = enemy.tilemap.tiles[y][x]
        door_info = enemy.tilemap.tile_states.get((x, y))
        if not is_walkable_tile(tile, door_info):
            continue
        blocked = False
        if y < target.y:
            rng = range(y + 1, target.y)
        else:
            rng = range(target.y + 1, y)
        for cy in rng:
            t = enemy.tilemap.tiles[cy][x]
            d = enemy.tilemap.tile_states.get((x, cy))
            if not is_walkable_tile(t, d):
                blocked = True
                break
        if not blocked and (abs(y - target.y) % 2 == 0):
            pos = (x, y)
            if pos not in positions:
                positions.append(pos)
    return positions


def telegraph_melee(enemy, target):
    if target is None:
        return None
    if abs(target.x - enemy.x) + abs(target.y - enemy.y) == 1:
        return {'start': (enemy.x, enemy.y), 'pos': (target.x, target.y), 'attacker': enemy}
    return None


def telegraph_slime(enemy, target):
    if target is None:
        return None
    path: List[Tuple[int, int]] = []
    # Horizontal alignment
    if enemy.y == target.y and enemy.x != target.x:
        direction = 1 if target.x - enemy.x > 0 else -1
        y = enemy.y
        x = enemy.x
        while True:
            x += 2 * direction
            if not (0 <= x < MAP_WIDTH):
                break
            tile = enemy.tilemap.tiles[y][x]
            door_info = enemy.tilemap.tile_states.get((x, y))
            if not is_walkable_tile(tile, door_info):
                break
            path.append((x, y))
    # Vertical alignment
    elif enemy.x == target.x and enemy.y != target.y:
        direction = 1 if target.y - enemy.y > 0 else -1
        x = enemy.x
        y = enemy.y
        while True:
            y += 2 * direction
            if not (0 <= y < MAP_HEIGHT):
                break
            tile = enemy.tilemap.tiles[y][x]
            door_info = enemy.tilemap.tile_states.get((x, y))
            if not is_walkable_tile(tile, door_info):
                break
            path.append((x, y))
    if not path:
        return None
    telegraph_info = {'start': (enemy.x, enemy.y), 'path': path, 'type': 'bouncing', 'attacker': enemy}
    return telegraph_info
