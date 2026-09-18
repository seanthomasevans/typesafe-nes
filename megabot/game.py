"""Mega Man module for nesbot.runner: perception from the sprite list, three Jev questions, policy."""
from __future__ import annotations

from dataclasses import dataclass, field

from typesafe_sdk import Choice, Noul, Score

from nesbot.sprites import read_oam, cluster, Tracker, size_words, where_words, motion_words
from .emu import MegaMan, FPS, HP_FULL

SLUG, TITLE = "megaman", "Jev plays Mega Man"
DANGER = ["Nothing is close to Mega Man.", "Something is approaching and will need a reaction within a second.", "Something is about to hit Mega Man right now."]
MOVES = {
    "run": "Keep walking right.",
    "jump": "Jump now: over a gap, up onto a ledge, or over an enemy.",
    "climb": "Hold up to climb a ladder Mega Man is touching.",
    "hold": "Stand still and shoot.",
    "back_up": "Step back to the left.",
}
SPEC = [("danger", "score", DANGER), ("move", "choice", None), ("fire", "noul", None)]


@dataclass
class Meta:
    v: dict = field(default_factory=dict)
    things: list = field(default_factory=list)
    stuck: bool = False
    climb_dead: bool = False
    sx: int = 0


class Game(MegaMan):
    def __init__(self):
        super().__init__()
        self.tracker = Tracker()
        self._last_stage = self.vars()["stage"]
        self._last_hp = self.vars()["hp"]

    def perceive(self, hist):
        v = self.vars()
        meta = Meta(v=v)
        sx = v["x"] - v["cam"]; meta.sx = sx
        cx, cy = sx + 8, v["y"] + 12
        objs = [o for o in cluster(read_oam(self.ram())) if o["y"] > 32 and o["x"] >= 32]   # score line and health bar are HUD sprites
        objs = self.tracker.update(objs, self.frame)
        others = [o for o in objs if not (abs(o["cx"] - cx) < 20 and abs(o["cy"] - cy) < 28)]
        others.sort(key=lambda o: abs(o["cx"] - cx))
        meta.things = others[:6]
        xs = hist.setdefault("xs", []); xs.append(v["x"]); del xs[:-15]
        ys = hist.setdefault("ys", []); ys.append(v["y"]); del ys[:-8]
        meta.stuck = len(xs) >= 15 and max(xs) - min(xs) < 6
        moves = hist.get("moves", [])
        climbing = [m for m in moves[-4:] if m.startswith("climb")]
        meta.climb_dead = len(climbing) >= 3 and len(ys) >= 8 and max(ys) - min(ys) < 4
        seen = []
        for o in meta.things[:5]:
            near, lvl = where_words(o, cx, cy)
            seen.append(f"{size_words(o)} {near}, {lvl}, {motion_words(o, cx)}")
        if not seen: seen = "nothing else on screen"
        hp = v["hp"]
        words = {
            "mega_man": {"health": f"{'full' if hp >= HP_FULL else 'hurt' if hp >= HP_FULL // 2 else 'low'} ({hp} of {HP_FULL})", "lives_left": v["lives"], "hit_recently": "yes" if v["iframes"] else "no"},
            "seen": seen,
            "stuck": ("yes, Mega Man has not moved for a while" + ("; holding up did nothing, so there is no ladder here" if meta.climb_dead else "; a wall or a ladder is in the way")) if meta.stuck else "no",
            "recent_moves": hist.get("moves", [])[-4:] or "none yet",
        }
        return words, meta

    def dead(self, meta):
        return meta.v["hp"] == 0 and self._last_hp > 0 or (meta.v["hp"] == 0 and meta.v["y"] == 0)

    def after_death(self):
        n = 0
        for _ in range(FPS * 6):
            self.step(self.act()); n += 1
            if self.vars()["hp"] > 0: break
        if self.vars()["lives"] & 0x80 or self.vars()["hp"] == 0:
            self.reset()
        else:
            self.wait_playable()
        self._last_hp = self.vars()["hp"]
        self.tracker = Tracker()
        return n

    def transition(self, meta):
        self._last_hp = meta.v["hp"]
        st = meta.v["stage"]
        if st != self._last_stage:
            self._last_stage = st
            return f"STAGE CHANGED to {st}"
        return None

    def footer(self, meta):
        v = meta.v
        return f"stage {v['stage']}   x {v['x']}   hp {v['hp']}/{HP_FULL}   lives {v['lives'] & 0x7F}"

    def progress(self, meta):
        return meta.v["x"]


def make_game():
    return Game()


def build_questions(words, meta):
    return {
        "danger": Score(instructions="How urgent is the closest thing in `seen` for Mega Man?", criteria=DANGER),
        "move": Choice(instructions="What should Mega Man do now, using `mega_man`, `seen` and `stuck`? Jump over small things coming at him and when something blocks the way. Climb when stuck after jumping did not help. Hold to shoot something coming at his level. Back up when something is right on top of him.", criteria=MOVES),
        "fire": Noul(instructions="Should Mega Man fire the arm cannon right now?", criteria={"true": "A figure or object in `seen` is ahead at Mega Man's level, or coming toward him.", "false": "Nothing worth shooting is in view."}),
    }


