#!/usr/bin/env python3
"""Review stills: render every anchor of a cut (a little after the anchor, when its beat has settled) plus each
scene's first and last moments, then tile them into contact sheets - one sheet per scene, or one for the film.

Usage: python3 scripts/review.py <CompositionId> <cut> [--scenes s_intro,s_end] [--after 18] [--scale 0.5]
                                 [--out review] [--per-sheet 12]
  e.g. python3 scripts/review.py VIDEO-ZH zh --scenes s_method
Needs the composition's frames to be laid out by public/data/vo.<cut>.json (as the template does).
Prints the sheet paths; open them and look for overlaps, clipping, empty frames, illegible or off-message text.
Runs scripts/text_check.py for the cut first (caption typography, font coverage; reported, not fatal).
"""
import argparse
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import ROOT, frames, load_vo, project_fps, scene_spans  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("comp")
ap.add_argument("cut")
ap.add_argument("--scenes", help="comma-separated scene ids (default: all)")
ap.add_argument("--after", type=int, default=18, help="frames after each anchor (let the beat settle)")
ap.add_argument("--scale", type=float, default=0.5)
ap.add_argument("--out", default="review")
ap.add_argument("--per-sheet", type=int, default=12)
a = ap.parse_args()

# typography first (cheap): caption layout rules + font coverage, reported, not fatal; never rebuilds fonts here
# (a render may be reading public/)
subprocess.run([sys.executable, str(pathlib.Path(__file__).resolve().parent / "text_check.py"), "--cut", a.cut, "--no-fetch"], cwd=ROOT)
fps = project_fps()
only = set(a.scenes.split(",")) if a.scenes else None
plan = []  # (frame, label, scene)
for s, t, dur in scene_spans(load_vo(a.cut), fps):
    if only and s["id"] not in only:
        continue
    pts = {t + 6: "start", t + dur - 4: "end"}
    for l in s["lines"]:
        for k, v in l["anchors"].items():
            pts.setdefault(min(t + dur - 4, max(t, t + frames(s["leadInMs"] + v, fps) + a.after)), k)
    plan += [(f, f"{s['id']}-{lab}", s["id"]) for f, lab in sorted(pts.items())]
if not plan:
    sys.exit("no frames (unknown scene ids?)")

out = ROOT / a.out / a.comp
out.mkdir(parents=True, exist_ok=True)
lst = out / f"frames_{os.getpid()}.txt"  # per process: several reviews may run at once
lst.write_text("\n".join(f"{f} {lab}" for f, lab, _ in plan))
r = subprocess.run(["node", str(pathlib.Path(__file__).resolve().parent / "stills.mjs"), a.comp, str(out), f"@{lst}",
                    "--scale", str(a.scale)], cwd=ROOT, capture_output=True, text=True)
if r.returncode:
    sys.exit(r.stderr[-3000:])
pngs = [p for p in r.stdout.split("\n") if p.endswith(".png")]
lst.unlink(missing_ok=True)
groups = {}
for (f, lab, sid), png in zip(plan, pngs):
    groups.setdefault(sid if only else "film", []).append(png)
sheets = []
for key, files in groups.items():
    for i in range(0, len(files), a.per_sheet):
        sheet = out / f"sheet_{key}_{i // a.per_sheet + 1}.png"
        subprocess.run([sys.executable, str(pathlib.Path(__file__).resolve().parent / "contact_sheet.py"), str(sheet),
                        *files[i: i + a.per_sheet], "--cols", "3"], check=True, capture_output=True)
        sheets.append(sheet)
for s in sheets:
    print(s)
