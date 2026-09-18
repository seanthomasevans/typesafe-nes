"""Generic NES perception from the sprite list the game keeps in RAM for the PPU (OAM shadow at 0x200):
cluster 8x8 sprites into objects, track them between decisions for velocity, describe them in words."""
from __future__ import annotations

import math

OAM = 0x200


def read_oam(ram, oam=OAM):
    out = []
    for i in range(64):
        y, tile, attr, x = int(ram[oam + 4 * i]), int(ram[oam + 4 * i + 1]), int(ram[oam + 4 * i + 2]), int(ram[oam + 4 * i + 3])
        if y < 0xEF:
            out.append((x, y + 1, tile, attr))
    return out


def cluster(sprites, gap=10):
    """Union sprites whose 8x8 boxes are within `gap` px of each other."""
    n = len(sprites)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i

    for i in range(n):
        xi, yi = sprites[i][0], sprites[i][1]
        for j in range(i + 1, n):
            xj, yj = sprites[j][0], sprites[j][1]
            if abs(xi - xj) <= 8 + gap and abs(yi - yj) <= 8 + gap:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(sprites[i])
    objs = []
    for g in groups.values():
        xs, ys = [s[0] for s in g], [s[1] for s in g]
        objs.append({"x": min(xs), "y": min(ys), "w": max(xs) - min(xs) + 8, "h": max(ys) - min(ys) + 8,
                     "cx": (min(xs) + max(xs) + 8) / 2.0, "cy": (min(ys) + max(ys) + 8) / 2.0,
                     "n": len(g), "tiles": sorted(set(s[2] for s in g))})
    return objs


class Tracker:
    """Match objects between calls by nearest centre and attach velocity in px per frame."""
    def __init__(self):
        self.prev, self.frame_prev, self.next_id = [], 0, 1

    def update(self, objs, frame):
        dt = max(1, frame - self.frame_prev)
        used = set()
        for o in objs:
            best, bd = None, 28.0
            for p in self.prev:
                if p["id"] in used: continue
                d = math.hypot(p["cx"] - o["cx"], p["cy"] - o["cy"])
                if d < bd: best, bd = p, d
            if best is not None:
                used.add(best["id"])
                o["id"] = best["id"]; o["vx"] = (o["cx"] - best["cx"]) / dt; o["vy"] = (o["cy"] - best["cy"]) / dt; o["age"] = best["age"] + 1
            else:
                o["id"] = self.next_id; self.next_id += 1; o["vx"] = o["vy"] = 0.0; o["age"] = 0
        self.prev, self.frame_prev = objs, frame
        return objs


def size_words(o):
    if o["n"] <= 1: return "a small thing"
    if o["w"] <= 16 and o["h"] <= 16: return "a small object"
    if o["w"] <= 24 and o["h"] <= 32: return "a person-sized figure"
    return "a large object"


def where_words(o, px, py, facing_right=True):
    dx = o["cx"] - px
    tiles = round(abs(dx) / 16)
    side = "ahead" if (dx > 0) == facing_right else "behind"
    if tiles == 0: near = f"right on top of the player"
    else: near = f"{tiles} tile{'s' if tiles != 1 else ''} {side}"
    dy = o["cy"] - py
    if dy < -24: lvl = "above"
    elif dy > 24: lvl = "below"
    else: lvl = "at the player's level"
    return near, lvl


def motion_words(o, px, facing_right=True):
    vx, vy = o.get("vx", 0.0), o.get("vy", 0.0)
    toward = (o["cx"] > px and vx < -0.3) or (o["cx"] < px and vx > 0.3)
    speed = math.hypot(vx, vy)
    if speed < 0.3: return "not moving"
    if toward: return "coming at the player fast" if speed > 2.0 else "coming toward the player"
    if vy > 1.0: return "falling"
    if vy < -1.0: return "rising"
    return "moving away" if abs(vx) > 0.3 else "drifting"