@dataclass
class Ctrl:
    a_hold: int = 0
    a_prev: bool = False
    fire_tick: int = 0
    stuck_tries: int = 0
    mode: str = ""            # "" or "ladder"
    ladder_step: int = 0      # index into the sideways offsets to try
    ladder_phase: str = ""    # "move" | "try" | "climb"
    ladder_x0: int = 0
    ladder_y: int = 0
    ladder_frames: int = 0

LADDER_OFFSETS = [0, -12, 12, -24, 24, -36, 36, -48, 48, -64, 64]


def policy(meta: Meta, a: dict, frames: int, ctrl: Ctrl, act):
    mv, fire = a["move"]["choice"], a["fire"]["noul"] >= 0.5
    override = ""
    x, y = meta.v["x"], meta.v["y"]

    # Ladder search: ladders are background tiles the sprite layer cannot see. When Mega Man is stuck,
    # code tries holding up at a few positions around him and keeps climbing once y starts dropping.
    if ctrl.mode == "ladder":
        ctrl.ladder_frames += frames
        W = "ladder search"
        if ctrl.ladder_frames > 600:
            ctrl.mode = ""
        elif ctrl.ladder_phase == "climb":
            if y < ctrl.ladder_y - 2:
                ctrl.ladder_y = y; ctrl.ladder_frames = 0
                return [act("UP") for _ in range(frames)], "climb", f"{W}: on a ladder, climbing (code)"
            if ctrl.ladder_frames > 40:
                ctrl.mode = ""
                override = f"{W}: reached the top, back to Jev"
            else:
                return [act("UP") for _ in range(frames)], "climb", f"{W}: on a ladder, climbing (code)"
        elif ctrl.ladder_phase == "try":
            if y < ctrl.ladder_y - 2:
                ctrl.ladder_phase, ctrl.ladder_frames = "climb", 0
                return [act("UP") for _ in range(frames)], "climb", f"{W}: found a ladder here, climbing (code)"
            ctrl.ladder_step += 1
            if ctrl.ladder_step >= len(LADDER_OFFSETS):
                ctrl.mode = ""
                override = f"{W}: no ladder within 4 tiles either side, back to Jev"
            else:
                ctrl.ladder_phase = "move"
        if ctrl.mode == "ladder" and ctrl.ladder_phase == "move":
            target = ctrl.ladder_x0 + LADDER_OFFSETS[ctrl.ladder_step]
            ctrl.ladder_move_frames = getattr(ctrl, "ladder_move_frames", 0) + frames
            if abs(x - target) <= 3 or ctrl.ladder_move_frames > 36:
                ctrl.ladder_phase, ctrl.ladder_y, ctrl.ladder_move_frames = "try", y, 0
                return [act("UP") for _ in range(frames)], "climb", f"{W}: trying up at {x - ctrl.ladder_x0:+d}px (code)"
            btn = "RIGHT" if target > x else "LEFT"
            return [act(btn) for _ in range(frames)], "walk", f"{W}: moving to {LADDER_OFFSETS[ctrl.ladder_step]:+d}px (code)"
    if ctrl.mode == "" and meta.stuck and ctrl.stuck_tries >= 2 and not meta.v["iframes"]:
        ctrl.mode, ctrl.ladder_step, ctrl.ladder_phase, ctrl.ladder_x0, ctrl.ladder_y, ctrl.ladder_frames = "ladder", 0, "try", x, y, 0
        ctrl.stuck_tries = 0
        return [act("UP") for _ in range(frames)], "climb", "stuck and jumping did not help: code is searching for a ladder (up here first)"
    if meta.climb_dead and mv == "climb":
        mv, override = ("jump" if ctrl.stuck_tries % 2 == 0 else "back_up"), "holding up changed nothing, no ladder here; code tried " + ("jump" if ctrl.stuck_tries % 2 == 0 else "back_up")
        ctrl.stuck_tries += 1
    elif meta.stuck:
        ctrl.stuck_tries += 1
        if mv in ("run", "hold"):
            mv = "jump" if ctrl.stuck_tries % 4 < 2 else "climb"
            override = f"not moving for a while, code tried {mv}"
    else:
        ctrl.stuck_tries = 0
    plan = []
    for i in range(frames):
        btn = []
        if mv in ("run", "jump"): btn.append("RIGHT")
        if mv == "climb": btn.append("UP")
        if mv == "back_up": btn.append("LEFT")
        if mv == "jump":
            if i == 0 and ctrl.a_prev: pass
            elif i <= 1 and ctrl.a_hold == 0: ctrl.a_hold = 18
        if ctrl.a_hold > 0: btn.append("A"); ctrl.a_hold -= 1
        ctrl.a_prev = "A" in btn
        if fire:
            ctrl.fire_tick += 1
            if ctrl.fire_tick % 6 < 2: btn.append("B")
        plan.append(act(*btn))
    return plan, mv + (" + fire" if fire else ""), override
