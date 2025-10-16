import pyxel
import time
import math
from enum import Enum
from map import PIT, WALL, Tilemap
from entity import SlimeProjectile, Decor, Treasure, DumbSlime, Spider, Spinner
import random
import ai
from vfx import VfxManager
from constants import TILE_SIZE, MAP_WIDTH, MAP_HEIGHT


class _SimEntity:
    def __init__(self, x, y, width, height, tilemap):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.tilemap = tilemap

    def occupies(self, x, y):
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height

    def can_occupy(self, new_x, new_y, all_entities):
        for i in range(self.width):
            for j in range(self.height):
                tx = new_x + i
                ty = new_y + j
                if not (0 <= tx < MAP_WIDTH and 0 <= ty < MAP_HEIGHT):
                    return False
                tile = self.tilemap.tiles[ty][tx]
                if tile == PIT:
                    return False
                if tile == WALL:
                    door_info = self.tilemap.tile_states.get((tx, ty))
                    if not (door_info and door_info.get('state') == 'open'):
                        return False
                door_info = self.tilemap.tile_states.get((tx, ty))
                if door_info and door_info.get('state') == 'closed':
                    return False
                for entity in all_entities:
                    if entity is self:
                        continue
                    if hasattr(entity, 'occupies') and entity.occupies(tx, ty):
                        return False
        return True

    def move(self, dx, dy, all_entities):
        new_x = self.x + dx
        new_y = self.y + dy
        if not self.can_occupy(new_x, new_y, all_entities):
            return False
        self.x = new_x
        self.y = new_y
        return True


class _SimPlayer(_SimEntity):
    def __init__(self, player, tile):
        super().__init__(tile[0], tile[1], player.width, player.height, player.tilemap)


