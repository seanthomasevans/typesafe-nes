#!/usr/bin/env python3
"""Build the stable-retro custom integration this repo expects from a ROM you own.

    python make_integration.py --game mario   --rom "/path/to/Super Mario Bros.nes"
    python make_integration.py --game contra  --rom "/path/to/Contra (USA).nes"
    python make_integration.py --game megaman --rom "/path/to/Mega Man (USA).nes"

Writes refs/retro-int/<Name>-Nes/{rom.nes, rom.sha, data.json, metadata.json, scenario.json}.
refs/ is gitignored; ROMs are never part of this repository."""
import argparse, hashlib, json, os, shutil, warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

ROOT = Path(__file__).resolve().parent
NAMES = {"mario": "SMBDuckHunt-Nes", "contra": "Contra-Nes", "megaman": "MegaMan-Nes"}
DATA = {
    "contra": {"info": {"px": {"address": 0x334, "type": "|u1"}, "py": {"address": 0x31A, "type": "|u1"}, "lives": {"address": 0x32, "type": "|u1"}, "screen": {"address": 0x64, "type": "|u1"}, "scroll": {"address": 0xFD, "type": "|u1"}}},
    "megaman": {"info": {"hp": {"address": 0x6A, "type": "|u1"}, "lives": {"address": 0xA6, "type": "|u1"}, "stage": {"address": 0x31, "type": "|u1"}, "x": {"address": 0x22, "type": "|u1"}, "xscreen": {"address": 0x20, "type": "|u1"}, "y": {"address": 0x25, "type": "|u1"}}},
}

ap = argparse.ArgumentParser()
ap.add_argument("--game", choices=NAMES, required=True)
ap.add_argument("--rom", required=True)
a = ap.parse_args()
dest = ROOT / "refs" / "retro-int" / NAMES[a.game]
dest.mkdir(parents=True, exist_ok=True)
rom = Path(a.rom)
shutil.copy(rom, dest / "rom.nes")
(dest / "rom.sha").write_text(hashlib.sha1(rom.read_bytes()).hexdigest() + "\n")
if a.game == "mario":
    import retro
    src = Path(retro.data.get_file_path("SuperMarioBros-Nes", "data.json")).parent
    for f in ("data.json", "scenario.json", "metadata.json"):
        shutil.copy(src / f, dest / f)
else:
    json.dump(DATA[a.game], open(dest / "data.json", "w"))
    json.dump({"default_state": None, "states": {}}, open(dest / "metadata.json", "w"))
    json.dump({"done": {"variables": {}}, "reward": {"variables": {}}}, open(dest / "scenario.json", "w"))
print(f"integration written: {dest}")
