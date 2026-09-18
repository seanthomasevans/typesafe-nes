"""Generic run loop for a NES game module: perceive -> one Jev request -> policy -> frames, with the
panel, recorder, decision log, summary, and index regeneration. A game module provides:
make_game(), TITLE, SPEC [(id, type, extra)], build_questions(words, meta), policy(meta, answers, frames, ctrl, act),
Ctrl class, and game methods: step(buttons), act(*names), obs, frame, perceive(hist) -> (words, meta),
dead(meta), after_death(), transition(meta) -> str|None, footer(meta), progress(meta)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from typesafe_sdk import TypeSafeClient

from .panel import Panel

ROOT = Path(__file__).resolve().parent.parent
PRICE_PER_MTOK = 0.042
FPS = 60


def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())


class Recorder:
    def __init__(self, path, w, h, fps=FPS):
        self.p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
                                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], stdin=subprocess.PIPE)

    def write(self, frame):
        self.p.stdin.write(np.ascontiguousarray(frame).tobytes())

    def close(self):
        self.p.stdin.close(); self.p.wait()


def ask(client, words, questions, spec):
    t0 = time.time()
    r = client.system_one(state=words, questions=questions)
    ms = (time.time() - t0) * 1000
    out = {}
    for qid, qtype, _ in spec:
        if qtype == "choice":
            a = r.choices[qid]; out[qid] = {"choice": a.choice, "probabilities": dict(a.probabilities), "confidence": a.confidence}
        elif qtype == "score":
            a = r.scores[qid]; out[qid] = {"score": a.score, "probabilities": {str(k): v for k, v in a.probabilities.items()}, "confidence": a.confidence}
        else:
            out[qid] = {"noul": r.nouls[qid].noul}
    return out, ms, r.usage.input_tokens, r.model


def run(mod, argv=None):
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--decision-frames", type=int, default=6)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-decisions", type=int, default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    slug = mod.SLUG
    out = Path(args.out) if args.out else ROOT / "runs" / f"{slug}-{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    game = mod.make_game()
    panel = Panel(*game.obs.shape[:2], mod.SPEC, mod.TITLE)
    rec = None if args.no_record else Recorder(out / "run.mp4", panel.w, panel.h)
    if args.show:
        import cv2
        cv2.namedWindow(mod.TITLE, cv2.WINDOW_AUTOSIZE)
    client, ctrl, hist = TypeSafeClient(), mod.Ctrl(), {}
    log = open(out / "decisions.jsonl", "w")
    stats = {"model": "", "decisions": 0, "deaths": 0, "cost": 0.0, "transitions": []}
    total_tokens, budget, total, lat, dec, best = 0, int(args.seconds * FPS), 0, [], None, 0
    t_start = time.time()
    try:
        while total < budget:
            words, meta = game.perceive(hist)
            if game.dead(meta):
                stats["deaths"] += 1
                print(f"[{total/FPS:6.1f}s] died, {game.footer(meta)}", flush=True)
                total += game.after_death(); hist.clear(); ctrl.__init__()
                continue
            tr = game.transition(meta)
            if tr:
                stats["transitions"].append({"at_s": round(total / FPS, 1), "what": tr}); print(f"[{total/FPS:6.1f}s] {tr}", flush=True)
                hist.clear(); ctrl.__init__(); continue
            answers, ms, toks, model = ask(client, words, mod.build_questions(words, meta), mod.SPEC)
            total_tokens += toks; lat.append(ms)
            plan, label, override = mod.policy(meta, answers, args.decision_frames, ctrl, game.act)
            hist.setdefault("moves", []).append(label); del hist["moves"][:-6]
            best = max(best, game.progress(meta))
            stats.update(model=model, decisions=stats["decisions"] + 1, latency_ms=ms, input_tokens=toks, cost=total_tokens / 1e6 * PRICE_PER_MTOK)
            dec = {"answers": answers, "label": label, "override": override, "seen": words.get("seen", [])}
            log.write(json.dumps({"frame": total, "state": words, "answers": answers, "label": label, "override": override, "progress": game.progress(meta)}) + "\n")
            if args.verbose or stats["decisions"] % 50 == 0:
                seen = words.get("seen", []); seen = seen if isinstance(seen, str) else "; ".join(seen[:3])
                print(f"[{total/FPS:6.1f}s] #{stats['decisions']} {ms:.0f}ms {game.footer(meta)} -> {label}" + (f" [{override}]" if override else "") + f" | {seen}", flush=True)
            for buttons in plan:
                frame = game.step(buttons); total += 1
                if rec is not None or args.show:
                    img = panel.render(frame, dec, stats, game.footer(meta) + f"   deaths {stats['deaths']}")
                    if rec is not None: rec.write(img)
                    if args.show:
                        cv2.imshow(mod.TITLE, img[:, :, ::-1]); cv2.waitKey(1)
            if args.max_decisions and stats["decisions"] >= args.max_decisions: break
    finally:
        log.close()
        if rec is not None: rec.close()
        client.close()
        if args.show: cv2.destroyAllWindows()
    summary = {"game": mod.TITLE, "model": stats["model"], "decisions": stats["decisions"], "game_seconds": round(total / FPS, 1), "wall_seconds": round(time.time() - t_start, 1),
               "deaths": stats["deaths"], "transitions": stats["transitions"], "best_progress": best, "requests": len(lat), "input_tokens": total_tokens,
               "cost_usd": round(total_tokens / 1e6 * PRICE_PER_MTOK, 4), "latency_ms_median": round(float(np.median(lat)), 1) if lat else None,
               "latency_ms_p90": round(float(np.percentile(lat, 90)), 1) if lat else None, "video": str(out / "run.mp4") if rec else None}
    (out / "summary.json").write_text(json.dumps(summary, indent=2)); print(json.dumps(summary, indent=2))
    subprocess.run([str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "make_index.py"), "Jev plays NES"], check=False)
