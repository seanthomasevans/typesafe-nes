"""Scripted Contra (no Jev): run right, jump and fire on a schedule; print the objects the sprite layer sees,
and draw the clusters on a few frames."""
import sys
from PIL import Image, ImageDraw
from contrabot.emu import Contra, RIGHT, A, B
from nesbot.sprites import read_oam, cluster, Tracker, size_words, where_words, motion_words

c = Contra(); tr = Tracker()
print("start vars:", c.vars())
for i in range(1500):
    btn = RIGHT | (B if i % 8 < 2 else 0) | (A if i % 150 in range(60, 70) else 0)
    c.step(btn)
    if i % 6 == 0:
        v = c.vars()
        objs = [o for o in cluster(read_oam(c.ram())) if o["y"] > 24]
        objs = tr.update(objs, c.frame)
        player = [o for o in objs if abs(o["cx"] - v["px"]) < 20 and abs(o["cy"] - v["py"]) < 40]
        others = [o for o in objs if o not in player]
        if i % 90 == 0:
            desc = [f"{size_words(o)} {where_words(o, v['px'], v['py'])[0]}, {where_words(o, v['px'], v['py'])[1]}, {motion_words(o, v['px'])} tiles={o['tiles'][:4]}" for o in sorted(others, key=lambda o: abs(o['cx'] - v['px']))[:4]]
            print(f"f{i:4d} px={v['px']:3d} py={v['py']:3d} st={v['state']} death={v['death']} prog={v['progress']} | player_clusters={len(player)} others={len(others)} | " + " ; ".join(desc))
        if i in (300, 600, 900, 1200):
            img = Image.fromarray(c.obs).resize((512, 480), Image.NEAREST); d = ImageDraw.Draw(img)
            for o in others: d.rectangle([o["x"]*2, o["y"]*2, (o["x"]+o["w"])*2, (o["y"]+o["h"])*2], outline=(255, 0, 0)); d.text((o["x"]*2, o["y"]*2-10), str(o["tiles"][0]), fill=(255,255,0))
            for o in player: d.rectangle([o["x"]*2, o["y"]*2, (o["x"]+o["w"])*2, (o["y"]+o["h"])*2], outline=(0, 255, 0))
            img.save(f"refs/probe_contra_clusters_{i}.png")
    if c.vars()["death"]:
        print("death flag at frame", i, c.vars()); break
