"""Jev side for Mario: one request per decision with four typed questions, then a policy in code
that turns Jev's intent into precisely timed button presses. Jev decides what (run, jump the next
thing, stomp, wait); code decides the exact takeoff frame and how long to hold the jump."""
from __future__ import annotations

import time
from dataclasses import dataclass

from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

from .perceive import Meta

PRICE_PER_MTOK = 0.042

DANGER_LEVELS = [
    "Nothing threatens Mario for at least 3 tiles ahead.",
    "Something will need a jump soon, 2 to 4 tiles ahead.",
    "Something must be jumped over or avoided right now, within 1 tile.",
]
MOVES = {
    "run": "Keep running right at full speed; nothing needs a jump within 3 tiles.",
    "jump": "Jump over the next gap or wall ahead. Code times the takeoff and the jump height from the gap width or wall height.",
    "stomp": "Jump onto the nearest enemy ahead to stomp it.",
    "wait": "Stop and stand still so an enemy comes closer or passes, or so a piranha plant goes back into its pipe.",
}


def build_questions(words: dict, meta: Meta) -> dict:
    return {
        "move": Choice(
            instructions="What should Mario do next, using `mario` and `ahead`? Choose jump when the nearest thing in `ahead` is a gap or a wall. Choose stomp when the nearest thing is an enemy that can be stomped. Choose run when nothing is within 3 tiles. Choose wait only when the nearest thing is an enemy that must not be touched and it is in the way.",
            criteria=MOVES,
        ),
        "danger": Score(instructions="How urgent is the nearest problem in `ahead`?", criteria=DANGER_LEVELS),
        "stomp": Noul(
            instructions="Should Mario jump onto the nearest enemy in `ahead` to stomp it?",
            criteria={"true": "The nearest enemy ahead can be stomped, is within 4 tiles, and is at Mario's level.",
                      "false": "No enemy is close ahead, or the nearest enemy must not be stomped, or it is above or below Mario."},
        ),
        "full_speed": Noul(
            instructions="Is it safe for Mario to keep running at full speed for the next 3 tiles?",
            criteria={"true": "Nothing in `ahead` is within 3 tiles.", "false": "Something in `ahead` is within 3 tiles and needs care."},
        ),
    }


@dataclass
class Answers:
    move: str
    move_probs: dict
    move_conf: float
    danger: float
    danger_probs: dict
    danger_conf: float
    stomp: float
    full_speed: float
    latency_ms: float
    input_tokens: int
    model: str

    def as_dict(self):
        return self.__dict__


class Brain:
    def __init__(self, model="jev-latest"):
        self.client = TypeSafeClient(model=model)
        self.total_tokens = 0
        self.total_requests = 0

    def close(self):
        self.client.close()

    @property
    def cost_usd(self):
        return self.total_tokens / 1e6 * PRICE_PER_MTOK

    def ask(self, words: dict, meta: Meta) -> Answers:
        t0 = time.time()
        r = self.client.system_one(state=words, questions=build_questions(words, meta))
        ms = (time.time() - t0) * 1000
        self.total_tokens += r.usage.input_tokens
        self.total_requests += 1
        mv, dg = r.choices["move"], r.scores["danger"]
        return Answers(move=mv.choice, move_probs=dict(mv.probabilities), move_conf=mv.confidence,
                       danger=dg.score, danger_probs={str(k): v for k, v in dg.probabilities.items()}, danger_conf=dg.confidence,
                       stomp=r.nouls["stomp"].noul, full_speed=r.nouls["full_speed"].noul,
                       latency_ms=ms, input_tokens=r.usage.input_tokens, model=r.model)


@dataclass
class Ctrl:
    a_hold: int = 0          # frames left to keep holding A (a jump keeps rising while held)
    a_prev: bool = False     # A was down on the last frame (SMB jumps only on a fresh press)
    mode: str = ""           # "" or "runup"
    runup_from: int = 0
    wall_x: int = 0
    wall_h: int = 0
    runup_frames: int = 0
    backup_x: int = 0
    backup_blocked: int = 0
    phase_run: bool = False
    short_runway: bool = False


