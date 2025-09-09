import pyxel
import time
from enum import Enum
from map import PIT, WALL
from entity import SlimeProjectile
from vfx import VfxManager
from constants import TILE_SIZE, MAP_WIDTH, MAP_HEIGHT

class GamePhase(Enum):
    ENEMY_MOVE_TELEGRAPH = 1
    PLAYER_ACTION = 2
    ENEMY_ATTACK = 3
    PROJECTILE_RESOLUTION = 4

class CombatManager:
    def __init__(self, player, enemies, tilemap):
        self.player = player
        self.enemies = enemies
        self.tilemap = tilemap
        self.current_phase = GamePhase.ENEMY_MOVE_TELEGRAPH
        self.telegraphs = []
        self.projectiles = []
        self.vfx_manager = VfxManager()
        self.enemy_action_queue = []
        self.action_timer = 0
        self.action_delay = 10
        self.phase_started = True
        self.phase_complete = False # New flag to signal phase completion

        self._next_phase = {
            GamePhase.ENEMY_MOVE_TELEGRAPH: GamePhase.PLAYER_ACTION,
            GamePhase.PLAYER_ACTION: GamePhase.ENEMY_ATTACK,
            GamePhase.ENEMY_ATTACK: GamePhase.PROJECTILE_RESOLUTION,
            GamePhase.PROJECTILE_RESOLUTION: GamePhase.ENEMY_MOVE_TELEGRAPH, # Loop back
        }

    def update(self):
        if self.phase_complete:
            self.current_phase = self._next_phase[self.current_phase]
            self.phase_started = True
            self.phase_complete = False

        match self.current_phase:
            case GamePhase.ENEMY_MOVE_TELEGRAPH:
                self.handle_enemy_move_telegraph_phase()
            case GamePhase.PLAYER_ACTION:
                self.handle_player_action_phase()
            case GamePhase.ENEMY_ATTACK:
                self.handle_enemy_attack_phase()
            case GamePhase.PROJECTILE_RESOLUTION:
                self.handle_projectile_resolution_phase()

        for enemy in self.enemies:
            enemy.update_animation()

        self.vfx_manager.update()

    def handle_enemy_move_telegraph_phase(self):
        if self.phase_started:
            self.enemy_action_queue = []
            for enemy in self.enemies:
                self.enemy_action_queue.append({'action': 'move', 'enemy': enemy})
                self.enemy_action_queue.append({'action': 'telegraph', 'enemy': enemy})
            self.phase_started = False

        self.action_timer += 1
        if self.action_timer >= self.action_delay:
            self.action_timer = 0
            if self.enemy_action_queue:
                action = self.enemy_action_queue.pop(0)
                if action['action'] == 'move':
                    action['enemy'].move_towards_player(self.player)
                elif action['action'] == 'telegraph':
                    telegraph = action['enemy'].telegraph(self.player)
                    if telegraph:
                        self.telegraphs.append(telegraph)
            else:
                self.phase_complete = True

    def handle_player_action_phase(self):
        if self.phase_started:
            self.player.reset_moves()
            self.phase_started = False

        self.player.update()
        if pyxel.btnp(pyxel.KEY_SPACE):
            self.phase_complete = True

    def handle_enemy_attack_phase(self):
        self.resolve_enemy_attacks()
        if self.projectiles:
            # If there are projectiles, the next phase will be projectile resolution
            pass # Transition handled by update based on phase_complete
        else:
            # If no projectiles, we can directly transition to the next phase
            pass # Transition handled by update based on phase_complete
        self.phase_complete = True

    def handle_projectile_resolution_phase(self):
        self.update_projectiles()
        if not self.projectiles:
            self.phase_complete = True

    def move_enemies(self):
        for enemy in self.enemies:
            enemy.move_towards_player(self.player)

    def resolve_enemy_attacks(self):
        for telegraph in self.telegraphs:
            if telegraph.get('type') == 'bouncing':
                start_pos = telegraph['start']
                path = telegraph['path']
                projectile = SlimeProjectile(start_pos[0], start_pos[1], path, self.tilemap, self.player.asset_manager)
                self.projectiles.append(projectile)
            elif telegraph.get('type') == 'ranged':
                start_pos = telegraph['start']
                target_pos = telegraph['pos']
                projectile = SlimeProjectile(start_pos[0], start_pos[1], [target_pos], self.tilemap, self.player.asset_manager)
                self.projectiles.append(projectile)
            else:
                target_pos = telegraph['pos']
                
                # Check if player is at the target position
                if self.player.occupies(target_pos[0], target_pos[1]):
                    self.player.take_damage(1)
                    self.vfx_manager.add_particles(target_pos[0] * TILE_SIZE + TILE_SIZE / 2, target_pos[1] * TILE_SIZE + TILE_SIZE / 2, 8, 10)

                # Check if any enemy is at the target position
                for enemy in self.enemies:
                    if enemy.occupies(target_pos[0], target_pos[1]):
                        enemy.take_damage(1)
                        self.vfx_manager.add_particles(target_pos[0] * TILE_SIZE + TILE_SIZE / 2, target_pos[1] * TILE_SIZE + TILE_SIZE / 2, 8, 10)
        
        self.enemies = [enemy for enemy in self.enemies if enemy.hp > 0]
        self.telegraphs = []

    def update_projectiles(self):
        for p in self.projectiles:
            p.update()
            if p.segment >= len(p.path):
                self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 8, 20)
                if p in self.projectiles:
                    self.projectiles.remove(p)
            elif p.time == p.duration -1:
                tile_x = p.path[p.segment][0]
                tile_y = p.path[p.segment][1]
                
                # Check for wall collision
                if not (0 <= tile_x < MAP_WIDTH and 0 <= tile_y < MAP_HEIGHT):
                    self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 8, 20)
                    if p in self.projectiles:
                        self.projectiles.remove(p)
                        continue

                tile = self.tilemap.tiles[tile_y][tile_x]
                if tile == PIT or tile == WALL:
                    self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 8, 20)
                    if p in self.projectiles:
                        self.projectiles.remove(p)
                        continue

                if self.player.occupies(tile_x, tile_y):
                    self.player.take_damage(1)
                    self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 8, 20)
                    p.path = p.path[:p.segment+1]
                for enemy in self.enemies:
                    if enemy.occupies(tile_x, tile_y):
                        enemy.take_damage(1)
                        self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 8, 20)
                        p.path = p.path[:p.segment+1]
        
        if not self.projectiles:
            self.phase_complete = True

    def draw_projectiles(self):
        for p in self.projectiles:
            p.draw()


    def telegraph_enemy_attacks(self):
        self.telegraphs = []
        for enemy in self.enemies:
            telegraph = enemy.telegraph(self.player)
            if telegraph:
                self.telegraphs.append(telegraph)

    def draw_telegraphs(self):
        for telegraph in self.telegraphs:
            if telegraph.get('type') == 'bouncing':
                start_pos = telegraph['start']
                path = telegraph['path']
                if path:
                    start_x = start_pos[0] * TILE_SIZE + TILE_SIZE // 2
                    start_y = start_pos[1] * TILE_SIZE + TILE_SIZE // 2
                    end_x = path[-1][0] * TILE_SIZE + TILE_SIZE // 2
                    end_y = path[-1][1] * TILE_SIZE + TILE_SIZE // 2
                    pyxel.line(start_x, start_y, end_x, end_y, 13)
                for pos in path:
                    x = pos[0] * TILE_SIZE + TILE_SIZE // 2
                    y = pos[1] * TILE_SIZE + TILE_SIZE // 2
                    pyxel.circ(x, y, 2, 8)
            else:
                start_pos = telegraph['start']
                end_pos = telegraph['pos']
                
                start_x = start_pos[0] * TILE_SIZE + TILE_SIZE // 2
                start_y = start_pos[1] * TILE_SIZE + TILE_SIZE // 2
                end_x = end_pos[0] * TILE_SIZE + TILE_SIZE // 2
                end_y = end_pos[1] * TILE_SIZE + TILE_SIZE // 2

                pyxel.line(start_x, start_y, end_x, end_y, 8)
                pyxel.circ(end_x, end_y, 2, 8)