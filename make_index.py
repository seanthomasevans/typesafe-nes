#!/usr/bin/env python
"""Write runs/index.html: every run in runs/ with its summary and video. Data-derived labels only."""
import html, json, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
TITLE = sys.argv[1] if len(sys.argv) > 1 else ROOT.name

rows = []
for d in sorted(RUNS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
    s = d / "summary.json"
    if not d.is_dir() or not s.exists():
        continue
    summ = json.loads(s.read_text())
    video = d / "run.mp4"
    rows.append((d.name, datetime.fromtimestamp(s.stat().st_mtime).strftime("%Y-%m-%d %H:%M"), summ, video if video.exists() else None))

keys = []
for _, _, summ, _ in rows:
    for k in summ:
        if k not in keys and k not in ("video", "model"):
            keys.append(k)

def cell(v):
    if isinstance(v, float): return f"{v:.3f}" if v < 10 else f"{v:.1f}"
    return html.escape(str(v))

parts = [f"""<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="45"><title>{html.escape(TITLE)} runs</title>
<style>
body{{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;color:#111;background:#fff;margin:0;padding:32px 40px;font-size:14px}}
h1{{font-size:20px;font-weight:500;margin:0 0 6px}} .sub{{color:#777;margin-bottom:24px}}
table{{border-collapse:collapse;width:100%;margin-bottom:32px}} th,td{{text-align:left;padding:7px 10px;border-bottom:1px solid #e5e5e5;font-variant-numeric:tabular-nums;white-space:nowrap}}
th{{color:#777;font-weight:500;font-size:12px}} tr.sel td{{background:#fff3f3}} td a{{color:#111}} tr[data-video]{{cursor:pointer}}
.run{{margin-bottom:40px}} .run h2{{font-size:15px;font-weight:500;margin:0 0 8px}} .run h2 span{{color:#777;font-weight:400;margin-left:12px}}
video{{width:100%;max-width:1040px;background:#000;display:block}} .meta{{color:#777;font-size:12px;margin-top:6px}}
.none{{color:#999}} .acc{{color:#E30613}}
</style></head><body>
<h1>{html.escape(TITLE)}</h1><div class="sub">{len(rows)} runs in runs/ · click a row to jump to its video · newest first</div>
<table><thead><tr><th>run</th><th>when</th>{''.join(f'<th>{html.escape(k)}</th>' for k in keys)}<th>video</th></tr></thead><tbody>"""]
for name, when, summ, video in rows:
    parts.append(f"<tr data-video=\"{'1' if video else ''}\" onclick=\"location.hash='{html.escape(name)}'\"><td>{html.escape(name)}</td><td>{when}</td>"
                 + "".join(f"<td>{cell(summ[k]) if k in summ else '<span class=none>·</span>'}</td>" for k in keys)
                 + f"<td>{'yes' if video else '<span class=none>none</span>'}</td></tr>")
parts.append("</tbody></table>")
for name, when, summ, video in rows:
    parts.append(f"<div class=run id=\"{html.escape(name)}\"><h2>{html.escape(name)}<span>{when}</span></h2>")
    if video:
        parts.append(f"<video controls preload=\"none\" src=\"{html.escape(name)}/run.mp4\"></video>")
    else:
        parts.append("<div class=none>no video for this run (recorded with --no-record)</div>")
    parts.append(f"<div class=meta>{' · '.join(f'{html.escape(k)} {cell(summ[k])}' for k in keys if k in summ)} · <a href=\"{html.escape(name)}/decisions.jsonl\">decisions.jsonl</a></div></div>")
parts.append("</body></html>")
(RUNS / "index.html").write_text("\n".join(parts))
print(f"{RUNS / 'index.html'}: {len(rows)} runs")
