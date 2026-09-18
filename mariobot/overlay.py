"""Side panel: the words Jev saw and the typed answers it returned. Labels are question ids and option names."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCALE = 2
PANEL_W = 400
BG, INK, MUTED, RULE, RED, BAR_BG = (255, 255, 255), (17, 17, 17), (120, 120, 120), (225, 225, 225), (227, 6, 19), (238, 238, 238)


def _font(size, mono=False):
    for path in (["/System/Library/Fonts/Menlo.ttc"] if mono else ["/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Helvetica.ttc"]):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


F_H, F_B, F_S, F_M = _font(15), _font(13), _font(11), _font(12, mono=True)


def _wrap(text, n):
    words, lines, cur = str(text).split(), [], ""
    for wd in words:
        if len(cur) + len(wd) + 1 > n:
            lines.append(cur); cur = wd
        else:
            cur = (cur + " " + wd).strip()
    if cur: lines.append(cur)
    return lines


class Panel:
    def __init__(self, frame_h, frame_w):
        self.gw, self.gh = frame_w * SCALE, frame_h * SCALE
        self.w, self.h = self.gw + PANEL_W, self.gh

    def _bar(self, d, x, y, w, frac, label, value, strong=False):
        d.text((x, y), label, font=F_B, fill=INK if strong else MUTED)
        d.text((x + w, y), value, font=F_M, fill=INK, anchor="ra")
        y += 17
        d.rectangle([x, y, x + w, y + 5], fill=BAR_BG)
        d.rectangle([x, y, x + int(w * max(0.0, min(1.0, frac))), y + 5], fill=RED if strong else (170, 170, 170))
        return y + 12

    def render(self, frame_rgb, dec, stats):
        canvas = Image.new("RGB", (self.w, self.h), BG)
        game = Image.fromarray(frame_rgb).resize((self.gw, self.gh), Image.NEAREST)
        canvas.paste(game, (0, 0))
        d = ImageDraw.Draw(canvas)
        x, y, w = self.gw + 18, 14, PANEL_W - 36
        d.text((x, y), stats.get("model", "jev"), font=F_H, fill=INK)
        d.text((x + w, y + 1), f"decision {stats.get('decisions', 0)}", font=F_M, fill=MUTED, anchor="ra"); y += 24
        d.text((x, y), f"{stats.get('latency_ms', 0):.0f} ms   {stats.get('input_tokens', 0)} tok   ${stats.get('cost', 0):.4f} total", font=F_M, fill=MUTED); y += 20
        d.line([x, y, x + w, y], fill=RULE); y += 10
        if dec:
            a = dec["answers"]
            lv = int(round(a["danger"]))
            y = self._bar(d, x, y, w, a["danger"] / 2.0, "danger", f"{a['danger']:.2f}  conf {a['danger_conf']:.2f}", strong=a["danger"] >= 1.5)
            d.text((x, y - 4), dec["danger_legend"][lv][:60], font=F_S, fill=MUTED); y += 14
            d.text((x, y), "move", font=F_B, fill=MUTED); d.text((x + w, y), f"conf {a['move_conf']:.2f}", font=F_M, fill=INK, anchor="ra"); y += 18
            for opt, p in sorted(a["move_probs"].items(), key=lambda kv: -kv[1]):
                chosen = opt == a["move"]
                d.text((x + 4, y), opt, font=F_M, fill=INK if chosen else MUTED)
                d.text((x + w, y), f"{p:.2f}", font=F_M, fill=INK if chosen else MUTED, anchor="ra")
                d.rectangle([x + 4, y + 15, x + 4 + int((w - 8) * p), y + 18], fill=RED if chosen else (200, 200, 200)); y += 20
            y += 2
            y = self._bar(d, x, y, w, a["stomp"], "stomp", f"{a['stomp']:.2f}", strong=a["stomp"] >= 0.5)
            y = self._bar(d, x, y, w, a["full_speed"], "full_speed", f"{a['full_speed']:.2f}", strong=a["full_speed"] >= 0.5)
            y += 2; d.line([x, y, x + w, y], fill=RULE); y += 8
            d.text((x, y), "action", font=F_B, fill=MUTED); y += 18
            d.text((x + 4, y), dec["label"], font=F_H, fill=INK); y += 22
            if dec.get("override"):
                for line in _wrap(dec["override"], 52):
                    d.text((x + 4, y), line, font=F_S, fill=RED); y += 14
            y += 4; d.text((x, y), "ahead", font=F_B, fill=MUTED); y += 16
            ahead = dec.get("ahead", [])
            for line in ([ahead] if isinstance(ahead, str) else ahead)[:4]:
                for sub in _wrap(line, 56)[:2]:
                    d.text((x + 4, y), sub, font=F_S, fill=INK); y += 13
        fy = self.h - 22
        d.line([x, fy - 8, x + w, fy - 8], fill=RULE)
        d.text((x, fy), f"world {stats.get('world', '')}   lives {stats.get('lives', 0)}   deaths {stats.get('deaths', 0)}   x {stats.get('x', 0)}   time {stats.get('time', 0)}", font=F_M, fill=MUTED)
        return np.asarray(canvas)
