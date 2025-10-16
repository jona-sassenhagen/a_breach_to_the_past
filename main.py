
import os
from typing import Tuple

try:
    from PIL import Image
except Exception:  # Pillow optional
    Image = None

import pyxel
import time
from asset_manager import AssetManager
from map import Tilemap
from entity import Player, DumbSlime, Spider, Spinner
from combat import CombatManager
from constants import TILE_SIZE

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
        if self.combat_manager is None:
            self.reset_world()
            return

        self.combat_manager.update()
        self.enemies = self.combat_manager.enemies
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

    def reset_world(self):
        if self.asset_manager is None:
            self.asset_manager = AssetManager()
        self.tilemap = Tilemap(self.asset_manager)
        start_x = getattr(self.tilemap, 'top_door_xs', [1])[0]
        self.player = Player(start_x, 1, self.tilemap, self.asset_manager)
        enemies = [
            DumbSlime(7, 6, self.tilemap, self.asset_manager),   # Dumb slime
            Spider(6, 2, self.tilemap, self.asset_manager),
            Spinner(3, 6, self.tilemap, self.asset_manager)
        ]
        self.enemies = enemies
        self.combat_manager = CombatManager(self.player, self.enemies, self.tilemap)

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

    def draw_death_screen(self):
        pyxel.rect(0, 0, 160, 160, 0)
        pyxel.text(20, 60, "You died a gruseome death", 7)
        pyxel.text(38, 80, "Click to play again", 7)
        y = 105
        pyxel.text(20, y, "Credits:", 7)
        y += 10
        for line in self.credits:
            pyxel.text(20, y, line, 7)
            y += 10

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

App()
