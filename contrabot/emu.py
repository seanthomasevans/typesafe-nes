"""Contra (USA) through stable-retro with a custom integration (refs/retro-int/Contra-Nes).
nes-py could load the ROM but its controller input never registered, so every nes-py probe was
watching the attract demo. RAM addresses from Data Crystal, checked in-emulator 2026-09-18."""
from __future__ import annotations

import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
import retro  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FPS = 60
A_PX, A_PY, A_STATE, A_JUMP, A_AIM, A_DEATH, A_INV, A_LEVEL, A_SCREEN, A_SCROLL, A_LIVES = 0x334, 0x31A, 0x90, 0xA0, 0xC0, 0xB4, 0xB0, 0x30, 0x64, 0xFD, 0x32


class Contra:
    def __init__(self):
        retro.data.Integrations.add_custom_path(str(ROOT / "refs" / "retro-int"))
        self.env = retro.make("Contra-Nes", inttype=retro.data.Integrations.CUSTOM_ONLY, state=retro.State.NONE,
                              use_restricted_actions=retro.Actions.ALL, render_mode=None)
        self.buttons = self.env.buttons
        self.frame, self.obs = 0, None
        self.reset()

    def act(self, *names):
        return [1 if b in names else 0 for b in self.buttons]

    def ram(self):
        return self.env.get_ram()

    def step(self, buttons):
        self.obs = self.env.step(buttons)[0]
        self.frame += 1
        return self.obs

    def reset(self):
        """Power on, one START at the title (1 PLAYER is the default), wait for a real game with medals.
        Retries the START if the first press did not take."""
        out = self.env.reset()
        self.obs = out[0] if isinstance(out, tuple) else out
        for _ in range(300): self.step(self.act())
        for attempt in range(4):
            for _ in range(8): self.step(self.act("START"))
            if self.wait_playable(600):
                return True
            for _ in range(120): self.step(self.act())
        return False

    def in_game(self):
        """Real game: lives byte in 1..9 and at least one medal sprite (tile 10) in the top bar.
        The attract demo shows GAME OVER as sprites (tiles 2..8) and its lives byte reads 98."""
        r = self.ram()
        lives = int(r[A_LIVES])
        medals = any(r[0x200 + 4 * i] < 24 and r[0x200 + 4 * i + 1] == 10 for i in range(64))
        return 0 < lives <= 9 and medals

    def wait_playable(self, limit=1200):
        for _ in range(limit):
            r = self.ram()
            if r[A_STATE] == 1 and r[A_DEATH] == 0 and r[A_PX] > 0 and self.in_game():
                return True
            self.step(self.act())
        return False

    def vars(self):
        r = self.ram()
        return {"px": int(r[A_PX]), "py": int(r[A_PY]), "state": int(r[A_STATE]), "jump": int(r[A_JUMP]), "aim": int(r[A_AIM]),
                "death": int(r[A_DEATH]), "inv": int(r[A_INV]), "level": int(r[A_LEVEL]), "screen": int(r[A_SCREEN]),
                "scroll": int(r[A_SCROLL]), "lives": int(r[A_LIVES]), "progress": int(r[A_SCREEN]) * 256 + int(r[A_SCROLL])}