# Takeoff distance (px before the obstacle's first column) and A-hold frames, by obstacle.
def gap_plan(width):
    if width <= 2: return 4, 14
    if width <= 3: return 6, 22
    if width <= 4: return 8, 28
    return 10, 32


def wall_plan(h):
    if h <= 1: return 12, 8
    if h == 2: return 20, 16
    if h == 3: return 34, 26
    return 52, 32


def _frames(act, ctrl, n, right=True, run=True, jump_now=False, hold=0):
    """Build n frames. jump_now starts a fresh A press (after a release frame if A was down) and holds it
    for `hold` frames in total, carried across decisions in ctrl.a_hold."""
    plan, started = [], False
    for _ in range(n):
        if jump_now and not started:
            if ctrl.a_prev:
                a = False                      # release so the next press registers
            else:
                started, ctrl.a_hold, a = True, hold, True
        else:
            a = ctrl.a_hold > 0
        if a and ctrl.a_hold > 0:
            ctrl.a_hold -= 1
        ctrl.a_prev = a
        buttons = (["RIGHT"] if right else []) + (["B"] if run else []) + (["A"] if a else [])
        plan.append(act(*buttons))
    return plan


def policy(meta: Meta, a: Answers, frames: int, ctrl: Ctrl, act):
    mv, override = a.move, ""
    x, v = meta.v["x"], meta.v
    fast = v["xspeed"] >= 24

    # Run-up for a wall Mario cannot clear from here (4 tiles needs full speed; any wall when stuck).
    behind = [e for e in meta.enemies if abs(e["dy"]) < 24 and -80 < e["dx"] < 0]
    runway = [e for e in meta.enemies if abs(e["dy"]) < 24 and 0 <= e["dx"] < 56 and e["dx"] < (meta.wall_px or 9999) - 8]
    if ctrl.mode == "runup":
        ctrl.runup_frames += frames
        dist = ctrl.wall_x - x
        if x > ctrl.wall_x + 20 or ctrl.runup_frames > 900:
            ctrl.mode = ""
        else:
            W = f"run-up for the wall at {ctrl.wall_x}"
            if not ctrl.phase_run:
                if x <= ctrl.runup_from or ctrl.backup_blocked >= 3:
                    ctrl.phase_run = True
                    ctrl.short_runway = ctrl.backup_blocked >= 3 and (ctrl.wall_x - x) < 56
                elif behind:
                    if any(e["dx"] > -40 for e in behind) and meta.on_ground:
                        return _frames(act, ctrl, frames, right=False, run=False, jump_now=True, hold=4), "hop", f"{W}: a goomba is right behind, hopping (code)"
                    ctrl.a_hold = 0
                    return _frames(act, ctrl, frames, right=False, run=False), "wait", f"{W}: waiting for the enemy behind to pass (code)"
                else:
                    ctrl.backup_blocked = ctrl.backup_blocked + 1 if ctrl.backup_x - x < 2 else 0
                    ctrl.backup_x = x
                    ctrl.a_hold, ctrl.a_prev = 0, False
                    return [act("LEFT") for _ in range(frames)], "back_up", f"{W}: backing up (code)"
            take, hold = wall_plan(ctrl.wall_h)
            if runway and meta.on_ground and ctrl.a_hold == 0 and runway[0]["dx"] <= 40:
                return _frames(act, ctrl, frames, jump_now=True, hold=8), "stomp", f"{W}: stomping the enemy on the runway (code)"
            if meta.on_ground and ctrl.a_hold == 0 and dist <= take + 6 and v["xspeed"] >= 20:
                return _frames(act, ctrl, frames, jump_now=True, hold=hold), "jump", f"{W}: jumping at speed (code)"
            if meta.on_ground and ctrl.a_hold == 0 and dist <= 24 and v["xspeed"] < 12:
                if ctrl.short_runway or ctrl.wall_h <= 3:
                    return _frames(act, ctrl, frames, jump_now=True, hold=32), "jump", f"{W}: no runway, standing jump with full hold (code)"
                ctrl.phase_run, ctrl.backup_blocked, ctrl.backup_x = False, 0, x + 100
                return [act("LEFT") for _ in range(frames)], "back_up", f"{W}: reached the wall too slow, backing up again (code)"
            return _frames(act, ctrl, frames), "run", f"{W}: running at it, {dist}px to go, speed {v['xspeed']} (code)"
    wall_close = meta.wall_at is not None and meta.wall_at <= 3 and meta.wall_height >= 2
    tall = wall_close and meta.wall_height >= 4
    if ctrl.mode == "" and meta.on_ground and ((tall and not fast) or (meta.stuck and wall_close)) and not runway:
        ctrl.mode, ctrl.wall_x, ctrl.wall_h, ctrl.runup_frames, ctrl.phase_run = "runup", x + meta.wall_px, meta.wall_height, 0, False
        ctrl.runup_from = ctrl.wall_x - (7 if tall else 4) * 16
        ctrl.a_hold, ctrl.backup_x, ctrl.backup_blocked, ctrl.short_runway = 0, x + 100, 0, False
        why = "a 4-tile wall is close and Mario is slow" if tall else "stuck at a wall"
        plan = [act("LEFT") for _ in range(frames)]; ctrl.a_prev = False
        return plan, "back_up", f"{why}: code is doing a run-up for the wall at {ctrl.wall_x}"

    # Nearest things ahead, in pixels.
    nearest_enemy = next((e for e in meta.enemies if 0 < e["dx"] <= 72 and abs(e["dy"]) < 24), None)
    gap = (meta.gap_px, meta.gap_width) if meta.gap_at is not None else None
    wall = (meta.wall_px, meta.wall_height) if meta.wall_at is not None else None

    # Code refuses to run off an edge and says so.
    if mv == "run" and meta.on_ground and gap is not None and gap[0] <= 20:
        mv, override = "jump", "a gap starts right there, code jumped"
    if meta.stuck and mv in ("run", "wait") and not wall_close:
        mv, override = "jump", "stuck against something, code jumped"
    # Jev's stomp judgment drives the stomp when an enemy is close.
    if nearest_enemy is not None and a.stomp >= 0.5 and mv in ("run", "wait") and meta.on_ground:
        mv = "stomp"

    if mv == "stomp" and nearest_enemy is not None and meta.on_ground:
        if nearest_enemy["dx"] <= 40:
            return _frames(act, ctrl, frames, jump_now=True, hold=8), "stomp", override
        return _frames(act, ctrl, frames), "stomp: closing in", override
    if mv == "jump" and meta.on_ground:
        # Take the nearer of gap and wall; time the takeoff and the hold from its size.
        target = None
        if gap is not None and (wall is None or gap[0] <= wall[0]):
            take, hold = gap_plan(gap[1]); target = ("gap", gap[0], take, hold)
        elif wall is not None:
            take, hold = wall_plan(wall[1]); target = ("wall", wall[0], take, hold)
        if target is not None:
            kind, px, take, hold = target
            if px <= take + 8:
                return _frames(act, ctrl, frames, jump_now=True, hold=hold), f"jump the {kind}", override
            return _frames(act, ctrl, frames), f"jump the {kind}: running to the takeoff", override
        return _frames(act, ctrl, frames, jump_now=True, hold=12), "jump", override
    if mv == "wait":
        ctrl.a_hold = 0; ctrl.a_prev = False
        return [act() for _ in range(frames)], "wait", override
    return _frames(act, ctrl, frames), "run" if mv == "run" else mv, override
