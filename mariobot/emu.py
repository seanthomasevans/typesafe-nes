"""Super Mario Bros. through stable-retro, using Sean's SMB + Duck Hunt combo cart via a custom
integration (refs/retro-int/SMBDuckHunt-Nes). Exposes RAM reads and a clean start sequence."""
from __future__ import annotations

import os
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore", category=DeprecationWarning)
import retro  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FPS = 60

# RAM addresses (verified in-emulator 2026-09-18; sources: gym-super-mario-bros smb_env.py, stable-retro data.json)
A_PAGE, A_X, A_XSCREEN, A_Y, A_YVIEW = 0x6D, 0x86, 0x3AD, 0x3B8, 0xB5
A_STATE, A_SIZE, A_LIVES, A_COINS, A_WORLD, A_STAGE, A_MODE = 0x0E, 0x756, 0x75A, 0x75E, 0x75F, 0x75C, 0x770
A_FLOAT, A_YSPEED, A_XSPEED, A_TIME = 0x1D, 0x9F, 0x57, 0x7F8
E_TYPE, E_DRAWN, E_PAGE, E_X, E_Y = 0x16, 0x0F, 0x6E, 0x87, 0xCF
TILES, PAGE_BYTES, ROWS, COLS = 0x500, 208, 13, 16
TILE_Y0 = 16   # pixel y of tile row 0 (rows 0-12 cover y 16..223); checked against the ground under Mario


class Mario:
    def __init__(self):
        retro.data.Integrations.add_custom_path(str(ROOT / "refs" / "retro-int"))
        self.env = retro.make("SMBDuckHunt-Nes", inttype=retro.data.Integrations.CUSTOM_ONLY,
                              state=retro.State.NONE, use_restricted_actions=retro.Actions.ALL, render_mode=None)
        self.buttons = self.env.buttons
        self.frame = 0
        self.obs = None
        self.reset()

    def act(self, *names):
        return [1 if b in names else 0 for b in self.buttons]

    def ram(self):
        return self.env.get_ram()

    def step(self, buttons):
        out = self.env.step(buttons)
        self.obs = out[0]
        self.frame += 1
        return self.obs

    def reset(self):
        """Power on, pick Super Mario Bros. on the combo-cart menu, start a game, wait for play."""
        out = self.env.reset()
        self.obs = out[0] if isinstance(out, tuple) else out
        for _ in range(40): self.step(self.act())
        for _ in range(2): self.step(self.act("START"))          # combo-cart menu -> SMB title
        for _ in range(120): self.step(self.act())
        self.start_game()

    def start_game(self):
        presses = 0
        while self.ram()[A_MODE] != 1 and presses < 6:
            for _ in range(2): self.step(self.act("START"))
            presses += 1
            for _ in range(90): self.step(self.act())
        self.wait_playable()

    def wait_playable(self, limit=600):
        """Step no-ops until Mario is in the normal state on screen (after level cards, deaths)."""
        for _ in range(limit):
            r = self.ram()
            if r[A_MODE] == 1 and r[A_STATE] == 8 and r[A_YVIEW] == 1 and r[0x7A0] == 0:
                return True
            if r[A_MODE] == 0:            # back at the title (game over)
                return False
            self.step(self.act())
        return False

    # ---- raw facts -----------------------------------------------------------------
    def vars(self):
        r = self.ram()
        return {
            "x": int(r[A_PAGE]) * 256 + int(r[A_X]), "x_screen": int(r[A_XSCREEN]), "y": int(r[A_Y]), "yview": int(r[A_YVIEW]),
            "state": int(r[A_STATE]), "size": int(r[A_SIZE]), "lives": int(r[A_LIVES]), "coins": int(r[A_COINS]),
            "world": int(r[A_WORLD]) + 1, "stage": int(r[A_STAGE]) + 1, "mode": int(r[A_MODE]),
            "float": int(r[A_FLOAT]), "yspeed": int(np.int8(r[A_YSPEED])), "xspeed": int(np.int8(r[A_XSPEED])),
            "time": int(r[A_TIME]) * 100 + int(r[A_TIME + 1]) * 10 + int(r[A_TIME + 2]),
        }

    def enemies(self):
        r = self.ram()
        out = []
        for i in range(5):
            if r[E_DRAWN + i] == 0:
                continue
            out.append({"slot": i, "type": int(r[E_TYPE + i]), "x": int(r[E_PAGE + i]) * 256 + int(r[E_X + i]), "y": int(r[E_Y + i])})
        return out

    def tile(self, x, y):
        """Tile byte at level pixel (x, y); 0 = empty. Only the two loaded pages exist."""
        if y < TILE_Y0 or y >= TILE_Y0 + ROWS * 16 or x < 0:
            return 0
        page = (x // 256) % 2
        row, col = (y - TILE_Y0) // 16, (x % 256) // 16
        return int(self.ram()[TILES + page * PAGE_BYTES + row * 16 + col])

    def page_loaded(self, x):
        """True if the tile page containing x is the current page or the next one (ring of two)."""
        cur = self.vars()["x"] // 256
        return x // 256 in (cur, cur + 1)
