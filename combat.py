import pyxel
import time
import math
from enum import Enum
from map import PIT, WALL
from entity import SlimeProjectile, Decor
import random
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

        # Visuals for simultaneous attack rendering
        self.attack_renders = []  # snapshot of telegraphs to render on attack frame
        self.attack_render_ticks = 0  # frames to render attack overlay
        self.show_attack_order = False  # hide initiative while resolving simultaneously

        # Decor objects (collision while intact; rubble is passable and temporary)
        self.decor_objects: list[Decor] = []
        self._decor_initialized = False

        # Per-enemy move arrow (briefly shown after each move)
        self.move_arrow = None  # dict with {'start': (x,y), 'end': (x,y)}
        self.move_arrow_ticks = 0

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
        # Keep player idle animation running
        self.player.update_animation()

        self.vfx_manager.update()

        # Decay one-frame (or few-frames) attack overlay
        if self.attack_render_ticks > 0:
            self.attack_render_ticks -= 1
            if self.attack_render_ticks <= 0:
                self.attack_renders = []

        # Decay move arrow timer
        if self.move_arrow_ticks > 0:
            self.move_arrow_ticks -= 1
            if self.move_arrow_ticks <= 0:
                self.move_arrow = None

    def handle_enemy_move_telegraph_phase(self):
        if self.phase_started:
            # On very first round, place random decor on floor tiles
            if not self._decor_initialized:
                self._spawn_random_decor()
                self._decor_initialized = True
            # At round start, decay rubble one step (remove those expired)
            self._decay_rubble_once()
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
                all_entities = [self.player] + self.enemies + self.decor_objects # Create all_entities list
                if action['action'] == 'move':
                    # Move towards an attack position for selected target
                    enemy = action['enemy']
                    old_pos = (enemy.x, enemy.y)
                    enemy.move_towards_target(enemy.current_target, all_entities)
                    new_pos = (enemy.x, enemy.y)
                    if new_pos != old_pos:
                        # Show a brief yellow arrow from old to new
                        self.move_arrow = {'start': old_pos, 'end': new_pos}
                        # Keep it visible for just under one action delay so it disappears before next action
                        self.move_arrow_ticks = max(1, self.action_delay - 1)
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

        all_entities = [self.player] + self.enemies + self.decor_objects # Create all_entities list
        self.player.update(all_entities)
        # End player phase on spacebar or when out of moves
        if pyxel.btnp(pyxel.KEY_SPACE) or getattr(self.player, 'moves_left', 0) <= 0:
            self.phase_complete = True

    def handle_enemy_attack_phase(self):
        # Simultaneous resolution of all telegraphed attacks
        if not self.phase_started:
            # Nothing to do; phase completes immediately after processing
            return

        self.phase_started = False

        # Use all telegraphs from last phase (do not drop dead attackers; their attack still resolves this round)
        telegraphs = list(self.telegraphs)

        # Partition telegraphs into projectile-based and immediate (melee) attacks
        projectile_teles = []
        melee_teles = []
        for t in telegraphs:
            if t.get('type') in ('bouncing', 'ranged'):
                projectile_teles.append(t)
            else:
                melee_teles.append(t)

        # Tally structures shared by projectile and melee resolution
        total_player_dmg = 0
        enemy_dmg = {}
        hate_adjustments = []  # tuples of (attacker, victim, dmg)
        vfx_positions = []
        decor_vfx_positions = []
        max_lunge_hold = 0

        # Resolve all projectiles immediately by computing their first impact; tally damage; also tally self-damage
        self_damage = {}  # attacker -> damage to self (e.g., slime recoil)
        for t in projectile_teles:
            attacker = t.get('attacker')
            # Self-damage for ranged attackers if applicable (e.g., slime)
            if attacker is not None and hasattr(attacker, 'anim_name') and 'slime' in getattr(attacker, 'anim_name', ''):
                self_damage[attacker] = self_damage.get(attacker, 0) + 1

            # Determine the projectile path
            if t.get('type') == 'bouncing':
                path = t['path']
            else:  # 'ranged' single-step
                path = [t['pos']]

            # Simulate first impact along the path and capture cosmetic path
            hit_applied = False
            cosmetic_end_index = -1
            impact_on_decor = False
            for (tile_x, tile_y) in path:
                cosmetic_end_index += 1
                # Bounds and hard obstruction
                if not (0 <= tile_x < MAP_WIDTH and 0 <= tile_y < MAP_HEIGHT):
                    hit_applied = True
                    break
                tile = self.tilemap.tiles[tile_y][tile_x]
                if tile == PIT or tile == WALL:
                    hit_applied = True
                    break

                # Check player first
                if self.player.occupies(tile_x, tile_y):
                    total_player_dmg += 1
                    hate_adjustments.append((attacker, self.player, 1))
                    hit_applied = True
                    break

                # Check enemies
                for enemy in self.enemies:
                    if enemy.occupies(tile_x, tile_y):
                        enemy_dmg[enemy] = enemy_dmg.get(enemy, 0) + 1
                        hate_adjustments.append((attacker, enemy, 1))
                        hit_applied = True
                        break
                if hit_applied:
                    break

                # Check decor (intact only)
                for deco in self.decor_objects:
                    if not deco.is_rubble and deco.occupies(tile_x, tile_y):
                        # Decor will break to rubble
                        # Tally decor breaks separately (converted to rubble after all tallies)
                        enemy_dmg[deco] = enemy_dmg.get(deco, 0) + 1  # reuse map; special-case when applying
                        impact_on_decor = True
                        hit_applied = True
                        break
                if hit_applied:
                    break

            # Spawn a cosmetic projectile to visualize travel up to the impact (or full path if no impact)
            cosmetic_path = path if not hit_applied else path[:cosmetic_end_index+1]
            if cosmetic_path:
                start_pos = t['start']
                proj = SlimeProjectile(start_pos[0], start_pos[1], cosmetic_path, self.tilemap, self.player.asset_manager, owner=attacker, cosmetic=True)
                # Mark whether this cosmetic projectile ended on decor
                setattr(proj, 'impact_on_decor', impact_on_decor)
                self.projectiles.append(proj)

        # Compute melee hits simultaneously against snapshot of positions
        for t in melee_teles:
            attacker = t.get('attacker')
            target_pos = t.get('pos')

            # Compute dynamic target for directional melee (e.g., spider)
            if t.get('type') == 'melee_dir':
                # Determine cardinal direction toward current hate target at attack time
                dx = 1
                dy = 0
                if attacker is not None:
                    target_ent = getattr(attacker, 'current_target', None)
                    if target_ent is None or getattr(target_ent, 'hp', 0) <= 0:
                        # No valid hate target: skip this attack
                        continue
                    pdx = target_ent.x - attacker.x
                    pdy = target_ent.y - attacker.y
                    if abs(pdx) >= abs(pdy):
                        dx = 1 if pdx > 0 else -1 if pdx < 0 else 0
                        dy = 0
                    else:
                        dy = 1 if pdy > 0 else -1 if pdy < 0 else 0
                        dx = 0
                target_pos = (attacker.x + dx, attacker.y + dy) if attacker is not None else target_pos

            # If no valid target position determined, skip
            if target_pos is None:
                continue

            # Player hit check
            if self.player.occupies(target_pos[0], target_pos[1]):
                total_player_dmg += 1
                hate_adjustments.append((attacker, self.player, 1))
                vfx_positions.append((target_pos[0], target_pos[1]))

            # Enemy hit checks (do not remove yet; apply after tally)
            for enemy in self.enemies:
                if enemy.occupies(target_pos[0], target_pos[1]):
                    enemy_dmg[enemy] = enemy_dmg.get(enemy, 0) + 1
                    hate_adjustments.append((attacker, enemy, 1))
                    vfx_positions.append((target_pos[0], target_pos[1]))

            # Decor hit checks (convert to rubble after tally)
            for deco in self.decor_objects:
                if not deco.is_rubble and deco.occupies(target_pos[0], target_pos[1]):
                    enemy_dmg[deco] = enemy_dmg.get(deco, 0) + 1
                    # Melee breaking decor: grey splatter only
                    decor_vfx_positions.append((target_pos[0], target_pos[1]))

            # Trigger lunge animation for melee attackers
            if attacker is not None and hasattr(attacker, 'trigger_lunge'):
                attacker.trigger_lunge(target_pos)
                try:
                    hold = (
                        getattr(attacker, '_lunge_forward', 0)
                        + getattr(attacker, '_lunge_linger', 0)
                        + getattr(attacker, '_lunge_retreat', 0)
                    )
                except Exception:
                    hold = 0
                max_lunge_hold = max(max_lunge_hold, hold + 2)

        # Apply all tallied damage and effects (simultaneous)
        if total_player_dmg > 0:
            self.player.take_damage(total_player_dmg)
            if self.player.hp <= 0:
                print("Game Over!")
                pyxel.quit()

        for victim, dmg in enemy_dmg.items():
            if isinstance(victim, Decor):
                # Convert to rubble if hit
                victim.break_to_rubble()
            else:
                victim.take_damage(dmg)

        # Apply any tallied self-damage (e.g., slimes)
        for attacker, dmg in self_damage.items():
            attacker.hp -= dmg
            if attacker.hp <= 0:
                ax, ay = attacker.x, attacker.y
                self.vfx_manager.add_particles(ax * TILE_SIZE + TILE_SIZE / 2, ay * TILE_SIZE + TILE_SIZE / 2, 8, 20)

        # Hate adjustments after damage tally
        for attacker, victim, dmg in hate_adjustments:
            if attacker is not None and dmg > 0:
                ai.adjust_hate_on_hit(attacker, victim, dmg, self.player)

        # Spawn VFX for each impact
        for (vx, vy) in vfx_positions:
            self.vfx_manager.add_particles(vx * TILE_SIZE + TILE_SIZE / 2, vy * TILE_SIZE + TILE_SIZE / 2, 8, 10)
        # Additional decor grey splatter
        for (vx, vy) in decor_vfx_positions:
            self.vfx_manager.add_particles(vx * TILE_SIZE + TILE_SIZE / 2, vy * TILE_SIZE + TILE_SIZE / 2, 6, 12)

        # Prune dead enemies after simultaneous resolution
        if self.enemies:
            self.enemies = [e for e in self.enemies if e.hp > 0]

        # Set lunge lock for readability (does not block projectile resolution)
        if max_lunge_hold > 0:
            self.anim_lock_ticks = max(self.anim_lock_ticks, max_lunge_hold)

        # Take a snapshot for rendering the simultaneous attack burst
        self.attack_renders = telegraphs
        self.attack_render_ticks = 1  # render for this frame only (can be tuned)

        # Clear telegraphs now that attacks have resolved
        self.telegraphs = []

        # No need to go to projectile resolution for these attacks; proceed per default flow
        self.phase_complete = True

    def _spawn_random_decor(self):
        # Choose 3 to 5 random decor names from asset manager
        names = [n for n in getattr(self.player.asset_manager, 'decor_names', []) if n]
        if not names:
            return
        count = random.randint(3, 5)
        # Collect candidate floor tiles not blocked by doors and not occupied by entities
        candidates = []
        for y in range(MAP_HEIGHT):
            for x in range(MAP_WIDTH):
                tile = self.tilemap.tiles[y][x]
                if tile and tile.startswith('floor'):
                    door_info = self.tilemap.tile_states.get((x, y))
                    if door_info and door_info.get('state') == 'closed':
                        continue
                    # Avoid spawning under existing entities or decor
                    occupied = False
                    for ent in [self.player] + self.enemies + self.decor_objects:
                        if ent.occupies(x, y):
                            occupied = True
                            break
                    if not occupied:
                        candidates.append((x, y))
        random.shuffle(candidates)
        spots = candidates[:count]
        for (x, y) in spots:
            sprite = random.choice(names)
            self.decor_objects.append(Decor(x, y, self.tilemap, self.player.asset_manager, sprite_name=sprite))

    def _decay_rubble_once(self):
        if not self.decor_objects:
            return
        keep: list[Decor] = []
        for d in self.decor_objects:
            if d.is_rubble:
                d.rubble_ticks -= 1
                if d.rubble_ticks > 0:
                    keep.append(d)
                else:
                    # rubble disappears
                    pass
            else:
                keep.append(d)
        self.decor_objects = keep

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
                # Cosmetic projectiles: show hit splatter now (only at impact)
                if getattr(p, 'cosmetic', False):
                    # Pink splatter for slime shots
                    if getattr(p, 'owner', None) is not None and hasattr(p.owner, 'anim_name') and 'slime' in getattr(p.owner, 'anim_name', ''):
                        self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 8, 20)
                    # Grey splatter for decor if the impact was decor
                    if getattr(p, 'impact_on_decor', False):
                        self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 6, 16)
                else:
                    # Non-cosmetic (legacy) shots keep previous behavior
                    self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 8, 20)
                if p in self.projectiles:
                    self.projectiles.remove(p)
            elif p.time == p.duration -1:
                tile_x = p.path[p.segment][0]
                tile_y = p.path[p.segment][1]
                
                # Check for wall collision
                if not (0 <= tile_x < MAP_WIDTH and 0 <= tile_y < MAP_HEIGHT):
                    if not getattr(p, 'cosmetic', False):
                        self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 8, 20)
                    if p in self.projectiles:
                        self.projectiles.remove(p)
                        continue

                tile = self.tilemap.tiles[tile_y][tile_x]
                if tile == PIT or tile == WALL:
                    if not getattr(p, 'cosmetic', False):
                        self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 8, 20)
                    if p in self.projectiles:
                        self.projectiles.remove(p)
                        continue

                if not getattr(p, 'cosmetic', False) and self.player.occupies(tile_x, tile_y):
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
                        if not getattr(p, 'cosmetic', False):
                            dmg = 1
                            enemy.take_damage(dmg)
                            if getattr(p, 'owner', None) is not None:
                                ai.adjust_hate_on_hit(p.owner, enemy, dmg, self.player)
                            self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 8, 20)
                            p.path = p.path[:p.segment+1]
                # Decor breaks to rubble on projectile hit
                for deco in self.decor_objects:
                    if not deco.is_rubble and deco.occupies(tile_x, tile_y):
                        if not getattr(p, 'cosmetic', False):
                            deco.break_to_rubble()
                            # Grey splatter for decor
                            self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 6, 20)
                            # If the projectile owner is a slime, also add pink splatter
                            if getattr(p, 'owner', None) is not None and hasattr(p.owner, 'anim_name') and 'slime' in getattr(p.owner, 'anim_name', ''):
                                self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 8, 12)
                            p.path = p.path[:p.segment+1]
        # Immediately prune dead enemies so they "die now" (with VFX already spawned)
        if self.enemies:
            self.enemies = [e for e in self.enemies if e.hp > 0]

        if not self.projectiles:
            self.phase_complete = True

    def draw_projectiles(self):
        for p in self.projectiles:
            p.draw()

    def draw_decor(self):
        for d in self.decor_objects:
            d.draw()


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
            elif telegraph.get('type') == 'melee_dir':
                start_pos = telegraph['start']
                sx = start_pos[0] * TILE_SIZE + TILE_SIZE // 2
                sy = start_pos[1] * TILE_SIZE + TILE_SIZE // 2
                attacker = telegraph.get('attacker')
                # Aim strictly at attacker's current hate target; if none, do not draw
                target_ent = getattr(attacker, 'current_target', None) if attacker is not None else None
                if target_ent is None:
                    continue
                dx = 1
                dy = 0
                pdx = target_ent.x - attacker.x
                pdy = target_ent.y - attacker.y
                if abs(pdx) >= abs(pdy):
                    dx = 1 if pdx > 0 else -1 if pdx < 0 else 0
                    dy = 0
                else:
                    dy = 1 if pdy > 0 else -1 if pdy < 0 else 0
                    dx = 0
                ex = (start_pos[0] + dx) * TILE_SIZE + TILE_SIZE // 2
                ey = (start_pos[1] + dy) * TILE_SIZE + TILE_SIZE // 2
                pyxel.line(sx, sy, ex, ey, 8)
                pyxel.circ(ex, ey, 2, 8)
            else:
                start_pos = telegraph['start']
                end_pos = telegraph['pos']
                start_x = start_pos[0] * TILE_SIZE + TILE_SIZE // 2
                start_y = start_pos[1] * TILE_SIZE + TILE_SIZE // 2
                end_x = end_pos[0] * TILE_SIZE + TILE_SIZE // 2
                end_y = end_pos[1] * TILE_SIZE + TILE_SIZE // 2
                pyxel.line(start_x, start_y, end_x, end_y, 8)
                pyxel.circ(end_x, end_y, 2, 8)

    def draw_attack_renders(self):
        # Draw the simultaneous attack overlay (short-lived)
        if not self.attack_renders:
            return
        for telegraph in self.attack_renders:
            if telegraph.get('type') == 'bouncing':
                start_pos = telegraph['start']
                path = telegraph['path']
                if path:
                    start_x = start_pos[0] * TILE_SIZE + TILE_SIZE // 2
                    start_y = start_pos[1] * TILE_SIZE + TILE_SIZE // 2
                    end_x = path[-1][0] * TILE_SIZE + TILE_SIZE // 2
                    end_y = path[-1][1] * TILE_SIZE + TILE_SIZE // 2
                    pyxel.line(start_x, start_y, end_x, end_y, 7)
                for pos in path:
                    x = pos[0] * TILE_SIZE + TILE_SIZE // 2
                    y = pos[1] * TILE_SIZE + TILE_SIZE // 2
                    pyxel.circ(x, y, 2, 7)
            elif telegraph.get('type') == 'melee_dir':
                start_pos = telegraph['start']
                sx = start_pos[0] * TILE_SIZE + TILE_SIZE // 2
                sy = start_pos[1] * TILE_SIZE + TILE_SIZE // 2
                attacker = telegraph.get('attacker')
                # Aim strictly at attacker's current hate target; if none, do not draw
                target_ent = getattr(attacker, 'current_target', None) if attacker is not None else None
                if target_ent is None:
                    continue
                dx = 1
                dy = 0
                pdx = target_ent.x - attacker.x
                pdy = target_ent.y - attacker.y
                if abs(pdx) >= abs(pdy):
                    dx = 1 if pdx > 0 else -1 if pdx < 0 else 0
                    dy = 0
                else:
                    dy = 1 if pdy > 0 else -1 if pdy < 0 else 0
                    dx = 0
                ex = (start_pos[0] + dx) * TILE_SIZE + TILE_SIZE // 2
                ey = (start_pos[1] + dy) * TILE_SIZE + TILE_SIZE // 2
                pyxel.line(sx, sy, ex, ey, 7)
                pyxel.circ(ex, ey, 2, 7)
            else:
                start_pos = telegraph['start']
                end_pos = telegraph['pos']

                start_x = start_pos[0] * TILE_SIZE + TILE_SIZE // 2
                start_y = start_pos[1] * TILE_SIZE + TILE_SIZE // 2
                end_x = end_pos[0] * TILE_SIZE + TILE_SIZE // 2
                end_y = end_pos[1] * TILE_SIZE + TILE_SIZE // 2

                # Brighter color to indicate the actual attack burst
                pyxel.line(start_x, start_y, end_x, end_y, 7)
                pyxel.circ(end_x, end_y, 2, 7)

    def draw_move_arrow(self):
        # Draw a brief yellow arrow from old to new enemy position
        if not self.move_arrow:
            return
        sx, sy = self.move_arrow['start']
        ex, ey = self.move_arrow['end']
        sx = sx * TILE_SIZE + TILE_SIZE // 2
        sy = sy * TILE_SIZE + TILE_SIZE // 2
        ex = ex * TILE_SIZE + TILE_SIZE // 2
        ey = ey * TILE_SIZE + TILE_SIZE // 2
        color = 10  # yellow
        pyxel.line(sx, sy, ex, ey, color)
        # Arrowhead at the end pointing along movement direction
        dx = ex - sx
        dy = ey - sy
        length = math.hypot(dx, dy) or 1.0
        ndx = dx / length
        ndy = dy / length
        # Perpendicular vector
        px = -ndy
        py = ndx
        head_len = 6  # pixels
        head_w = 3    # pixels
        bx = ex - int(ndx * head_len)
        by = ey - int(ndy * head_len)
        lx = int(bx + px * head_w)
        ly = int(by + py * head_w)
        rx = int(bx - px * head_w)
        ry = int(by - py * head_w)
        pyxel.line(ex, ey, lx, ly, color)
        pyxel.line(ex, ey, rx, ry, color)

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
        # Initiative UI hidden while using simultaneous resolution
        if not self.show_attack_order:
            return
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
