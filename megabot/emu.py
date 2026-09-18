"""Mega Man (USA) through stable-retro with a custom integration (refs/retro-int/MegaMan-Nes).
RAM addresses from Data Crystal, checked in-emulator 2026-09-18; enemies come from the sprite list."""
from __future__ import annotations

import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
import retro  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FPS = 60
A_CAMX, A_CAMSCR, A_XSCR, A_X, A_Y, A_HP, A_IFRAMES, A_LIVES, A_STAGE, A_BOSSHP = 0x1A, 0x1B, 0x20, 0x22, 0x25, 0x6A, 0x55, 0xA6, 0x31, 0x6C1
HP_FULL = 0x1C


class MegaMan:
    def __init__(self):
        retro.data.Integrations.add_custom_path(str(ROOT / "refs" / "retro-int"))
        self.env = retro.make("MegaMan-Nes", inttype=retro.data.Integrations.CUSTOM_ONLY, state=retro.State.NONE,
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
        """Power on, START at the title, START at stage select (default cursor), wait for control."""
        out = self.env.reset()
        self.obs = out[0] if isinstance(out, tuple) else out
        for _ in range(400): self.step(self.act())
        for _ in range(8): self.step(self.act("START"))
        for _ in range(240): self.step(self.act())
        for _ in range(8): self.step(self.act("START"))
        self.wait_playable()

    def wait_playable(self, limit=900):
        """Mega Man teleports in; wait until y is stable on the ground and HP is set."""
        last = None
        for _ in range(limit):
            r = self.ram()
            y = int(r[A_Y])
            if r[A_HP] > 0 and y > 0 and y == last:
                return True
            last = y
            self.step(self.act())
        return False

    def vars(self):
        r = self.ram()
        return {"x": int(r[A_XSCR]) * 256 + int(r[A_X]), "x_screen": int(r[A_X]), "y": int(r[A_Y]), "hp": int(r[A_HP]),
                "iframes": int(r[A_IFRAMES]), "lives": int(r[A_LIVES]), "stage": int(r[A_STAGE]), "boss_hp": int(r[A_BOSSHP]),
                "cam": int(r[A_CAMSCR]) * 256 + int(r[A_CAMX])}
