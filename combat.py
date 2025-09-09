import pyxel
import time
from enum import Enum
from map import PIT, WALL
from entity import SlimeProjectile
import ai
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
        self.next_phase_override = None

        # Deterministic initiative order and attack order visualization
        self.enemy_initiative = list(enemies)
        self.attack_order_map = {}

        # Sequential attack processing
        self.attack_queue = []
        self.attack_index = 0
        self.anim_lock_ticks = 0
        self.next_phase_override = None

        # Deterministic initiative order (static spawn order)
        self.enemy_initiative = list(enemies)

        # Sequential attack processing
        self.attack_queue = []
        self.attack_index = 0

        self._next_phase = {
            GamePhase.ENEMY_MOVE_TELEGRAPH: GamePhase.PLAYER_ACTION,
            GamePhase.PLAYER_ACTION: GamePhase.ENEMY_ATTACK,
            GamePhase.ENEMY_ATTACK: GamePhase.PROJECTILE_RESOLUTION,
            GamePhase.PROJECTILE_RESOLUTION: GamePhase.ENEMY_MOVE_TELEGRAPH, # Loop back
        }

    def update(self):
        if self.phase_complete:
            if self.next_phase_override is not None:
                self.current_phase = self.next_phase_override
                self.next_phase_override = None
            else:
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

        # Tick down any attack animation locks (e.g., spider lunge linger)
        if self.anim_lock_ticks > 0:
            self.anim_lock_ticks -= 1

        for enemy in self.enemies:
            enemy.update_animation()

        self.vfx_manager.update()

    def handle_enemy_move_telegraph_phase(self):
        if self.phase_started:
            self.enemy_action_queue = []
            # Begin turn: update hate maps and choose targets in static initiative order
            ordered = [e for e in self.enemy_initiative if e in self.enemies]
            for enemy in ordered:
                enemy.begin_turn(self.player, self.enemies, self.enemy_initiative)
            for enemy in ordered:
                self.enemy_action_queue.append({'action': 'move', 'enemy': enemy})
                self.enemy_action_queue.append({'action': 'telegraph', 'enemy': enemy})
            self.phase_started = False

        self.action_timer += 1
        if self.action_timer >= self.action_delay:
            self.action_timer = 0
            if self.enemy_action_queue:
                action = self.enemy_action_queue.pop(0)
                all_entities = [self.player] + self.enemies # Create all_entities list
                if action['action'] == 'move':
                    # Move towards an attack position for selected target
                    action['enemy'].move_towards_target(action['enemy'].current_target, all_entities)
                elif action['action'] == 'telegraph':
                    telegraph = action['enemy'].telegraph(action['enemy'].current_target, all_entities)
                    if telegraph:
                        if 'attacker' not in telegraph:
                            telegraph['attacker'] = action['enemy']
                        self.telegraphs.append(telegraph)
            else:
                # Compute attack order numbers based on initiative and who telegraphed
                self._compute_attack_order_map()
                self.phase_complete = True

    def handle_player_action_phase(self):
        if self.phase_started:
            self.player.reset_moves()
            self.phase_started = False

        all_entities = [self.player] + self.enemies # Create all_entities list
        self.player.update(all_entities)
        # End player phase on spacebar or when out of moves
        if pyxel.btnp(pyxel.KEY_SPACE) or getattr(self.player, 'moves_left', 0) <= 0:
            self.phase_complete = True

    def handle_enemy_attack_phase(self):
        # If an animation lock is active, wait before processing next attack
        if self.anim_lock_ticks > 0:
            return
        # Build a deterministic, sequential attack queue on phase start
        if self.phase_started:
            tele_by_attacker = {}
            for t in self.telegraphs:
                attacker = t.get('attacker')
                if attacker is not None:
                    tele_by_attacker[attacker] = t
            self.attack_queue = []
            ordered = [e for e in self.enemy_initiative if e in self.enemies]
            for enemy in ordered:
                t = tele_by_attacker.get(enemy)
                if t is not None:
                    self.attack_queue.append(t)
            self.attack_index = 0
            # Clear telegraphs now; we will process from queue
            self.telegraphs = []
            self.phase_started = False

        # If no pending attacks, end phase
        if self.attack_index >= len(self.attack_queue):
            self.phase_complete = True
            return

        self.action_timer += 1
        if self.action_timer < self.action_delay:
            return
        self.action_timer = 0

        # Process next attack in queue if attacker still alive
        telegraph = self.attack_queue[self.attack_index]
        attacker = telegraph.get('attacker')
        if attacker not in self.enemies or getattr(attacker, 'hp', 0) <= 0:
            self.attack_index += 1
            return

        self.resolve_single_enemy_attack(telegraph)

        # If projectiles were spawned, go resolve them, then return to continue queue
        if self.projectiles:
            self.attack_index += 1
            self.next_phase_override = GamePhase.PROJECTILE_RESOLUTION
            self.phase_complete = True
        else:
            # Continue to next attack on next tick
            self.attack_index += 1

    def handle_projectile_resolution_phase(self):
        self.update_projectiles()
        if not self.projectiles:
            # If there are more sequential attacks pending, go back to ENEMY_ATTACK
            if self.attack_index < len(self.attack_queue):
                self.next_phase_override = GamePhase.ENEMY_ATTACK
            else:
                self.next_phase_override = None
            self.phase_complete = True

    def resolve_single_enemy_attack(self, telegraph):
        if telegraph.get('type') == 'bouncing':
            start_pos = telegraph['start']
            path = telegraph['path']
            attacker = telegraph.get('attacker')
            projectile = SlimeProjectile(start_pos[0], start_pos[1], path, self.tilemap, self.player.asset_manager, owner=attacker)
            self.projectiles.append(projectile)
            # Slime self-damage on actual shot
            if attacker is not None and hasattr(attacker, 'anim_name') and 'slime' in getattr(attacker, 'anim_name', ''):
                attacker.hp -= 1
                if attacker.hp <= 0 and attacker in self.enemies:
                    ax, ay = attacker.x, attacker.y
                    self.vfx_manager.add_particles(ax * TILE_SIZE + TILE_SIZE / 2, ay * TILE_SIZE + TILE_SIZE / 2, 8, 20)
                    self.enemies.remove(attacker)
        elif telegraph.get('type') == 'ranged':
            start_pos = telegraph['start']
            target_pos = telegraph['pos']
            attacker = telegraph.get('attacker')
            projectile = SlimeProjectile(start_pos[0], start_pos[1], [target_pos], self.tilemap, self.player.asset_manager, owner=attacker)
            self.projectiles.append(projectile)
            # Self-damage for ranged attackers if applicable (none currently besides slime)
            if attacker is not None and hasattr(attacker, 'anim_name') and 'slime' in getattr(attacker, 'anim_name', ''):
                attacker.hp -= 1
                if attacker.hp <= 0 and attacker in self.enemies:
                    ax, ay = attacker.x, attacker.y
                    self.vfx_manager.add_particles(ax * TILE_SIZE + TILE_SIZE / 2, ay * TILE_SIZE + TILE_SIZE / 2, 8, 20)
                    self.enemies.remove(attacker)
        else:
            target_pos = telegraph['pos']
            attacker = telegraph.get('attacker')

            # Check if player is at the target position
            if self.player.occupies(target_pos[0], target_pos[1]):
                dmg = 1
                self.player.take_damage(dmg)
                # Hate adjust: attacker lowers hate toward player, min 1
                if attacker is not None:
                    ai.adjust_hate_on_hit(attacker, self.player, dmg, self.player)
                self.vfx_manager.add_particles(target_pos[0] * TILE_SIZE + TILE_SIZE / 2, target_pos[1] * TILE_SIZE + TILE_SIZE / 2, 8, 10)
                if self.player.hp <= 0:
                    print("Game Over!")
                    pyxel.quit()

            # Check if any enemy is at the target position
            for enemy in list(self.enemies):
                if enemy.occupies(target_pos[0], target_pos[1]):
                    dmg = 1
                    enemy.take_damage(dmg)
                    # Hate adjust: victim increases hate toward attacker; attacker decreases toward victim
                    if attacker is not None:
                        ai.adjust_hate_on_hit(attacker, enemy, dmg, self.player)
                    self.vfx_manager.add_particles(target_pos[0] * TILE_SIZE + TILE_SIZE / 2, target_pos[1] * TILE_SIZE + TILE_SIZE / 2, 8, 10)

            # Prune dead enemies immediately
            self.enemies = [enemy for enemy in self.enemies if enemy.hp > 0]

            # Trigger spider lunge toward the attacked square (visual bounce)
            if attacker is not None and hasattr(attacker, 'trigger_lunge'):
                attacker.trigger_lunge(target_pos)
                # Hold the queue until the full lunge (forward + linger + retreat) completes
                try:
                    hold = (
                        getattr(attacker, '_lunge_forward', 0)
                        + getattr(attacker, '_lunge_linger', 0)
                        + getattr(attacker, '_lunge_retreat', 0)
                    )
                except Exception:
                    hold = 0
                # Add a couple extra frames for readability
                self.anim_lock_ticks = max(self.anim_lock_ticks, hold + 2)

    def move_enemies(self):
        for enemy in self.enemies:
            enemy.move_towards_player(self.player)

    def resolve_enemy_attacks(self):
        for telegraph in self.telegraphs:
            if telegraph.get('type') == 'bouncing':
                start_pos = telegraph['start']
                path = telegraph['path']
                attacker = telegraph.get('attacker')
                projectile = SlimeProjectile(start_pos[0], start_pos[1], path, self.tilemap, self.player.asset_manager, owner=attacker)
                self.projectiles.append(projectile)
                # Slime self-damage on actual shot
                if attacker is not None and hasattr(attacker, 'anim_name') and 'slime' in getattr(attacker, 'anim_name', ''):
                    attacker.hp -= 1
                    if attacker.hp <= 0 and attacker in self.enemies:
                        ax, ay = attacker.x, attacker.y
                        self.vfx_manager.add_particles(ax * TILE_SIZE + TILE_SIZE / 2, ay * TILE_SIZE + TILE_SIZE / 2, 8, 20)
                        self.enemies.remove(attacker)
            elif telegraph.get('type') == 'ranged':
                start_pos = telegraph['start']
                target_pos = telegraph['pos']
                attacker = telegraph.get('attacker')
                projectile = SlimeProjectile(start_pos[0], start_pos[1], [target_pos], self.tilemap, self.player.asset_manager, owner=attacker)
                self.projectiles.append(projectile)
                # Self-damage for ranged attackers if applicable (none currently besides slime)
                if attacker is not None and hasattr(attacker, 'anim_name') and 'slime' in getattr(attacker, 'anim_name', ''):
                    attacker.hp -= 1
                    if attacker.hp <= 0 and attacker in self.enemies:
                        ax, ay = attacker.x, attacker.y
                        self.vfx_manager.add_particles(ax * TILE_SIZE + TILE_SIZE / 2, ay * TILE_SIZE + TILE_SIZE / 2, 8, 20)
                        self.enemies.remove(attacker)
            else:
                target_pos = telegraph['pos']
                attacker = telegraph.get('attacker')
                
                # Check if player is at the target position
                if self.player.occupies(target_pos[0], target_pos[1]):
                    self.player.take_damage(1)
                    self.vfx_manager.add_particles(target_pos[0] * TILE_SIZE + TILE_SIZE / 2, target_pos[1] * TILE_SIZE + TILE_SIZE / 2, 8, 10)
                    if self.player.hp <= 0:
                        print("Game Over!")
                        pyxel.quit()

                # Check if any enemy is at the target position
                for enemy in self.enemies:
                    if enemy.occupies(target_pos[0], target_pos[1]):
                        enemy.take_damage(1)
                        # Grief: bump attacker to the top of victim's hate list
                        if attacker and hasattr(enemy, 'register_grief'):
                            enemy.register_grief(attacker)
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
                    dmg = 1
                    self.player.take_damage(dmg)
                    if getattr(p, 'owner', None) is not None:
                        ai.adjust_hate_on_hit(p.owner, self.player, dmg, self.player)
                    self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 8, 20)
                    p.path = p.path[:p.segment+1]
                    if self.player.hp <= 0:
                        print("Game Over!")
                        pyxel.quit()
                for enemy in self.enemies:
                    if enemy.occupies(tile_x, tile_y):
                        dmg = 1
                        enemy.take_damage(dmg)
                        if getattr(p, 'owner', None) is not None:
                            ai.adjust_hate_on_hit(p.owner, enemy, dmg, self.player)
                        self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 8, 20)
                        p.path = p.path[:p.segment+1]
        # Immediately prune dead enemies so they "die now" (with VFX already spawned)
        if self.enemies:
            self.enemies = [e for e in self.enemies if e.hp > 0]

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

    def _compute_attack_order_map(self):
        attackers = [t.get('attacker') for t in self.telegraphs if t.get('attacker') is not None]
        attackers_set = set(attackers)
        ordered = [e for e in self.enemy_initiative if e in self.enemies]
        mapping = {}
        idx = 1
        for e in ordered:
            if e in attackers_set:
                mapping[e] = idx
                idx += 1
        self.attack_order_map = mapping

    def draw_attack_order(self):
        if not self.attack_order_map:
            return
        # Clean mapping of dead/removed
        for e in list(self.attack_order_map.keys()):
            if e not in self.enemies or getattr(e, 'hp', 0) <= 0:
                self.attack_order_map.pop(e, None)
        # Determine current attacker to highlight
        current_attacker = None
        if self.current_phase == GamePhase.ENEMY_ATTACK and 0 <= self.attack_index < len(self.attack_queue):
            current_attacker = self.attack_queue[self.attack_index].get('attacker')
        for enemy, order in self.attack_order_map.items():
            bx = enemy.x * TILE_SIZE
            by = enemy.y * TILE_SIZE
            tx = bx + 1
            ty = by + TILE_SIZE - 6
            # Draw a small shadow for readability
            pyxel.text(tx+1, ty+1, str(order), 0)
            if enemy is current_attacker:
                # Highlight border and use a bright number color
                pyxel.rectb(bx, by, TILE_SIZE, TILE_SIZE, 8)
                pyxel.text(tx, ty, str(order), 7)
            else:
                pyxel.text(tx, ty, str(order), 10)
