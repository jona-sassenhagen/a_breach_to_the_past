
import os
import json
import threading
import urllib.request
import urllib.error
from typing import Tuple

try:
    from PIL import Image
except Exception:  # Pillow optional
    Image = None

import pyxel
import time
from asset_manager import AssetManager
from map import Tilemap
from entity import Player, DumbSlime, Spider, Spinner, Phantom
from combat import CombatManager
from constants import TILE_SIZE

LEADERBOARD_URL = os.getenv("DUNGEON_BREACH_LEADERBOARD", "").strip()
DEFAULT_PLAYER_NAME = os.getenv("DUNGEON_BREACH_PLAYER", "Player")[:12] or "Player"

class App:
    def __init__(self):
        pyxel.init(160, 160, title="DUNGEON BREACH")
        pyxel.mouse(True)
        self.asset_manager = None
        self.tilemap = None
        self.player = None
        self.enemies = []
        self.combat_manager = None
        self.in_title = True
        self.title_image_bank = 2
        self.title_image_loaded, self.title_image_size = self._load_title_image()
        self.credits = self._load_credits()
        self.title_frame_counter = 0
        self.title_input_armed = False
        self.player_name = DEFAULT_PLAYER_NAME
        self.leaderboard: list[dict] = []
        self._leaderboard_lock = threading.Lock()
        self._score_submitted = False
        self._lb_thread_running = False
        self._pending_leaderboard_refresh = False
        if LEADERBOARD_URL:
            self._refresh_leaderboard_async()
        pyxel.run(self.update, self.draw)

    def update(self):
        if pyxel.btnp(pyxel.KEY_Q):
            pyxel.quit()
        if self.in_title:
            self.title_frame_counter += 1
            if self.title_frame_counter >= 10:
                self.title_input_armed = True
            if self.title_input_armed and (pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT) or pyxel.btnp(pyxel.KEY_SPACE)):
                self.in_title = False
                self.reset_world()
            return
        if self.combat_manager and self.combat_manager.player_dead:
            if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT) or pyxel.btnp(pyxel.KEY_SPACE):
                self.reset_world()
            return
        if self.combat_manager and self.combat_manager.victory:
            if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT) or pyxel.btnp(pyxel.KEY_SPACE):
                self.reset_world()
            return
        if self.combat_manager is None:
            self.reset_world()
            return

        self.combat_manager.update()
        # CombatManager may regenerate the active tilemap when advancing rooms;
        # mirror its reference so draws use the latest variant.
        self.tilemap = self.combat_manager.tilemap
        self.enemies = self.combat_manager.enemies
        self._maybe_submit_score()
        time.sleep(0.05)

    def draw(self):
        if self.in_title:
            self.draw_title()
            return
        if self.combat_manager is None:
            return
        pyxel.cls(0)
        self.tilemap.draw()
        self.combat_manager.draw_player_reachability_overlay()
        self.combat_manager.draw_decor()
        self.combat_manager.draw_treasure()
        # Draw telegraphs beneath entities so sprites appear on top
        self.combat_manager.draw_telegraphs()
        self.player.draw()
        self.combat_manager.draw_pending_move_preview(self.player.anim_frame, self.player.anim_name, self.player.asset_manager)
        for enemy in self.enemies:
            enemy.draw()
        self.combat_manager.draw_attack_renders()
        self.combat_manager.draw_hover_predictions()
        self.combat_manager.draw_move_arrow()
        self.combat_manager.draw_projectiles()
        self.combat_manager.vfx_manager.draw()
        # Draw attack order numbers last for visibility across all phases
        self.combat_manager.draw_attack_order()
        self.draw_ui()
        self.combat_manager.draw_room_transition_overlay()
        if self.combat_manager.player_dead:
            self.draw_death_screen()
        elif self.combat_manager.victory:
            self.draw_victory_screen()

    def reset_world(self):
        if self.asset_manager is None:
            self.asset_manager = AssetManager()
        self.tilemap = Tilemap(self.asset_manager)
        start_x = getattr(self.tilemap, 'top_door_xs', [1])[0]
        self.player = Player(start_x, 1, self.tilemap, self.asset_manager)
        setattr(self.player, 'coins', 0)
        self.enemies = []
        self.combat_manager = CombatManager(self.player, self.enemies, self.tilemap)
        self.tilemap = self.combat_manager.tilemap
        self._score_submitted = False

    def _load_title_image(self) -> Tuple[bool, Tuple[int, int]]:
        path = "static_assets/title.png"
        if not os.path.exists(path):
            return False, (0, 0)
        try:
            pyxel.images[self.title_image_bank].load(0, 0, path)
            width = 160
            height = 60
            if Image is not None:
                try:
                    with Image.open(path) as im:
                        width, height = im.size
                except Exception:
                    pass
            return True, (width, height)
        except Exception:
            return False, (0, 0)

    def draw_ui(self):
        phase_text = str(self.combat_manager.current_phase.name).replace('_', ' ').title()
        pyxel.text(80, 5, phase_text, 7)

        self.draw_hp_bar(self.player.x, self.player.y, self.player.hp)

        for enemy in self.enemies:
            self.draw_hp_bar(enemy.x, enemy.y, enemy.hp)

        # Coin counter top-left with drop shadow
        coins = getattr(self.player, 'coins', 0)
        shadow_x, shadow_y = 3, 3
        text_x, text_y = 2, 2
        pyxel.text(shadow_x, shadow_y, f"Coins: {coins}", 0)  # shadow (black)
        pyxel.text(text_x, text_y, f"Coins: {coins}", 7)      # main text (white)

        room = getattr(self.combat_manager, 'room_index', 1)
        total_rooms = getattr(self.combat_manager, 'max_rooms', 1)
        room_text = f"Room {room}/{total_rooms}"
        base_y = 160 - 10
        pyxel.text(3, base_y + 1, room_text, 0)
        pyxel.text(2, base_y, room_text, 7)

        turns = getattr(self.combat_manager, 'turn_count', 0)
        turn_text = f"Turns: {turns}"
        turn_width = len(turn_text) * 4
        turn_x = max(2, 160 - turn_width - 2)
        pyxel.text(turn_x + 1, base_y + 1, turn_text, 0)
        pyxel.text(turn_x, base_y, turn_text, 7)

        self._draw_in_game_leaderboard()

    def draw_title(self):
        pyxel.cls(0)
        text_y = 30
        if self.title_image_loaded:
            width, height = self.title_image_size
            width = max(1, min(160, width))
            height = max(1, min(80, height))
            x = (160 - width) // 2
            y = max(10, (60 - height) // 2)
            pyxel.blt(x, y, self.title_image_bank, 0, 0, width, height, 0)
            text_y = y + height + 8
        else:
            pyxel.text(20, text_y, "DUNGEON BREACH", 7)
            text_y += 16

        lines = [
            "Tap once to preview, twice to move",
            "Collect treasure and stay alive",
            "Monsters telegraph movement and attacks",
            "Coax foes into wrecking furniture",
            " and each other to expose loot",
            "Good luck!",
            "",
            "Click or press space to begin",
        ]
        for line in lines:
            pyxel.text(4, text_y, line, 7)
            text_y += 10

        block_y = text_y + 4
        entries = self._get_leaderboard_snapshot()[:5]
        title = "Top Delvers" if LEADERBOARD_URL else "Leaderboard disabled"
        self._draw_leaderboard_block(4, block_y, entries, title)

    def draw_death_screen(self):
        pyxel.rect(0, 0, 160, 160, 0)
        pyxel.text(20, 60, "You died a gruseome death", 7)
        turns = getattr(self.combat_manager, 'turn_count', 0) if self.combat_manager else 0
        kills = getattr(self.combat_manager, 'monsters_killed', 0) if self.combat_manager else 0
        coins = getattr(self.player, 'coins', 0)
        pyxel.text(32, 72, f"Coins collected: {coins}", 7)
        pyxel.text(32, 82, f"Turns taken: {turns}", 7)
        pyxel.text(32, 92, f"Monsters defeated: {kills}", 7)
        pyxel.text(38, 104, "Click to play again", 7)
        y = 122
        pyxel.text(20, y, "Credits:", 7)
        y += 10
        for line in self.credits:
            pyxel.text(20, y, line, 7)
            y += 10

        entries = self._get_leaderboard_snapshot()[:5]
        self._draw_leaderboard_block(20, y + 4, entries, "Top Delvers")

    def draw_victory_screen(self):
        pyxel.rect(0, 0, 160, 160, 0)
        coins = getattr(self.player, 'coins', 0)
        turns = getattr(self.combat_manager, 'turn_count', 0) if self.combat_manager else 0
        kills = getattr(self.combat_manager, 'monsters_killed', 0) if self.combat_manager else 0
        pyxel.text(20, 30, "You conquered DUNGEON BREACH!", 7)
        pyxel.text(24, 48, f"Coins collected: {coins}", 7)
        pyxel.text(24, 60, f"Turns taken: {turns}", 7)
        pyxel.text(24, 72, f"Monsters defeated: {kills}", 7)
        pyxel.text(32, 92, "Click to play again", 7)
        y = 115
        pyxel.text(20, y, "Credits:", 7)
        y += 10
        for line in self.credits:
            pyxel.text(20, y, line, 7)
            y += 10

        entries = self._get_leaderboard_snapshot()[:5]
        self._draw_leaderboard_block(20, y + 4, entries, "Top Delvers")

    def draw_hp_bar(self, unit_x, unit_y, hp):
        for i in range(hp):
            draw_x = unit_x * TILE_SIZE + i * 3
            draw_y = unit_y * TILE_SIZE
            pyxel.rect(draw_x, draw_y, 2, 2, 8)

    def _load_credits(self):
        path = "credits.txt"
        if not os.path.exists(path):
            return []
        lines = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        lines.append(line)
        except Exception:
            return []
        extras = ["Pyxel by @kitao"]
        return (lines + extras)[:3]

    def _draw_in_game_leaderboard(self):
        if not LEADERBOARD_URL:
            return
        entries = self._get_leaderboard_snapshot()[:3]
        if not entries:
            return
        x = 110
        y = 18
        pyxel.rect(x - 2, y - 2, 50, 36, 1)
        pyxel.text(x, y, "Top:", 7)
        y += 8
        for entry in entries:
            name = str(entry.get('name', ''))[:5]
            coins = entry.get('score', 0)
            pyxel.text(x, y, f"{name:<5} {coins:>3}", 7)
            y += 8

    def _draw_leaderboard_block(self, x: int, y: int, entries: list, title: str):
        pyxel.text(x, y, title, 7)
        y += 8
        if not LEADERBOARD_URL:
            pyxel.text(x, y, "Set DUNGEON_BREACH_LEADERBOARD", 6)
            return
        if not entries:
            pyxel.text(x, y, "(Updating...)", 6)
            return
        for entry in entries:
            name = str(entry.get('name', ''))[:12]
            coins = entry.get('score', 0)
            turns = entry.get('turns')
            line = f"{name:<12} {coins:>3}c"
            if turns is not None:
                line += f" {int(turns):>3}t"
            pyxel.text(x, y, line, 7)
            y += 8

    def _get_leaderboard_snapshot(self):
        with self._leaderboard_lock:
            return list(self.leaderboard)

    def _refresh_leaderboard_async(self):
        if not LEADERBOARD_URL or getattr(self, '_lb_thread_running', False):
            return

        def worker():
            try:
                data = self._fetch_leaderboard()
                if data:
                    with self._leaderboard_lock:
                        self.leaderboard = data
            finally:
                self._lb_thread_running = False

        self._lb_thread_running = True
        threading.Thread(target=worker, daemon=True).start()

    def _fetch_leaderboard(self):
        try:
            req = urllib.request.Request(LEADERBOARD_URL, headers={'Cache-Control': 'no-cache'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = resp.read().decode('utf-8')
                data = json.loads(payload)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
        return []

    def _post_score_async(self, name: str, coins: int, turns: int):
        if not LEADERBOARD_URL:
            return
        payload = json.dumps({
            'name': name,
            'score': int(coins),
            'turns': int(turns),
        }).encode('utf-8')

        def worker():
            try:
                req = urllib.request.Request(
                    LEADERBOARD_URL,
                    data=payload,
                    headers={'Content-Type': 'application/json'}
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass
            finally:
                self._pending_leaderboard_refresh = True

        threading.Thread(target=worker, daemon=True).start()

    def _maybe_submit_score(self):
        if not self.combat_manager:
            return
        if getattr(self, '_pending_leaderboard_refresh', False):
            self._pending_leaderboard_refresh = False
            self._refresh_leaderboard_async()
        if self._score_submitted:
            return
        if not (self.combat_manager.victory or self.combat_manager.player_dead):
            return
        coins = getattr(self.player, 'coins', 0)
        turns = getattr(self.combat_manager, 'turn_count', 0)
        name = (self.player_name or "Player")[:12]
        self._score_submitted = True
        self._post_score_async(name, coins, turns)

App()
