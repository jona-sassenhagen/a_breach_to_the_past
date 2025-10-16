from constants import MAP_WIDTH, MAP_HEIGHT, DOOR

def get_layout():
    layout = [["" for _ in range(MAP_WIDTH)] for _ in range(MAP_HEIGHT)]
    for y in range(MAP_HEIGHT):
        for x in range(MAP_WIDTH):
            # Outer wall border
            if x == 0 and y == 0: layout[y][x] = "top_left_corner"
            elif x == MAP_WIDTH - 1 and y == 0: layout[y][x] = "top_right_corner"
            elif x == 0 and y == MAP_HEIGHT - 1: layout[y][x] = "bottom_left"
            elif x == MAP_WIDTH - 1 and y == MAP_HEIGHT - 1: layout[y][x] = "bottom_right"
            # Doors: handled via tile_states; keep walls continuous in tiles
            elif y == 0: layout[y][x] = "horizontal"
            elif y == MAP_HEIGHT - 1: layout[y][x] = "horizontal"
            elif x == 0: layout[y][x] = "vertical"
            elif x == MAP_WIDTH - 1: layout[y][x] = "vertical"
            # Inner 8x8 floor area
            else:
                # Adjust coordinates for the inner 8x8 grid
                inner_x = x - 1
                inner_y = y - 1
                # Now apply the previous 8x8 floor layout logic
                if inner_x == 0 and inner_y == 0: layout[y][x] = "floor_top_left"
                elif inner_x == 7 and inner_y == 0: layout[y][x] = "floor_top_right"
                elif inner_x == 0 and inner_y == 7: layout[y][x] = "floor_bottom_left"
                elif inner_x == 7 and inner_y == 7: layout[y][x] = "floor_bottom_right"
                elif inner_y == 0: layout[y][x] = "floor_top"
                elif inner_y == 7: layout[y][x] = "floor_bottom"
                elif inner_x == 0: layout[y][x] = "floor_left"
                elif inner_x == 7: layout[y][x] = "floor_right"
                else: layout[y][x] = "floor_center"
    return layout
