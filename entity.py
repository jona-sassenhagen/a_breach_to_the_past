import pyxel
from collections import deque
from map import WALL, PIT
from typing import List, Optional, Tuple
from constants import TILE_SIZE, MAP_WIDTH, MAP_HEIGHT, DOOR

class Entity:
    def __init__(self, x, y, tilemap, asset_manager, width=1, height=1):
        self.x = x
        self.y = y
        self.tilemap = tilemap
        self.asset_manager = asset_manager
        self.hp = 3
        self.width = width
        self.height = height
        self.anim_name = None
        self.anim_frame = 0
        self.anim_timer = 0

    def occupies(self, x, y):
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height

    def move(self, dx, dy, all_entities):
        new_x = self.x + dx
        new_y = self.y + dy
        for i in range(self.width):
            for j in range(self.height):
                if not (0 <= new_x + i < MAP_WIDTH and 0 <= new_y + j < MAP_HEIGHT):
                    return False
                tile = self.tilemap.tiles[new_y + j][new_x + i]
                if tile == WALL or tile == PIT:
                    return False
                door_info = self.tilemap.tile_states.get((new_x + i, new_y + j))
                if door_info and door_info.get('state') == 'closed':
                    return False

                # Check for collision with other entities
                for entity in all_entities:
                    if entity is not self and entity.occupies(new_x + i, new_y + j):
                        return False

        self.x = new_x
        self.y = new_y
        return True

    def take_damage(self, amount, target_pos=None):
        self.hp -= amount

    def update_animation(self):
        self.anim_timer += 1
        if self.anim_timer % 10 == 0:
            anim_seq = self.asset_manager.get_anim(self.anim_name)
            if anim_seq:
                self.anim_frame = (self.anim_frame + 1) % len(anim_seq)

    def draw(self):
        if self.anim_name:
            anim_seq = self.asset_manager.get_anim(self.anim_name)
            if anim_seq:
                img_bank, u, v = anim_seq[self.anim_frame]
                pyxel.blt(self.x * TILE_SIZE, self.y * TILE_SIZE, img_bank, u, v, TILE_SIZE, TILE_SIZE, 0)

    def pathfinding(self, target_x, target_y):
        q = deque([[(self.x, self.y)]])
        visited = set([(self.x, self.y)])

        while q:
            path = q.popleft()
            x, y = path[-1]

            if (x, y) == (target_x, target_y):
                return path

            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                new_x, new_y = x + dx, y + dy

                if (new_x, new_y) in visited:
                    continue

                # Validate footprint
                valid = True
                for i in range(self.width):
                    for j in range(self.height):
                        tx, ty = new_x + i, new_y + j
                        if not (0 <= tx < MAP_WIDTH and 0 <= ty < MAP_HEIGHT):
                            valid = False
                            break
                        tile = self.tilemap.tiles[ty][tx]
                        if tile == WALL or tile == PIT:
                            valid = False
                            break
                        door_info = self.tilemap.tile_states.get((tx, ty))
                        if door_info and door_info.get('state') == 'closed':
                            valid = False
                            break
                    if not valid:
                        break

                if not valid:
                    continue

                visited.add((new_x, new_y))
                new_path = list(path)
                new_path.append((new_x, new_y))
                q.append(new_path)
        return None

class Player(Entity):
    def __init__(self, x, y, tilemap, asset_manager):
        super().__init__(x, y, tilemap, asset_manager)
        self.action_direction = (1, 0)
        self.anim_name = "player"
        self.moves_left = 4

    def update(self, all_entities):
        if self.moves_left > 0:
            moved = False
            if pyxel.btnp(pyxel.KEY_W): moved = self.move(0, -1, all_entities)
            elif pyxel.btnp(pyxel.KEY_S): moved = self.move(0, 1, all_entities)
            elif pyxel.btnp(pyxel.KEY_A): moved = self.move(-1, 0, all_entities)
            elif pyxel.btnp(pyxel.KEY_D): moved = self.move(1, 0, all_entities)
            if moved:
                self.moves_left -= 1

    def reset_moves(self):
        self.moves_left = 4

    def draw(self):
        super().draw()
        # Draw remaining moves
        pyxel.text(self.x * TILE_SIZE, self.y * TILE_SIZE - 5, f"Moves: {self.moves_left}", 7)


