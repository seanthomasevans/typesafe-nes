"""Contra module for nesbot.runner: perception from the sprite list, four Jev questions, policy."""
from __future__ import annotations

from dataclasses import dataclass, field

from typesafe_sdk import Choice, Noul, Score

from nesbot.sprites import read_oam, cluster, Tracker, size_words, where_words, motion_words
from .emu import Contra, FPS

SLUG, TITLE = "contra", "Jev plays Contra"
DANGER = ["Nothing is close to the player.", "Something is approaching and will need a reaction within a second.", "Something is about to hit the player right now."]
MOVES = {
    "run": "Keep running right.",
    "jump": "Jump: over a bullet at leg height, over water or a gap, or up onto a ledge above.",
    "prone": "Lie flat on the ground so bullets at chest height pass over.",
    "hold": "Stand still and shoot.",
}
AIMS = {"forward": "Shoot straight ahead.", "up": "Shoot straight up.", "diagonal_up": "Shoot up and ahead.", "diagonal_down": "Shoot down and ahead."}
SPEC = [("danger", "score", DANGER), ("move", "choice", None), ("aim", "choice", None), ("fire", "noul", None)]


@dataclass
class Meta:
    v: dict = field(default_factory=dict)
    things: list = field(default_factory=list)
    stuck: bool = False


class Game(Contra):
    def __init__(self):
        super().__init__()
        self.tracker = Tracker()
        self._last_level = self.vars()["level"]

    def perceive(self, hist):
        v = self.vars()
        meta = Meta(v=v)
        objs = [o for o in cluster(read_oam(self.ram())) if o["y"] > 24]
        objs = self.tracker.update(objs, self.frame)
        others = [o for o in objs if not (abs(o["cx"] - v["px"]) < 20 and abs(o["cy"] - v["py"]) < 40)]
        others.sort(key=lambda o: abs(o["cx"] - v["px"]))
        meta.things = others[:6]
        ps = hist.setdefault("prog", []); ps.append(v["progress"]); del ps[:-15]
        meta.stuck = len(ps) >= 15 and max(ps) - min(ps) < 4 and v["state"] == 1
        seen = []
        for o in meta.things[:5]:
            near, lvl = where_words(o, v["px"], v["py"])
            seen.append(f"{size_words(o)} {near}, {lvl}, {motion_words(o, v['px'])}")
        if not seen: seen = "nothing else on screen"
        footing = "in the air" if v["jump"] else ("in the water" if v["py"] > 200 else "on the ground")
        words = {
            "player": {"footing": footing, "lives_left": v["lives"], "hit_recently": "yes" if v["inv"] else "no"},
            "seen": seen,
            "stuck": "yes, the player has not advanced for a while, something blocks the way" if meta.stuck else "no",
            "recent_moves": hist.get("moves", [])[-4:] or "none yet",
        }
        return words, meta

    def demo(self, meta):
        """The attract demo populates the same RAM bytes; its lives byte reads 98 and there are no medals."""
        return meta.v["lives"] > 9 or not self.in_game()

    def dead(self, meta):
        return bool(meta.v["death"]) or self.demo(meta)

    def after_death(self):
        """Wait out the death animation; on the GAME OVER screen press START on CONTINUE (the default).
        If the attract demo is running instead of a game, power-cycle and start a real game."""
        n = 0
        lives_before = self.vars()["lives"]
        if lives_before > 9 or not self.in_game():
            self.reset()
            self.tracker = Tracker()
            return n
        for _ in range(FPS * 4):
            self.step(self.act()); n += 1
            if self.vars()["death"] == 0 and self.vars()["state"] == 1: break
        if not self.wait_playable(300):
            if lives_before == 0:
                for _ in range(FPS * 3): self.step(self.act()); n += 1
                for _ in range(8): self.step(self.act("START")); n += 1
                self.continues = getattr(self, "continues", 0) + 1
            if not self.wait_playable(900):
                self.reset()
        if not self.in_game() or self.vars()["lives"] > 9:
            self.reset()
        self.tracker = Tracker()
        return n

    def transition(self, meta):
        lv = meta.v["level"]
        if lv != self._last_level:
            self._last_level = lv
            return f"LEVEL {lv} REACHED (finished level {lv})"
        return None

    def footer(self, meta):
        v = meta.v
        return f"level {v['level'] + 1}   screen {v['screen']}   lives {v['lives']}   continues {getattr(self, 'continues', 0)}"

    def progress(self, meta):
        return meta.v["level"] * 10000 + meta.v["progress"]


def make_game():
    return Game()


def build_questions(words, meta):
    return {
        "danger": Score(instructions="How urgent is the closest thing in `seen` for the player?", criteria=DANGER),
        "move": Choice(instructions="What should the player do now, using `player`, `seen` and `stuck`? Jump over small things coming at leg height, over water, and when something blocks the way. Go prone for small things coming at chest height. Hold only to shoot something that is not yet close.", criteria=MOVES),
        "aim": Choice(instructions="Where should the player shoot, using `seen`? Aim at the nearest person-sized figure or large object that is coming toward the player: forward if at the player's level, up or diagonal_up if above, diagonal_down if below.", criteria=AIMS),
        "fire": Noul(instructions="Should the player fire the gun right now?", criteria={"true": "Something in `seen` is ahead or above and worth shooting.", "false": "Nothing worth shooting is in view."}),
    }


@dataclass
class Ctrl:
    a_hold: int = 0
    a_prev: bool = False
    fire_tick: int = 0


def policy(meta: Meta, a: dict, frames: int, ctrl: Ctrl, act):
    mv, aim, fire = a["move"]["choice"], a["aim"]["choice"], a["fire"]["noul"] >= 0.5
    override = ""
    if meta.stuck and mv in ("run", "hold", "prone"):
        mv, override = "jump", "not advancing for a while, code jumped"
    plan = []
    for i in range(frames):
        btn = []
        if mv in ("run", "jump"): btn.append("RIGHT")
        if mv == "prone": btn.append("DOWN")
        if aim in ("up", "diagonal_up") and mv != "prone": btn.append("UP")
        if aim == "diagonal_down" and mv == "run": btn.append("DOWN")
        if mv == "jump":
            if i == 0 and ctrl.a_prev: pass
            elif i <= 1 and ctrl.a_hold == 0: ctrl.a_hold = 12
        if ctrl.a_hold > 0: btn.append("A"); ctrl.a_hold -= 1
        ctrl.a_prev = "A" in btn
        if fire:
            ctrl.fire_tick += 1
            if ctrl.fire_tick % 4 < 2: btn.append("B")
        plan.append(act(*btn))
    label = mv + (f" + fire {aim}" if fire else "")
    return plan, label, override
