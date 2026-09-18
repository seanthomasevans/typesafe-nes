# typesafe-nes

Jev (TypeSafe's System One model) plays Super Mario Bros. through stable-retro. Every 6 frames
code reads Mario's RAM (position, state, the 32×13 tile map, the five enemy slots) and writes a
few lines of words: "goomba 3 tiles ahead, at Mario's level, can be stomped", "a gap in the ground
starting 1 tile ahead, 2 tiles wide". One TypeSafe request asks four typed questions in parallel:

| id | type | question |
|---|---|---|
| move | Choice: run, jump, high_jump, wait, back_up | What Mario should do now |
| danger | Score, 3 levels | How urgent the nearest problem is |
| stomp | Noul | Jump onto the nearest enemy |
| full_speed | Noul | Safe to keep running for 3 tiles |

Code owns the RAM reading, the tile scan, jump-hold timing, and two refusals it logs on the panel:
it jumps when a gap starts right under the next step, and when Mario is stuck against a wall.

## ROM

The game runs from a Super Mario Bros. + Duck Hunt combo cart (iNES mapper 66) through a custom
stable-retro integration in `refs/retro-int/SMBDuckHunt-Nes/` (gitignored): `rom.nes`, `rom.sha`
(the ROM's SHA-1), plus `data.json`, `metadata.json`, `scenario.json` copied from stable-retro's
`SuperMarioBros-Nes-v0` integration. The RAM layout is the same as the plain cartridge.

## Run

```bash
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt
echo 'TYPESAFE_API_KEY=...' > .env
.venv/bin/python run.py --seconds 180 --show
```

Outputs in `runs/<timestamp>/`: `run.mp4` (game at 2× plus the judgment panel, 60 fps),
`decisions.jsonl`, `summary.json`. `probe.py` runs a scripted Mario with no Jev calls to check perception.

## Files

- `mariobot/emu.py` stable-retro wrapper, verified RAM addresses, start sequence
- `mariobot/perceive.py` RAM to words and numbers
- `mariobot/brain.py` questions, request, policy
- `mariobot/overlay.py` panel renderer
- `run.py` loop, recorder, logs