class Enemy(Entity):
    def __init__(self, x, y, tilemap, asset_manager, move_speed, attack_type='melee', width=1, height=1):
        super().__init__(x, y, tilemap, asset_manager, width, height)
        self.move_speed = move_speed
        self.attack_type = attack_type
        self.hate_list: List[Entity] = []  # Priority list; index 0 is current top
        self._decay_pending: bool = False  # Whether to decay the top enemy next turn
        self.current_target: Optional[Entity] = None

    # --- Hate list and targeting ---
    def init_ai(self, player: 'Player'):
        if not self.hate_list:
            self.hate_list = [player]

    def begin_turn(self, player: 'Player', enemies: List['Enemy']):
        # Ensure initial state
        self.init_ai(player)

        # Remove dead or missing entries; always keep player present
        valid_set = set([player] + enemies)
        self.hate_list = [e for e in self.hate_list if e in valid_set and getattr(e, 'hp', 1) > 0]
        if player not in self.hate_list:
            self.hate_list.append(player)

        # Apply decay if pending and top is an enemy (not player)
        if self._decay_pending and self.hate_list:
            top = self.hate_list[0]
            if isinstance(top, Enemy) and len(self.hate_list) > 1:
                self.hate_list[0], self.hate_list[1] = self.hate_list[1], self.hate_list[0]
            self._decay_pending = False

        # Choose target: first alive entry
        self.current_target = None
        for e in self.hate_list:
            if getattr(e, 'hp', 1) > 0:
                self.current_target = e
                break

    def register_grief(self, attacker: 'Enemy'):
        if attacker is None or attacker is self:
            return
        # Move attacker to top of hate list and set decay for next turn
        if attacker in self.hate_list:
            self.hate_list.remove(attacker)
        self.hate_list.insert(0, attacker)
        self._decay_pending = True

    # --- Movement towards attack positions ---
    def get_attack_positions(self, target: Entity) -> List[Tuple[int, int]]:
        # Default: adjacent tiles (4-neighborhood)
        positions = []
        for dx, dy in [(1,0), (-1,0), (0,1), (0,-1)]:
            tx, ty = target.x + dx, target.y + dy
            if 0 <= tx < MAP_WIDTH and 0 <= ty < MAP_HEIGHT:
                tile = self.tilemap.tiles[ty][tx]
                if tile != WALL and tile != PIT:
                    door_info = self.tilemap.tile_states.get((tx, ty))
                    if not (door_info and door_info.get('state') == 'closed'):
                        positions.append((tx, ty))
        return positions

    def _tile_occupied(self, x: int, y: int, all_entities: List[Entity]) -> bool:
        for e in all_entities:
            if e is self:
                continue
            if e.occupies(x, y):
                return True
        return False

    def find_closest_attack_position(self, target: Entity, all_entities: List[Entity]) -> Optional[List[Tuple[int,int]]]:
        candidates = self.get_attack_positions(target)
        best_path = None
        best_len = 10**9
        for (gx, gy) in candidates:
            # Skip positions currently occupied
            if self._tile_occupied(gx, gy, all_entities):
                continue
            path = self.pathfinding(gx, gy)
            if path and len(path) < best_len:
                best_len = len(path)
                best_path = path
        return best_path

    def move_towards_target(self, target: Optional[Entity], all_entities: List[Entity]):
        if target is None:
            return
        path = self.find_closest_attack_position(target, all_entities)
        if not path:
            return
        for i in range(1, min(len(path), self.move_speed + 1)):
            if self.move(path[i][0] - self.x, path[i][1] - self.y, all_entities):
                self.x, self.y = path[i]
            else:
                break

    def telegraph(self, target: Entity, all_entities: Optional[List[Entity]] = None):
        # Default melee telegraph: only if adjacent to target
        if target is None:
            return None
        if abs(target.x - self.x) + abs(target.y - self.y) == 1:
            return {'start': (self.x, self.y), 'pos': (target.x, target.y), 'attacker': self}
        return None


