"""Jev side for Mario: one request per decision with four typed questions, then a small policy
that turns the answers into controller buttons for the next few frames."""
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
    "run": "Keep running right at full speed.",
    "jump": "Jump now: a normal jump, enough for one enemy, a gap 1 or 2 tiles wide, or a wall up to 2 tiles tall.",
    "high_jump": "Jump now and hold it: the highest and longest jump, for gaps 3 tiles or wider and walls 3 tiles or taller.",
    "wait": "Stop and stand still so the enemy comes closer or passes.",
    "back_up": "Walk left a few steps to make room.",
}


def build_questions(words: dict, meta: Meta) -> dict:
    return {
        "move": Choice(
            instructions="What should Mario do right now, using `mario` and `ahead`? Jump when the nearest gap, wall, or stompable enemy is 1 or 2 tiles ahead and Mario is on the ground. Run when the next 3 tiles are clear. Wait or back up when something that must not be touched is close ahead and Mario cannot jump over it.",
            criteria=MOVES,
        ),
        "danger": Score(
            instructions="How urgent is the nearest problem in `ahead`?",
            criteria=DANGER_LEVELS,
        ),
        "stomp": Noul(
            instructions="Should Mario jump onto the nearest enemy in `ahead` to stomp it?",
            criteria={
                "true": "The nearest enemy ahead can be stomped, is within 3 tiles, and is at Mario's level.",
                "false": "No enemy is close ahead, or the nearest enemy must not be stomped, or it is above or below Mario.",
            },
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
        return Answers(
            move=mv.choice, move_probs=dict(mv.probabilities), move_conf=mv.confidence,
            danger=dg.score, danger_probs={str(k): v for k, v in dg.probabilities.items()}, danger_conf=dg.confidence,
            stomp=r.nouls["stomp"].noul, full_speed=r.nouls["full_speed"].noul,
            latency_ms=ms, input_tokens=r.usage.input_tokens, model=r.model,
        )


@dataclass
class Ctrl:
    a_hold: int = 0          # frames left to keep holding A (a high jump keeps rising while held)


def policy(meta: Meta, a: Answers, frames: int, ctrl: Ctrl, act):
    """Compose Jev's answers into `frames` button vectors. Returns (plan, label, override)."""
    mv, override = a.move, ""

    # Code refuses two obviously fatal outcomes and says so.
    if meta.on_ground and meta.gap_at is not None and meta.gap_at <= 1 and mv == "run":
        mv, override = "high_jump", "a gap starts right there, code jumped"
    if meta.stuck and mv in ("run", "wait"):
        mv, override = "high_jump", "stuck against a wall, code jumped"

    plan = []
    if mv == "run":
        for i in range(frames):
            plan.append(act("RIGHT", "B", "A") if ctrl.a_hold > 0 else act("RIGHT", "B"))
            ctrl.a_hold = max(0, ctrl.a_hold - 1)
    elif mv == "jump":
        ctrl.a_hold = 0
        for i in range(frames):
            plan.append(act("RIGHT", "B", "A") if i < 4 else act("RIGHT", "B"))
    elif mv == "high_jump":
        ctrl.a_hold = 22
        for i in range(frames):
            plan.append(act("RIGHT", "B", "A"))
            ctrl.a_hold -= 1
    elif mv == "wait":
        ctrl.a_hold = 0
        plan = [act() for _ in range(frames)]
    else:  # back_up
        ctrl.a_hold = 0
        plan = [act("LEFT") for _ in range(frames)]
    return plan, mv, override
