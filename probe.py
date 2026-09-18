"""Scripted run (no Jev): run right, jump periodically, print what perception says. Validates RAM reading."""
import json, sys
from PIL import Image
from mariobot.emu import Mario, TILE_Y0
from mariobot.perceive import perceive

m = Mario(); hist = {}
v = m.vars(); print("start:", v)
# ground check: first solid row at/below Mario's feet in his column
feet_row = (v["y"] + 16 - TILE_Y0) // 16
col = (v["x"] // 16) * 16 + 8
print("feet_row", feet_row, "solid rows in Mario's column:", [r for r in range(13) if m.tile(col, TILE_Y0 + 16 * r) != 0])
for i in range(900):
    jump = (i % 90) in range(40, 58)
    m.step(m.act("RIGHT", "B", "A") if jump else m.act("RIGHT", "B"))
    if i % 45 == 0:
        words, meta = perceive(m, hist)
        v = meta.v
        print(f"f{i:4d} x={v['x']:4d} y={v['y']:3d} ground={meta.on_ground} float={v['float']} ys={v['yspeed']} xs={v['xspeed']} dead={meta.dead} | gap={meta.gap_at},{meta.gap_width} wall={meta.wall_at},{meta.wall_height} | {words['ahead'] if isinstance(words['ahead'], str) else words['ahead'][:3]}")
    if i in (300, 600):
        Image.fromarray(m.obs).save(f"refs/probe_f{i}.png")
    if meta.dead if i % 45 == 0 else False:
        print("died at frame", i); break
