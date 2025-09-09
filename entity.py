import pyxel
from collections import deque
from map import WALL, PIT
import ai
from typing import List, Optional, Tuple, Dict
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
        self.palette_swap = None  # Optional dict of {src_color: dst_color}

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
                if self.palette_swap:
                    for src, dst in self.palette_swap.items():
                        pyxel.pal(src, dst)
                pyxel.blt(self.x * TILE_SIZE, self.y * TILE_SIZE, img_bank, u, v, TILE_SIZE, TILE_SIZE, 0)
                if self.palette_swap:
                    pyxel.pal()

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
        self.hate_map: Dict[Entity, int] = {}  # Per-target hate values
        self.current_target: Optional[Entity] = None

    # --- Hate list and targeting ---
    def init_ai(self, player: 'Player', enemies: List['Enemy']):
        ai.init_ai(self, player, enemies)

    def begin_turn(self, player: 'Player', enemies: List['Enemy'], initiative: Optional[List['Enemy']] = None):
        ai.begin_turn(self, player, enemies, initiative)

    # Hate is adjusted on hit via ai.adjust_hate_on_hit; no direct grief mechanics

    # --- Movement towards attack positions ---
    def get_attack_positions(self, target: Entity) -> List[Tuple[int, int]]:
        return ai.get_attack_positions_adjacent(self, target)

    def move_towards_target(self, target: Optional[Entity], all_entities: List[Entity]):
        ai.move_towards_target(self, target, all_entities)

    def telegraph(self, target: Entity, all_entities: Optional[List[Entity]] = None):
        return ai.telegraph_melee(self, target)


class Slime(Enemy):
    def __init__(self, x, y, tilemap, asset_manager):
        super().__init__(x, y, tilemap, asset_manager, move_speed=1, attack_type='ranged')
        self.hp = 5
        self.anim_name = "slime"
        # Apply palette swap to distinguish smart slime
        self.palette_swap = {
            1: 8,
            2: 13,
            3: 12,
            4: 7,
            5: 14,
            6: 15,
            7: 10,
            8: 2,
            9: 12,
            10: 13,
            11: 8,
            12: 11,
            13: 9,
            14: 5,
            15: 6,
        }

    def get_attack_positions(self, target: Entity) -> List[Tuple[int,int]]:
        return ai.get_attack_positions_slime(self, target)

    def telegraph(self, target: Entity, all_entities: Optional[List[Entity]] = None):
        return ai.telegraph_slime(self, target)

class SlimeProjectile:
    def __init__(self, start_x, start_y, path, tilemap, asset_manager, owner=None, cosmetic: bool = False):
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
        self.cosmetic = cosmetic

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

class Decor(Entity):
    def __init__(self, x, y, tilemap, asset_manager, sprite_name: str, rubble_sprite: str = "broken_pot_1"):
        super().__init__(x, y, tilemap, asset_manager)
        self.sprite_name = sprite_name
        self.is_rubble = False
        self.rubble_ticks = 0  # how many round-starts to persist rubble
        self._rubble_sprite = rubble_sprite

    def occupies(self, x, y):
        # Blocks movement only while intact
        if self.is_rubble:
            return False
        return super().occupies(x, y)

    def break_to_rubble(self):
        self.is_rubble = True
        self.rubble_ticks = 1

    def draw(self):
        name = self._rubble_sprite if self.is_rubble else self.sprite_name
        tile_asset = self.asset_manager.get_tile(name)
        if tile_asset:
            img_bank, u, v = tile_asset
            pyxel.blt(self.x * TILE_SIZE, self.y * TILE_SIZE, img_bank, u, v, TILE_SIZE, TILE_SIZE, 0)

class Spider(Enemy):
    def __init__(self, x, y, tilemap, asset_manager):
        super().__init__(x, y, tilemap, asset_manager, move_speed=3)
        self.hp = 2
        self.anim_name = "spider"
        # Lunge animation state (forward -> linger -> retreat)
        self._lunge_t = 0
        self._lunge_forward = 3   # quick
        self._lunge_linger = 8    # hold
        self._lunge_retreat = 10  # slow
        self._lunge_dx_px = 0
        self._lunge_dy_px = 0

    def trigger_lunge(self, target_pos: Tuple[int, int]):
        # Set a small pixel offset toward the attacked tile
        tx, ty = target_pos
        dx = max(-1, min(1, tx - self.x))
        dy = max(-1, min(1, ty - self.y))
        amplitude = 6  # pixels, deeper reach into target tile
        self._lunge_dx_px = dx * amplitude
        self._lunge_dy_px = dy * amplitude
        self._lunge_t = 1  # start lunge on next draw/update cycle

    def update_animation(self):
        super().update_animation()
        if self._lunge_t > 0:
            self._lunge_t += 1
            total = self._lunge_forward + self._lunge_linger + self._lunge_retreat
            if self._lunge_t > total:
                # Reset lunge
                self._lunge_t = 0
                self._lunge_dx_px = 0
                self._lunge_dy_px = 0

    def draw(self):
        # Compute lunge offset (ease out and back)
        ox = oy = 0
        if self._lunge_t > 0:
            f = 0.0
            t = self._lunge_t
            fwd = max(1, self._lunge_forward)
            linger = self._lunge_linger
            ret = max(1, self._lunge_retreat)
            if t <= fwd:
                # Super quick forward (ease-out): quadratic approach to 1
                x = t / fwd
                f = 1 - (1 - x) * (1 - x)
            elif t <= fwd + linger:
                # Linger at full extension
                f = 1.0
            else:
                # Slow retreat (ease-in): quadratic from 1 to 0
                x = (t - fwd - linger) / ret
                f = (1 - x) * (1 - x)
            ox = int(self._lunge_dx_px * f)
            oy = int(self._lunge_dy_px * f)

        if self.anim_name:
            anim_seq = self.asset_manager.get_anim(self.anim_name)
            if anim_seq:
                img_bank, u, v = anim_seq[self.anim_frame]
                if self.palette_swap:
                    for src, dst in self.palette_swap.items():
                        pyxel.pal(src, dst)
                pyxel.blt(self.x * TILE_SIZE + ox, self.y * TILE_SIZE + oy, img_bank, u, v, TILE_SIZE, TILE_SIZE, 0)
                if self.palette_swap:
                    pyxel.pal()

class DumbSlime(Slime):
    def __init__(self, x, y, tilemap, asset_manager):
        super().__init__(x, y, tilemap, asset_manager)
        # Dumb slime should use original palette (no swap)
        self.palette_swap = None

    def move_towards_target(self, target: Optional[Entity], all_entities: List[Entity]):
        # Move directly toward player's tile; pathfinding will stop before collisions
        if target is None:
            return
        path = self.pathfinding(target.x, target.y)
        if not path:
            return
        for i in range(1, min(len(path), self.move_speed + 1)):
            if self.move(path[i][0] - self.x, path[i][1] - self.y, all_entities):
                self.x, self.y = path[i]
            else:
                break

    def telegraph(self, target: Entity, all_entities: Optional[List[Entity]] = None):
        # Always fire if horizontally aligned (same as normal slime telegraph)
        return ai.telegraph_slime(self, target)

    # Use base begin_turn to respect hate/grief mechanics

    # Use base draw without overlays; dumb slime matches original palette
