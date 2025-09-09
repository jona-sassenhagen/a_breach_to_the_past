
import pyxel
import time
from asset_manager import AssetManager
from map import Tilemap
from entity import Player, DumbSlime, Spider
from combat import CombatManager
from constants import TILE_SIZE

class App:
    def __init__(self):
        pyxel.init(160, 160, title="Legends of the Breach")
        self.asset_manager = AssetManager()
        self.tilemap = Tilemap(self.asset_manager)
        self.player = Player(4, 4, self.tilemap, self.asset_manager)
        self.enemies = [
            DumbSlime(7, 6, self.tilemap, self.asset_manager),   # Dumb slime
            Spider(6, 2, self.tilemap, self.asset_manager)
        ]
        self.combat_manager = CombatManager(self.player, self.enemies, self.tilemap)
        pyxel.run(self.update, self.draw)

    def update(self):
        if pyxel.btnp(pyxel.KEY_Q):
            pyxel.quit()
        
        self.combat_manager.update()
        self.enemies = self.combat_manager.enemies
        time.sleep(0.05)

    def draw(self):
        pyxel.cls(0)
        self.tilemap.draw()
        self.player.draw()
        for enemy in self.enemies:
            enemy.draw()
        self.combat_manager.draw_telegraphs()
        self.combat_manager.draw_projectiles()
        self.combat_manager.vfx_manager.draw()
        # Draw attack order numbers last for visibility across all phases
        self.combat_manager.draw_attack_order()
        self.draw_ui()

    def draw_ui(self):
        phase_text = str(self.combat_manager.current_phase.name).replace('_', ' ').title()
        pyxel.text(80, 5, phase_text, 7)

        self.draw_hp_bar(self.player.x, self.player.y, self.player.hp)

        for enemy in self.enemies:
            self.draw_hp_bar(enemy.x, enemy.y, enemy.hp)

    def draw_hp_bar(self, unit_x, unit_y, hp):
        for i in range(hp):
            draw_x = unit_x * TILE_SIZE + i * 3
            draw_y = unit_y * TILE_SIZE
            pyxel.rect(draw_x, draw_y, 2, 2, 8)

App()
