
import pyxel
import time
from asset_manager import AssetManager
from map import Tilemap
from entity import Player, DumbSlime, Spider, Spinner
from combat import CombatManager
from constants import TILE_SIZE

class App:
    def __init__(self):
        pyxel.init(160, 160, title="Legends of the Breach")
        pyxel.mouse(True)
        self.asset_manager = AssetManager()
        self.tilemap = None
        self.player = None
        self.enemies = []
        self.combat_manager = None
        self.reset_world()
        pyxel.run(self.update, self.draw)

    def update(self):
        if pyxel.btnp(pyxel.KEY_Q):
            pyxel.quit()
        if self.combat_manager and self.combat_manager.player_dead:
            if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT) or pyxel.btnp(pyxel.KEY_SPACE):
                self.reset_world()
            return

        self.combat_manager.update()
        self.enemies = self.combat_manager.enemies
        time.sleep(0.05)

    def draw(self):
        pyxel.cls(0)
        self.tilemap.draw()
        self.combat_manager.draw_player_reachability_overlay()
        self.combat_manager.draw_decor()
        self.combat_manager.draw_treasure()
        # Draw telegraphs beneath entities so sprites appear on top
        self.combat_manager.draw_telegraphs()
        self.player.draw()
        for enemy in self.enemies:
            enemy.draw()
        self.combat_manager.draw_attack_renders()
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

    def draw_death_screen(self):
        pyxel.rect(0, 0, 160, 160, 0)
        pyxel.text(20, 70, "You died a gruseome death", 7)
        pyxel.text(38, 90, "Click to play again", 7)

    def draw_hp_bar(self, unit_x, unit_y, hp):
        for i in range(hp):
            draw_x = unit_x * TILE_SIZE + i * 3
            draw_y = unit_y * TILE_SIZE
            pyxel.rect(draw_x, draw_y, 2, 2, 8)

App()
