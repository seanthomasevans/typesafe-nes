#!/usr/bin/env python
"""Jev plays Super Mario Bros. One TypeSafe request every few frames; code does the rest.

    .venv/bin/python run.py --seconds 180 --show
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())

from mariobot.emu import Mario, FPS  # noqa: E402
from mariobot.perceive import perceive  # noqa: E402
from mariobot.brain import Brain, Ctrl, policy, DANGER_LEVELS  # noqa: E402
from mariobot.overlay import Panel  # noqa: E402


class Recorder:
    def __init__(self, path, w, h, fps=FPS):
        self.p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
                                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], stdin=subprocess.PIPE)

    def write(self, frame):
        self.p.stdin.write(np.ascontiguousarray(frame).tobytes())

    def close(self):
        self.p.stdin.close(); self.p.wait()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--decision-frames", type=int, default=6)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-decisions", type=int, default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    out = Path(args.out) if args.out else ROOT / "runs" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    m = Mario()
    panel = Panel(*m.obs.shape[:2])
    rec = None if args.no_record else Recorder(out / "run.mp4", panel.w, panel.h)
    if args.show:
        import cv2
        cv2.namedWindow("jev plays mario", cv2.WINDOW_AUTOSIZE)
    brain, ctrl, hist = Brain(), Ctrl(), {}
    log = open(out / "decisions.jsonl", "w")
    stats = {"model": "", "decisions": 0, "deaths": 0, "game_overs": 0, "levels": 0, "cost": 0.0}
    budget, total, lat, dec, max_x, best_world, level_times = int(args.seconds * FPS), 0, [], None, 0, "1-1", {}
    t_start = time.time()
    try:
        while total < budget:
            words, meta = perceive(m, hist)
            if meta.dead:
                stats["deaths"] += 1
                print(f"[{total/FPS:6.1f}s] died at x={meta.v['x']} world {meta.v['world']}-{meta.v['stage']}", flush=True)
                for _ in range(FPS * 3):
                    m.step(m.act()); total += 1
                if not m.wait_playable():
                    stats["game_overs"] += 1; m.start_game()
                hist.clear(); ctrl.a_hold = 0; ctrl.mode = ""
                continue
            if meta.v["state"] != 8 or meta.v["mode"] != 1:
                if (meta.v["float"] == 3 or meta.v["state"] in (4, 5)) and best_world not in level_times:
                    level_times[best_world] = meta.v["time"]
                    stats["levels"] += 1; print(f"[{total/FPS:6.1f}s] LEVEL COMPLETE {best_world} with {meta.v['time']} on the clock, deaths so far {stats['deaths']}", flush=True)
                m.wait_playable(); hist.clear(); ctrl.a_hold = 0; ctrl.mode = ""; continue
            a = brain.ask(words, meta)
            plan, label, override = policy(meta, a, args.decision_frames, ctrl, m.act)
            hist.setdefault("moves", []).append(label); del hist["moves"][:-6]
            lat.append(a.latency_ms); max_x = max(max_x, meta.v["x"]); best_world = f"{meta.v['world']}-{meta.v['stage']}"
            stats.update(model=a.model, decisions=stats["decisions"] + 1, latency_ms=a.latency_ms, input_tokens=a.input_tokens, cost=brain.cost_usd,
                         world=best_world, lives=meta.v["lives"], x=meta.v["x"], time=meta.v["time"])
            dec = {"answers": a.as_dict(), "label": label, "override": override, "danger_legend": DANGER_LEVELS, "ahead": words["ahead"]}
            log.write(json.dumps({"frame": total, "state": words, "answers": a.as_dict(), "label": label, "override": override, "x": meta.v["x"]}) + "\n")
            if args.verbose or stats["decisions"] % 50 == 0:
                print(f"[{total/FPS:6.1f}s] #{stats['decisions']} {a.latency_ms:.0f}ms x={meta.v['x']} {words['mario']['footing']} danger={a.danger:.1f} move={a.move}({a.move_conf:.2f}) stomp={a.stomp:.2f} -> {label}" + (f" [{override}]" if override else "") + f" | {words['ahead'] if isinstance(words['ahead'], str) else '; '.join(words['ahead'][:3])}", flush=True)
            for buttons in plan:
                frame = m.step(buttons); total += 1
                if rec is not None or args.show:
                    img = panel.render(frame, dec, stats)
                    if rec is not None: rec.write(img)
                    if args.show:
                        cv2.imshow("jev plays mario", img[:, :, ::-1]); cv2.waitKey(1)
            if args.max_decisions and stats["decisions"] >= args.max_decisions:
                break
    finally:
        log.close()
        if rec is not None: rec.close()
        brain.close()
        if args.show: cv2.destroyAllWindows()
    summary = {"model": stats["model"], "decisions": stats["decisions"], "game_seconds": round(total / FPS, 1), "wall_seconds": round(time.time() - t_start, 1),
               "deaths": stats["deaths"], "game_overs": stats["game_overs"], "levels_completed": stats["levels"], "level_clock": level_times, "furthest_x": max_x, "world": best_world,
               "requests": brain.total_requests, "input_tokens": brain.total_tokens, "cost_usd": round(brain.cost_usd, 4),
               "latency_ms_median": round(float(np.median(lat)), 1) if lat else None, "latency_ms_p90": round(float(np.percentile(lat, 90)), 1) if lat else None,
               "video": str(out / "run.mp4") if rec else None}
    (out / "summary.json").write_text(json.dumps(summary, indent=2)); print(json.dumps(summary, indent=2))
    subprocess.run([str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "make_index.py"), "Jev plays Super Mario Bros"], check=False)


if __name__ == "__main__":
    main()