class _SimEnemy(_SimEntity):
    def __init__(self, enemy):
        super().__init__(enemy.x, enemy.y, enemy.width, enemy.height, enemy.tilemap)
        self.move_speed = getattr(enemy, 'move_speed', 1)
        self.hate_map = dict(getattr(enemy, 'hate_map', {}))
        self.current_target = getattr(enemy, 'current_target', None)
        self._source = enemy

    def get_attack_positions(self, target):
        return self._source.get_attack_positions(target)

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
        self.player_reachable_tiles = {}
        self.player_reach_parents = {}
        self.player_reach_origin = (player.x, player.y)
        self._shade_offsets = [(ox, oy) for ox in range(TILE_SIZE) for oy in range(TILE_SIZE) if (ox + oy) % 4 == 0]
        self.room_transition = None
        self.player_dead = False
        self._transition_frames = 10
        self._screen_px_w = MAP_WIDTH * TILE_SIZE
        self._screen_px_h = MAP_HEIGHT * TILE_SIZE
        self.hover_tile = None
        self.hover_timer = 0
        self.hover_predictions = []
        self.hover_delay_frames = 10
        self.post_player_delay_frames = 12
        self.post_player_delay = 0
        self.locked_enemy_plan: list[dict] = []
        self.pending_move_tile: tuple[int, int] | None = None
        self.pending_move_path: list[tuple[int, int]] = []

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

        # Floor treasure pickups
        self.treasure_objects = []
        self.treasure_pending = []  # list of dicts: {'x':x,'y':y,'t':ticks}
        self.treasure_spawn_delay = 5  # frames until treasure appears (half of particle life)

        self._next_phase = {
            GamePhase.ENEMY_MOVE_TELEGRAPH: GamePhase.PLAYER_ACTION,
            GamePhase.PLAYER_ACTION: GamePhase.ENEMY_ATTACK,
            GamePhase.ENEMY_ATTACK: GamePhase.PROJECTILE_RESOLUTION,
            GamePhase.PROJECTILE_RESOLUTION: GamePhase.ENEMY_MOVE_TELEGRAPH, # Loop back
        }

    def update(self):
        if self.player_dead:
            return
        if self.room_transition:
            self._update_room_transition()
            return

        if self.phase_complete and self.current_phase == GamePhase.PLAYER_ACTION and self.post_player_delay > 0:
            self.post_player_delay -= 1
            if self.post_player_delay > 0:
                return
            self.post_player_delay = 0

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

        # Update delayed treasure spawns to appear mid-splatter
        if self.treasure_pending:
            keep_pending = []
            for e in self.treasure_pending:
                e['t'] -= 1
                if e['t'] <= 0:
                    self._spawn_treasure(e['x'], e['y'])
                else:
                    keep_pending.append(e)
            self.treasure_pending = keep_pending

        # Always allow passive pickup when standing on treasure
        self._pickup_treasure_under_player()

        if self.current_phase != GamePhase.PLAYER_ACTION:
            self.player_reachable_tiles = {}
            self._reset_hover_preview()

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
            if not self.locked_enemy_plan:
                self.locked_enemy_plan = self._compute_enemy_plan((self.player.x, self.player.y), apply=True)
            plan = []
            for entry in self.locked_enemy_plan:
                enemy = entry['enemy']
                if enemy in self.enemies and enemy.hp > 0:
                    plan.append(entry)
            self.locked_enemy_plan = plan
            self.enemy_action_queue = []
            for entry in plan:
                self.enemy_action_queue.append({'action': 'move', 'enemy': entry['enemy'], 'path': entry['path']})
                self.enemy_action_queue.append({'action': 'telegraph', 'enemy': entry['enemy'], 'target': entry['target']})
            self.phase_started = False

        self.action_timer += 1
        if self.action_timer >= self.action_delay:
            self.action_timer = 0
            if self.enemy_action_queue:
                action = self.enemy_action_queue.pop(0)
                enemy = action['enemy']
                if enemy not in self.enemies or enemy.hp <= 0:
                    pass
                elif action['action'] == 'move':
                    path = action.get('path') or []
                    old_pos = (enemy.x, enemy.y)
                    for step in path:
                        enemy.x, enemy.y = step
                    new_pos = (enemy.x, enemy.y)
                    if new_pos != old_pos:
                        self.move_arrow = {'start': old_pos, 'end': new_pos}
                        self.move_arrow_ticks = max(1, self.action_delay - 1)
                elif action['action'] == 'telegraph':
                    target = action.get('target')
                    enemy.current_target = target
                    all_entities = [self.player] + self.enemies + self.decor_objects
                    telegraph = enemy.telegraph(target, all_entities)
                    if telegraph:
                        if 'attacker' not in telegraph:
                            telegraph['attacker'] = enemy
                        self.telegraphs.append(telegraph)
            else:
                # Compute attack order numbers based on initiative and who telegraphed
                self._compute_attack_order_map()
                self.phase_complete = True
                self.locked_enemy_plan = []
        # Allow passive pickup if standing on treasure
        self._pickup_treasure_under_player()

    def handle_player_action_phase(self):
        if self.phase_started:
            self.player.reset_moves()
            self.locked_enemy_plan = []
            self._clear_pending_move()
            self.phase_started = False

        all_entities = [self.player] + self.enemies + self.decor_objects
        self._refresh_player_reachability(all_entities)
        self._update_hover_preview()

        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT):
            clicked_tile = self._mouse_tile()
            if clicked_tile == (self.player.x, self.player.y):
                self._finalize_player_turn()
                return
            if clicked_tile and clicked_tile in self.player_reachable_tiles:
                path = self._reconstruct_player_path(clicked_tile)
                if path:
                    if self.pending_move_tile == clicked_tile and self.pending_move_path:
                        start_pos = (self.player.x, self.player.y)
                        if self.player.follow_path(self.pending_move_path, all_entities):
                            steps = len(self.pending_move_path)
                            self._show_move_arrow(start_pos, (self.player.x, self.player.y), steps)
                            self._finalize_player_turn()
                        return
                    self._set_pending_move(clicked_tile, path)
                    return
            if clicked_tile and self._handle_door_click(clicked_tile, all_entities):
                self._reset_hover_preview()
                self._clear_pending_move()
                return

        moved = self.player.try_keyboard_move(all_entities)
        if moved:
            all_entities = [self.player] + self.enemies + self.decor_objects
            self._refresh_player_reachability(all_entities)
            self._clear_pending_move()

        if self._check_keyboard_room_transition():
            self._reset_hover_preview()
            self._clear_pending_move()
            return

        if pyxel.btnp(pyxel.KEY_SPACE) or pyxel.btnp(pyxel.MOUSE_BUTTON_RIGHT) or getattr(self.player, 'moves_left', 0) <= 0:
            self._finalize_player_turn()

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
        decor_break_events = []
        max_lunge_hold = 0

        # Spawn real projectiles; defer damage until projectile impact
        for t in projectile_teles:
            attacker = t.get('attacker')
            # Determine the projectile path
            if t.get('type') == 'bouncing':
                path = t['path']
            else:  # 'ranged' single-step
                path = [t['pos']]
            start_pos = t['start']
            projectile = SlimeProjectile(start_pos[0], start_pos[1], path, self.tilemap, self.player.asset_manager, owner=attacker)
            self.projectiles.append(projectile)
            # Apply shooter self-damage at fire time (e.g., slime recoil)
            if attacker is not None and hasattr(attacker, 'anim_name') and 'slime' in getattr(attacker, 'anim_name', ''):
                attacker.hp -= 1
                if attacker.hp <= 0 and attacker in self.enemies:
                    ax, ay = attacker.x, attacker.y
                    self.vfx_manager.add_particles(ax * TILE_SIZE + TILE_SIZE / 2, ay * TILE_SIZE + TILE_SIZE / 2, 8, 20)
                    self.enemies.remove(attacker)

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

            affected_tiles = []
            if t.get('type') == 'plus':
                affected_tiles = list(t.get('tiles', []))
            else:
                # Single target position
                if target_pos is None:
                    continue
                affected_tiles = [target_pos]

            for (ax, ay) in affected_tiles:
                # Player hit check
                if self.player.occupies(ax, ay):
                    total_player_dmg += 1
                    hate_adjustments.append((attacker, self.player, 1))
                    vfx_positions.append((ax, ay))

                # Enemy hit checks
                for enemy in self.enemies:
                    if enemy.occupies(ax, ay):
                        enemy_dmg[enemy] = enemy_dmg.get(enemy, 0) + 1
                        hate_adjustments.append((attacker, enemy, 1))
                        vfx_positions.append((ax, ay))

                # Decor hit checks
                for deco in self.decor_objects:
                    if not deco.is_rubble and deco.occupies(ax, ay):
                        enemy_dmg[deco] = enemy_dmg.get(deco, 0) + 1
                        decor_vfx_positions.append((ax, ay))
                        decor_break_events.append({'pos': (ax, ay), 'attacker': attacker, 'steps': 0})

            # Trigger lunge/attack animation for melee attackers
            if attacker is not None:
                if hasattr(attacker, 'trigger_lunge') and target_pos is not None:
                    attacker.trigger_lunge(target_pos)
                if hasattr(attacker, 'trigger_attack_anim'):
                    attacker.trigger_attack_anim()
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
        killed_positions = []
        if total_player_dmg > 0:
            self.player.take_damage(total_player_dmg)
            if self.player.hp <= 0:
                self.player.hp = 0
                self._on_player_death()
                return

        for victim, dmg in enemy_dmg.items():
            if isinstance(victim, Decor):
                # Convert to rubble if hit
                victim.break_to_rubble()
            else:
                pre_hp = getattr(victim, 'hp', 0)
                victim.take_damage(dmg)
                if pre_hp > 0 and getattr(victim, 'hp', 0) <= 0:
                    killed_positions.append((victim.x, victim.y))

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

        # Spawn treasure for melee decor breaks
        for ev in decor_break_events:
            pos = ev.get('pos')
            if pos:
                self._queue_treasure(pos[0], pos[1])

        # Spawn treasure immediately for melee kills; projectile kills are handled on impact in update_projectiles
        for (tx, ty) in set(killed_positions):
            self._queue_treasure(tx, ty)

        # Set lunge lock for readability (does not block projectile resolution)
        if max_lunge_hold > 0:
            self.anim_lock_ticks = max(self.anim_lock_ticks, max_lunge_hold)

        # Take a snapshot for rendering the simultaneous attack burst (melee only)
        self.attack_renders = melee_teles
        self.attack_render_ticks = 1  # render for this frame only (can be tuned)

        # Clear telegraphs now that attacks have resolved
        self.telegraphs = []

        # Projectiles will resolve in the next phase
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

    def _generate_room(self, entry_from: str, entry_x: int):
        # Regenerate tilemap
        self.tilemap = Tilemap(self.player.asset_manager)
        # Rebind tilemap on player and existing enemies
        self.player.tilemap = self.tilemap
        for e in self.enemies:
            e.tilemap = self.tilemap
        # Clear state
        self.telegraphs = []
        self.projectiles = []
        self.vfx_manager.particles = []
        self.decor_objects = []
        self.treasure_objects = []
        self.treasure_pending = []
        self.enemy_action_queue = []
        self.attack_queue = []
        self.attack_renders = []
        self.attack_render_ticks = 0
        self.move_arrow = None
        self.move_arrow_ticks = 0
        self.action_timer = 0
        # Position player at opposite side corresponding to entry
        if entry_from == 'top':
            self.player.y = MAP_HEIGHT - 2
            self.player.x = max(1, min(MAP_WIDTH - 2, entry_x))
        elif entry_from == 'bottom':
            self.player.y = 1
            self.player.x = max(1, min(MAP_WIDTH - 2, entry_x))
        # Spawn decor immediately
        self._spawn_random_decor()
        self._decor_initialized = True
        # Spawn enemies (2-3 random)
        self.enemies = []
        enemy_classes = []
        try:
            enemy_classes = [DumbSlime, Spider, Spinner]
        except Exception:
            # Fallback in case some classes are unavailable
            from entity import DumbSlime as _DS, Spider as _Sp
            enemy_classes = [_DS, _Sp]
        num = random.randint(2, 3)
        candidates = []
        for y in range(MAP_HEIGHT):
            for x in range(MAP_WIDTH):
                tile = self.tilemap.tiles[y][x]
                if tile and tile.startswith('floor') and not self.tilemap.is_open_door(x, y):
                    if not self.player.occupies(x, y):
                        candidates.append((x, y))
        random.shuffle(candidates)
        for i in range(min(num, len(candidates))):
            x, y = candidates[i]
            cls = random.choice(enemy_classes)
            self.enemies.append(cls(x, y, self.tilemap, self.player.asset_manager))
        # Reset enemy initiative to the new enemies
        self.enemy_initiative = list(self.enemies)
        # Occasionally free treasure (0-2)
        free = random.randint(0, 2)
        random.shuffle(candidates)
        for i in range(min(free, len(candidates))):
            x, y = candidates[i]
            self._queue_treasure(x, y, delay=0)
        # Reset phase to enemy telegraph of new room
        self.current_phase = GamePhase.ENEMY_MOVE_TELEGRAPH
        self.phase_started = True
        self.phase_complete = False

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
                    self.player.hp = 0
                    self._on_player_death()
                    return

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
                        self.player.hp = 0
                        self._on_player_death()
                        return

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
        if self.player_dead:
            return

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
                        self.player.hp = 0
                        self._on_player_death()
                        return
                for enemy in self.enemies:
                    if enemy.occupies(tile_x, tile_y):
                        if not getattr(p, 'cosmetic', False):
                            dmg = 1
                            pre_hp = enemy.hp
                            enemy.take_damage(dmg)
                            if getattr(p, 'owner', None) is not None:
                                ai.adjust_hate_on_hit(p.owner, enemy, dmg, self.player)
                            self.vfx_manager.add_particles(p.x + TILE_SIZE / 2, p.y + TILE_SIZE / 2, 8, 20)
                            p.path = p.path[:p.segment+1]
                            if pre_hp > 0 and enemy.hp <= 0:
                                self._queue_treasure(enemy.x, enemy.y)
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
                            # treasure scheduling handled in attack phase via decor_break_events
                            # Queue treasure unless the owner slime is dead (self-damage on shot)
                            if not (getattr(p, 'owner', None) is not None and getattr(p.owner, 'hp', 0) <= 0 and 'slime' in getattr(p.owner, 'anim_name', '')):
                                self._queue_treasure(tile_x, tile_y)
                            # Queue treasure to appear after splatter for decor destruction
                            self._queue_treasure(tile_x, tile_y)
        # Immediately prune dead enemies so they "die now" (with VFX already spawned)
        if self.enemies:
            self.enemies = [e for e in self.enemies if e.hp > 0]

        if not self.projectiles:
            self.phase_complete = True

    def draw_projectiles(self):
        for p in self.projectiles:
            p.draw()

    def _draw_arrow_segment(self, start, end, color):
        if start == end:
            return
        sx = start[0] * TILE_SIZE + TILE_SIZE // 2
        sy = start[1] * TILE_SIZE + TILE_SIZE // 2
        ex = end[0] * TILE_SIZE + TILE_SIZE // 2
        ey = end[1] * TILE_SIZE + TILE_SIZE // 2
        pyxel.line(sx, sy, ex, ey, color)
        dx = ex - sx
        dy = ey - sy
        length = math.hypot(dx, dy) or 1.0
        ndx = dx / length
        ndy = dy / length
        px = -ndy
        py = ndx
        head_len = 6
        head_w = 3
        bx = ex - int(ndx * head_len)
        by = ey - int(ndy * head_len)
        lx = int(bx + px * head_w)
        ly = int(by + py * head_w)
        rx = int(bx - px * head_w)
        ry = int(by - py * head_w)
        pyxel.line(ex, ey, lx, ly, color)
        pyxel.line(ex, ey, rx, ry, color)

    def draw_player_reachability_overlay(self):
        if self.player_dead:
            return
        if self.current_phase != GamePhase.PLAYER_ACTION:
            return
        if not self.player_reachable_tiles:
            return
        if self.room_transition:
            return

        top_doors = getattr(self.tilemap, 'top_door_xs', [])
        bottom_doors = getattr(self.tilemap, 'bottom_door_xs', [])
        for y in range(MAP_HEIGHT):
            for x in range(MAP_WIDTH):
                if (x, y) not in self.player_reachable_tiles:
                    if y == 0 and x in top_doors and (x, 1) in self.player_reachable_tiles:
                        continue
                    if y == MAP_HEIGHT - 1 and x in bottom_doors and (x, MAP_HEIGHT - 2) in self.player_reachable_tiles:
                        continue
                    base_x = x * TILE_SIZE
                    base_y = y * TILE_SIZE
                    for ox, oy in self._shade_offsets:
                        color = 2 if ((x + y + ox + oy) % 8) < 4 else 13
                        pyxel.pset(base_x + ox, base_y + oy, color)

    def draw_pending_move_preview(self, player_anim_frame, player_anim_name, asset_manager):
        if self.player_dead or self.room_transition:
            return
        if not self.pending_move_tile or not self.pending_move_path:
            return

        x, y = self.pending_move_tile
        px = x * TILE_SIZE
        py = y * TILE_SIZE
        pyxel.rectb(px, py, TILE_SIZE, TILE_SIZE, 10)

        for step in self.pending_move_path:
            sx, sy = step
            pyxel.rect(sx * TILE_SIZE + 4, sy * TILE_SIZE + 4, TILE_SIZE - 8, TILE_SIZE - 8, 2)

        anim_seq = asset_manager.get_anim(player_anim_name)
        if anim_seq:
            img_bank, u, v = anim_seq[player_anim_frame % len(anim_seq)]
            pyxel.pal(7, 10)
            pyxel.pal(11, 10)
            pyxel.blt(px, py, img_bank, u, v, TILE_SIZE, TILE_SIZE, 0)
            pyxel.pal()

    def draw_room_transition_overlay(self):
        if self.player_dead:
            return
        if not self.room_transition:
            return
        rt = self.room_transition
        if rt['state'] == 'fade_out':
            level = min(1.0, rt['timer'] / self._transition_frames)
        else:
            level = max(0.0, 1.0 - rt['timer'] / self._transition_frames)
        self._draw_fade_overlay(level)

    def _draw_fade_overlay(self, level: float):
        if level <= 0:
            return
        if level >= 1:
            pyxel.rect(0, 0, self._screen_px_w, self._screen_px_h, 0)
            return
        mod = 8
        threshold = max(1, int(level * mod))
        for y in range(self._screen_px_h):
            for x in range(self._screen_px_w):
                if ((x + y) % mod) < threshold:
                    pyxel.pset(x, y, 0)

    def draw_hover_predictions(self):
        if self.player_dead or self.room_transition:
            return
        if not self.hover_predictions:
            return
        for pred in self.hover_predictions:
            start = pred.get('start')
            end = pred.get('end')
            if start and end and start != end:
                self._draw_arrow_segment(start, end, 10)

    def draw_decor(self):
        for d in self.decor_objects:
            d.draw()

    def draw_treasure(self):
        for t in self.treasure_objects:
            t.draw()

    def _spawn_treasure(self, x: int, y: int):
        # Avoid duplicates on the same tile
        for t in self.treasure_objects:
            if t.x == x and t.y == y:
                return
        # Only on walkable floor
        if not (0 <= x < MAP_WIDTH and 0 <= y < MAP_HEIGHT):
            return
        tile = self.tilemap.tiles[y][x]
        if tile == WALL or tile == PIT:
            return
        name_list = getattr(self.player.asset_manager, 'treasure_names', [])
        if not name_list:
            return
        sprite = random.choice(name_list)
        self.treasure_objects.append(Treasure(x, y, self.tilemap, self.player.asset_manager, sprite_name=sprite))

    def _queue_treasure(self, x: int, y: int, delay: int | None = None):
        # Avoid duplicate queued spawns for the same tile at the same moment
        for e in self.treasure_pending:
            if e['x'] == x and e['y'] == y:
                return
        t = self.treasure_spawn_delay if delay is None else delay
        self.treasure_pending.append({'x': x, 'y': y, 't': t})

    def _pickup_treasure_under_player(self):
        keep = []
        picked = 0
        for t in self.treasure_objects:
            if self.player.occupies(t.x, t.y):
                picked += 1
            else:
                keep.append(t)
        if picked > 0:
            self.treasure_objects = keep
            # Increment player's coin count
            coins = getattr(self.player, 'coins', 0)
            setattr(self.player, 'coins', coins + picked)

    def _refresh_player_reachability(self, all_entities):
        reachable, parents = self.player.compute_reachable(all_entities)
        self.player_reachable_tiles = reachable
        self.player_reach_parents = parents
        self.player_reach_origin = (self.player.x, self.player.y)

    def _reconstruct_player_path(self, target_tile):
        if target_tile == self.player_reach_origin:
            return []

        path = []
        current = target_tile
        while current != self.player_reach_origin:
            parent = self.player_reach_parents.get(current)
            if parent is None:
                return []
            path.append(current)
            current = parent
        path.reverse()
        return path

    def _mouse_tile(self):
        tx = pyxel.mouse_x // TILE_SIZE
        ty = pyxel.mouse_y // TILE_SIZE
        if 0 <= tx < MAP_WIDTH and 0 <= ty < MAP_HEIGHT:
            return (tx, ty)
        return None

    def _show_move_arrow(self, start, end, steps=1):
        if start == end:
            return
        duration = max(6, steps * 3)
        self.move_arrow = {'start': start, 'end': end}
        self.move_arrow_ticks = duration

    def _reset_hover_preview(self):
        self.hover_tile = None
        self.hover_timer = 0
        self.hover_predictions = []

    def _set_pending_move(self, tile, path):
        self.pending_move_tile = tile
        self.pending_move_path = list(path)

    def _clear_pending_move(self):
        self.pending_move_tile = None
        self.pending_move_path = []

    def _update_hover_preview(self):
        if self.player_dead or self.room_transition:
            self._reset_hover_preview()
            return

        tile = self._mouse_tile()
        if not tile or tile == (self.player.x, self.player.y):
            self._reset_hover_preview()
            return

        if tile != self.hover_tile:
            self.hover_tile = tile
            self.hover_timer = 0
        else:
            self.hover_timer += 1

        if tile not in self.player_reachable_tiles:
            self.hover_predictions = []
            return

        if self.hover_timer >= self.hover_delay_frames:
            self.hover_predictions = self._compute_enemy_hover_predictions(tile)
        else:
            self.hover_predictions = []

    def _compute_enemy_plan(self, player_tile, apply: bool = False):
        alive_enemies = [enemy for enemy in self.enemies if enemy.hp > 0]
        if not alive_enemies:
            return []

        sim_player = _SimPlayer(self.player, player_tile)
        sim_map: dict = {}
        sim_enemies = []
        for enemy in alive_enemies:
            sim = _SimEnemy(enemy)
            sim_enemies.append(sim)
            sim_map[enemy] = sim

        rev_map = {sim: enemy for enemy, sim in sim_map.items()}

        sim_ordered = []
        ordered = [e for e in self.enemy_initiative if e in alive_enemies]
        if not ordered:
            ordered = list(alive_enemies)
        for enemy in ordered:
            sim_ordered.append(sim_map[enemy])

        sim_all_entities = [sim_player] + sim_enemies + list(self.decor_objects)

        for sim_enemy in sim_enemies:
            ai.init_ai(sim_enemy, sim_player, sim_enemies)

        for sim_enemy in sim_ordered:
            ai.begin_turn(sim_enemy, sim_player, sim_enemies, sim_ordered)

        plan = []
        for enemy in ordered:
            sim_enemy = sim_map[enemy]
            start_pos = (enemy.x, enemy.y)
            target_sim = sim_enemy.current_target or sim_player
            if target_sim is sim_player:
                target_actual = self.player
            else:
                target_actual = rev_map.get(target_sim, self.player)

            path = ai.find_closest_attack_position(sim_enemy, target_sim, sim_all_entities)
            travel_steps = []
            if path and len(path) > 1:
                steps = min(sim_enemy.move_speed, len(path) - 1)
                for idx in range(1, steps + 1):
                    step = path[idx]
                    travel_steps.append(step)
                    sim_enemy.move(step[0] - sim_enemy.x, step[1] - sim_enemy.y, sim_all_entities)
            final_pos = (sim_enemy.x, sim_enemy.y)

            plan.append({
                'enemy': enemy,
                'start': start_pos,
                'path': travel_steps,
                'final': final_pos,
                'target': target_actual,
                'hate_map': dict(sim_enemy.hate_map),
            })

        if apply:
            for entry in plan:
                enemy = entry['enemy']
                enemy.current_target = entry['target']
                enemy.hate_map = dict(entry['hate_map'])
            for enemy in self.enemies:
                if enemy not in alive_enemies:
                    enemy.current_target = None
        return plan

    def _lock_enemy_plan(self):
        self.locked_enemy_plan = self._compute_enemy_plan((self.player.x, self.player.y), apply=True)

    def _finalize_player_turn(self):
        if self.phase_complete:
            return
        self.phase_complete = True
        self.post_player_delay = self.post_player_delay_frames
        self._reset_hover_preview()
        self._clear_pending_move()
        self._lock_enemy_plan()

    def _compute_enemy_hover_predictions(self, target_tile):
        plan = self._compute_enemy_plan(target_tile, apply=False)
        predictions = []
        for entry in plan:
            start = entry['start']
            path = entry['path']
            end = path[-1] if path else start
            if end != start:
                predictions.append({'start': start, 'end': end})
        return predictions

    def _start_room_transition(self, entry_from, door_x):
        self.room_transition = {
            'state': 'fade_out',
            'timer': 0,
            'entry_from': entry_from,
            'door_x': door_x,
        }
        self.player_reachable_tiles = {}
        self.player_reach_parents = {}
        self._reset_hover_preview()
        self.locked_enemy_plan = []

    def _update_room_transition(self):
        if not self.room_transition:
            return
        rt = self.room_transition
        rt['timer'] += 1
        if rt['state'] == 'fade_out':
            if rt['timer'] >= self._transition_frames:
                entry_from = rt['entry_from']
                door_x = rt['door_x']
                self._generate_room(entry_from, door_x)
                self.room_transition = {
                    'state': 'fade_in',
                    'timer': 0,
                    'entry_from': entry_from,
                    'door_x': door_x,
                }
        elif rt['state'] == 'fade_in':
            if rt['timer'] >= self._transition_frames:
                self.room_transition = None

    def _on_player_death(self):
        if self.player_dead:
            return
        self.player_dead = True
        self.room_transition = None
        self.move_arrow = None
        self.move_arrow_ticks = 0
        self.attack_renders = []
        self.projectiles = []
        self.telegraphs = []
        self.enemy_action_queue = []
        self.attack_queue = []
        self._reset_hover_preview()
        self.locked_enemy_plan = []

    def _handle_door_click(self, tile, all_entities):
        x, y = tile
        top_doors = getattr(self.tilemap, 'top_door_xs', [])
        bottom_doors = getattr(self.tilemap, 'bottom_door_xs', [])

        if y == 0 and x in top_doors:
            return self._approach_door_and_enter('top', x, (x, 1), all_entities)

        if y == MAP_HEIGHT - 1 and x in bottom_doors:
            return self._approach_door_and_enter('bottom', x, (x, MAP_HEIGHT - 2), all_entities)

        return False

    def _approach_door_and_enter(self, entry_from, door_x, entry_tile, all_entities):
        if self.room_transition:
            return False
        if (self.player.x, self.player.y) != entry_tile:
            start_pos = (self.player.x, self.player.y)
            if entry_tile not in self.player_reachable_tiles:
                return False
            path = self._reconstruct_player_path(entry_tile)
            if not path and entry_tile != self.player_reach_origin:
                return False
            steps = len(path)
            moved = self.player.follow_path(path, all_entities) if path else True
            if not moved:
                return False
            if path:
                self._show_move_arrow(start_pos, (self.player.x, self.player.y), steps)

        self._start_room_transition(entry_from, door_x)
        return True

    def _check_keyboard_room_transition(self):
        # Top doors: player stands at y==1 and presses up into the top wall
        if self.player.y == 1 and self.player.x in getattr(self.tilemap, 'top_door_xs', []):
            if pyxel.btnp(pyxel.KEY_W):
                self._generate_room('top', self.player.x)
                return True
        # Bottom doors: player stands at y==MAP_HEIGHT-2 and presses down into the bottom wall
        if self.player.y == MAP_HEIGHT - 2 and self.player.x in getattr(self.tilemap, 'bottom_door_xs', []):
            if pyxel.btnp(pyxel.KEY_S):
                self._generate_room('bottom', self.player.x)
                return True
        return False


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
            elif telegraph.get('type') == 'plus':
                start_pos = telegraph['start']
                sx = start_pos[0] * TILE_SIZE + TILE_SIZE // 2
                sy = start_pos[1] * TILE_SIZE + TILE_SIZE // 2
                tiles = telegraph.get('tiles', [])
                for (tx, ty) in tiles:
                    ex = tx * TILE_SIZE + TILE_SIZE // 2
                    ey = ty * TILE_SIZE + TILE_SIZE // 2
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
            elif telegraph.get('type') == 'plus':
                start_pos = telegraph['start']
                sx = start_pos[0] * TILE_SIZE + TILE_SIZE // 2
                sy = start_pos[1] * TILE_SIZE + TILE_SIZE // 2
                tiles = telegraph.get('tiles', [])
                for (tx, ty) in tiles:
                    ex = tx * TILE_SIZE + TILE_SIZE // 2
                    ey = ty * TILE_SIZE + TILE_SIZE // 2
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
        start = self.move_arrow['start']
        end = self.move_arrow['end']
        self._draw_arrow_segment(start, end, 10)

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