class Slime(Enemy):
    def __init__(self, x, y, tilemap, asset_manager):
        super().__init__(x, y, tilemap, asset_manager, move_speed=1, attack_type='ranged')
        self.hp = 5
        self.anim_name = "slime"

    def get_attack_positions(self, target: Entity) -> List[Tuple[int,int]]:
        # All tiles in same row with clear horizontal line to target
        y = target.y
        positions: List[Tuple[int,int]] = []
        for x in range(MAP_WIDTH):
            # Skip blocked tiles
            tile = self.tilemap.tiles[y][x]
            if tile == WALL or tile == PIT:
                continue
            door_info = self.tilemap.tile_states.get((x, y))
            if door_info and door_info.get('state') == 'closed':
                continue
            # Check clear line between (x,y) and target.x along row
            blocked = False
            if x < target.x:
                rng = range(x + 1, target.x)
            else:
                rng = range(target.x + 1, x)
            for cx in rng:
                t = self.tilemap.tiles[y][cx]
                if t == WALL or t == PIT:
                    blocked = True
                    break
                d = self.tilemap.tile_states.get((cx, y))
                if d and d.get('state') == 'closed':
                    blocked = True
                    break
            # Slime hits every second tile; only positions with even distance to target are valid
            if not blocked and (abs(x - target.x) % 2 == 0):
                positions.append((x, y))
        return positions

    def telegraph(self, target: Entity, all_entities: Optional[List[Entity]] = None):
        # Fire only when horizontally aligned and with clear LoS; projectile skips every other tile
        if target is None or self.y != target.y:
            return None
        dx = target.x - self.x
        if dx == 0:
            return None
        direction = 1 if dx > 0 else -1
        y = self.y
        path = []
        x = self.x
        while True:
            x += 2 * direction  # bounce: every second tile
            if not (0 <= x < MAP_WIDTH):
                break
            tile = self.tilemap.tiles[y][x]
            if tile == WALL or tile == PIT:
                break
            door_info = self.tilemap.tile_states.get((x, y))
            if door_info and door_info.get('state') == 'closed':
                break
            path.append((x, y))
            # Do not force reaching target; projectile will truncate on first hit
        if not path:
            return None
        telegraph_info = {'start': (self.x, self.y), 'path': path, 'type': 'bouncing', 'attacker': self}
        self.hp -= 1  # Slime loses 1 HP when it attacks
        return telegraph_info

class SlimeProjectile:
    def __init__(self, start_x, start_y, path, tilemap, asset_manager, owner=None):
        self.tilemap = tilemap
        self.asset_manager = asset_manager
        self.start_x = start_x * TILE_SIZE
        self.start_y = start_y * TILE_SIZE
        self.x = float(self.start_x)
        self.y = float(self.start_y)
        self.path = path
        self.anim_name = "slime"
        self.duration = 8
        self.time = 0
        self.segment = 0
        self.anim_frame = 0
        self.anim_timer = 0
        self.y_offset = 0.0
        self.owner = owner

    def update_animation(self):
        self.anim_timer += 1
        if self.anim_timer % 10 == 0:
            anim_seq = self.asset_manager.get_anim(self.anim_name)
            if anim_seq:
                self.anim_frame = (self.anim_frame + 1) % len(anim_seq)

    def update(self):
        self.update_animation()
        self.time += 1
        if self.time >= self.duration:
            self.time = 0
            self.segment += 1

        if self.segment < len(self.path):
            start_x_seg = float(self.path[self.segment -1][0] * TILE_SIZE) if self.segment > 0 else float(self.start_x)
            start_y_seg = float(self.path[self.segment - 1][1] * TILE_SIZE) if self.segment > 0 else float(self.start_y)
            end_x_seg = float(self.path[self.segment][0] * TILE_SIZE)
            end_y_seg = float(self.path[self.segment][1] * TILE_SIZE)

            t = self.time / self.duration
            self.x = start_x_seg + (end_x_seg - start_x_seg) * t
            self.y = start_y_seg + (end_y_seg - start_y_seg) * t
            self.y_offset = -4.0 * TILE_SIZE * t * (1.0 - t)

    def draw(self):
        if self.anim_name:
            if self.segment >= len(self.path):
                return

            anim_seq = self.asset_manager.get_anim(self.anim_name)
            if anim_seq:
                img_bank, u, v = anim_seq[self.anim_frame]
                pyxel.blt(self.x, self.y + self.y_offset, img_bank, u, v, TILE_SIZE, TILE_SIZE, 0)

class Spider(Enemy):
    def __init__(self, x, y, tilemap, asset_manager):
        super().__init__(x, y, tilemap, asset_manager, move_speed=3)
        self.hp = 2
        self.anim_name = "spider"
