import pyxel
from collections import deque
from map import WALL, PIT
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

                if (new_x, new_y) not in visited:
                    for i in range(self.width):
                        for j in range(self.height):
                            if not (0 <= new_x + i < MAP_WIDTH and 0 <= new_y + j < MAP_HEIGHT):
                                continue
                            tile = self.tilemap.tiles[new_y + j][new_x + i]
                            if tile == WALL or tile == PIT:
                                continue
                            door_info = self.tilemap.tile_states.get((new_x + i, new_y + j))
                            if door_info and door_info.get('state') == 'closed':
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

    def move_towards_player(self, player, all_entities):
        path = self.pathfinding(player.x, player.y)
        if path:
            for i in range(1, min(len(path), self.move_speed + 1)):
                # Check collision before moving
                if self.move(path[i][0] - self.x, path[i][1] - self.y, all_entities):
                    self.x, self.y = path[i]
                else:
                    break # Stop if collision detected

    def telegraph(self, player):
        dx = player.x - self.x
        dy = player.y - self.y

        if abs(dx) > abs(dy):
            if dx > 0: target_pos = (self.x + 1, self.y)
            else: target_pos = (self.x - 1, self.y)
        else:
            if dy > 0: target_pos = (self.x, self.y + 1)
            else: target_pos = (self.x, self.y - 1)
        
        if 0 <= target_pos[0] < MAP_WIDTH and 0 <= target_pos[1] < MAP_HEIGHT:
            tile = self.tilemap.tiles[target_pos[1]][target_pos[0]]
            if tile != WALL and tile != PIT:
                return {'start': (self.x, self.y), 'pos': target_pos}
        return None


class Slime(Enemy):
    def __init__(self, x, y, tilemap, asset_manager):
        super().__init__(x, y, tilemap, asset_manager, move_speed=1, attack_type='ranged')
        self.hp = 5
        self.anim_name = "slime"

    def telegraph(self, player):
        dx = player.x - self.x
        
        if dx > 0:
            direction = 1
        else:
            direction = -1

        path = []
        for i in range(2, MAP_WIDTH, 2):
            target_x = self.x + i * direction
            target_y = self.y

            if not (0 <= target_x < MAP_WIDTH):
                break

            path.append((target_x, target_y))

            tile = self.tilemap.tiles[target_y][target_x]
            if tile == WALL or tile == PIT:
                break

            if player.occupies(target_x, target_y):
                break

        telegraph_info = {'start': (self.x, self.y), 'path': path, 'type': 'bouncing'}
        if telegraph_info:
            self.hp -= 1 # Slime loses 1 HP when it attacks
        return telegraph_info

class SlimeProjectile:
    def __init__(self, start_x, start_y, path, tilemap, asset_manager):
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
