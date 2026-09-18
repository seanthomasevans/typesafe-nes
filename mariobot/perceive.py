"""Turn Mario's RAM facts into a few lines of words for Jev, plus a Meta of numbers for the policy."""
from __future__ import annotations

from dataclasses import dataclass, field

from .emu import Mario, TILE_Y0, ROWS

ENEMY_NAMES = {
    0x00: ("green koopa", True), 0x01: ("red koopa", True), 0x02: ("buzzy beetle", True), 0x03: ("red koopa", True),
    0x04: ("green koopa", True), 0x05: ("hammer brother", True), 0x06: ("goomba", True), 0x07: ("blooper squid", False),
    0x08: ("bullet bill", True), 0x09: ("green paratroopa", True), 0x0A: ("cheep cheep fish", True), 0x0B: ("red cheep cheep fish", True),
    0x0C: ("podoboo fireball", False), 0x0D: ("piranha plant", False), 0x0E: ("green paratroopa", True), 0x0F: ("red paratroopa", True),
    0x10: ("green paratroopa", True), 0x11: ("lakitu", True), 0x12: ("spiny", False), 0x14: ("flying cheep cheep", True),
    0x15: ("bowser flame", False), 0x1B: ("fire bar", False), 0x1C: ("fire bar", False), 0x1D: ("fire bar", False), 0x1E: ("fire bar", False),
    0x24: ("moving platform", None), 0x25: ("moving platform", None), 0x26: ("moving platform", None), 0x27: ("moving platform", None),
    0x28: ("moving platform", None), 0x29: ("moving platform", None), 0x2A: ("moving platform", None), 0x2B: ("moving platform", None),
    0x2D: ("bowser", False), 0x2E: ("power-up item", None), 0x2F: ("vine", None), 0x30: ("flagpole", None), 0x31: ("castle flag", None),
    0x32: ("springboard", None),
}
LOOK_TILES = 9


@dataclass
class Meta:
    v: dict = field(default_factory=dict)
    on_ground: bool = False
    feet_row: int = 0
    gap_at: int | None = None        # tiles ahead where the next gap starts (0 = the next column)
    gap_width: int = 0
    gap_px: int = 0                  # pixels from Mario's x to the gap's first column
    wall_at: int | None = None       # tiles ahead where the next wall/pipe starts
    wall_height: int = 0
    wall_px: int = 0                 # pixels from Mario's x to the wall's first column
    known_tiles: int = 0
    enemies: list = field(default_factory=list)   # dicts with dx (px), dy, name, stompable
    stuck: bool = False
    dead: bool = False
    words: dict = field(default_factory=dict)


def tiles_words(n):
    return "right next to Mario" if n <= 0 else ("1 tile ahead" if n == 1 else f"{n} tiles ahead")


def perceive(m: Mario, hist: dict) -> tuple[dict, Meta]:
    v = m.vars()
    meta = Meta(v=v)
    size_px = 16 if v["size"] == 0 else 32
    feet_y = v["y"] + size_px                     # pixel row just below Mario's sprite
    meta.feet_row = (feet_y - TILE_Y0) // 16
    meta.on_ground = v["float"] == 0 and v["yspeed"] == 0 and v["yview"] == 1
    meta.dead = v["state"] in (0x06, 0x0B) or v["yview"] > 1
    col_x = (v["x"] // 16) * 16 + 8

    # Ground and walls, column by column ahead of Mario.
    known = LOOK_TILES
    for n in range(0, LOOK_TILES + 1):
        cx = col_x + 16 * n
        if not m.page_loaded(cx):
            known = n; break
        # gap: no solid tile from the feet row down to the bottom
        gap = all(m.tile(cx, TILE_Y0 + 16 * r) == 0 for r in range(max(meta.feet_row, 0), ROWS))
        if gap and meta.gap_at is None and n > 0:
            meta.gap_at = n
            meta.gap_px = (cx - 8) - v["x"]
        if meta.gap_at is not None and meta.gap_width == 0 and not gap and n > meta.gap_at:
            meta.gap_width = n - meta.gap_at
        # wall: solid tiles in Mario's body rows
        h = 0
        for r in range(meta.feet_row - 1, -1, -1):
            if m.tile(cx, TILE_Y0 + 16 * r) != 0: h += 1
            else: break
        if h > 0 and meta.wall_at is None and n > 0:
            meta.wall_at, meta.wall_height = n, h
            meta.wall_px = (cx - 8) - v["x"]
    meta.known_tiles = known
    if meta.gap_at is not None and meta.gap_width == 0:
        meta.gap_width = max(1, known - meta.gap_at)

    # Enemies relative to Mario.
    for e in m.enemies():
        name, stomp = ENEMY_NAMES.get(e["type"], (f"unknown thing (type {e['type']})", None))
        dx, dy = e["x"] - v["x"], e["y"] - v["y"]
        meta.enemies.append({"name": name, "stompable": stomp, "dx": dx, "dy": dy, "type": e["type"]})
    meta.enemies.sort(key=lambda e: abs(e["dx"]))

    # Stuck: running right but x not changing.
    xs = hist.setdefault("xs", [])
    xs.append(v["x"]); del xs[:-25]
    meta.stuck = len(xs) >= 25 and max(xs) - min(xs) < 24

    # ---- words -------------------------------------------------------------------
    ahead = []
    for e in meta.enemies:
        if e["dx"] < -80 or e["dx"] > 16 * LOOK_TILES + 8: continue
        tiles = round(e["dx"] / 16)
        where = "behind Mario" if tiles < 0 else tiles_words(tiles)
        level = "above Mario" if e["dy"] < -20 else ("below Mario" if e["dy"] > 20 else "at Mario's level")
        kind = "" if e["stompable"] is None else (", can be stomped" if e["stompable"] else ", must NOT be touched or stomped")
        ahead.append(f"{e['name']} {where}, {level}{kind}")
    if meta.gap_at is not None:
        ahead.append(f"a gap in the ground starting {tiles_words(meta.gap_at)}, {meta.gap_width} tile{'s' if meta.gap_width != 1 else ''} wide")
    if meta.wall_at is not None:
        ahead.append(f"a wall or pipe {meta.wall_height} tile{'s' if meta.wall_height != 1 else ''} tall starting {tiles_words(meta.wall_at)}")
    if meta.wall_at is not None and meta.wall_at <= 1 and meta.wall_height >= 4 and v["xspeed"] < 16:
        ahead.append(f"the wall is {meta.wall_height} tiles tall: a standing jump clears only 3, so Mario must back up several tiles and jump at full running speed")
    if known < LOOK_TILES:
        ahead.append(f"beyond {known} tiles ahead the level is not loaded yet")
    if not ahead:
        ahead = "clear ground for at least 9 tiles, no enemies"

    if v["xspeed"] > 20: moving = "running right fast"
    elif v["xspeed"] > 0: moving = "moving right"
    elif v["xspeed"] < 0: moving = "moving left"
    else: moving = "standing still"
    words = {
        "mario": {
            "size": ["small", "big", "big with fire flower"][min(v["size"], 2)],
            "footing": "on the ground" if meta.on_ground else "in the air",
            "moving": moving,
            "lives": v["lives"], "time_left": v["time"], "world": f"{v['world']}-{v['stage']}",
        },
        "ahead": ahead,
        "stuck": "yes, Mario is pressed against something and not moving; a jump from here goes straight up, he needs to back up first" if meta.stuck else "no",
        "recent_moves": hist.get("moves", [])[-4:] or "none yet",
    }
    meta.words = words
    return words, meta
