#!/usr/bin/env python3
"""Review stills of the vertical (9:16) scenes: every anchor (+ a few frames, once the beat has settled) plus each
scene's start and end, rendered from the `V-<Name>` scene compositions (src/vertical/scenes/registry.ts) with one
bundle per scene, tiled into one contact sheet per scene (270×480 cells).

Usage: python3 scripts/vreview.py [--cut zh]  (use --cut en while the zh voice is not built yet: vo.zh.json is a placeholder until then)
       [--scenes s_intro,s_end] [--after 18] [--scale 0.5] [--out review/vertical]
Look for: text outside the text-safe area or under the captions, more than ~3 elements, empty top/bottom bands
(the picture should fill the frame), beats that miss their anchor. Runs scripts/text_check.py --kinds vertical first.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import ROOT, frames, project_fps  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--cut", default="zh")
ap.add_argument("--scenes", help="comma-separated scene ids (default: all registered vertical scenes)")
ap.add_argument("--after", type=int, default=18)
ap.add_argument("--scale", type=float, default=0.5)
ap.add_argument("--out", default="review/vertical")
a = ap.parse_args()

# typography first (cheap): caption layout rules + font coverage, reported, not fatal; never rebuilds fonts here
# (a render may be reading public/)
subprocess.run([sys.executable, str(pathlib.Path(__file__).resolve().parent / "text_check.py"), "--cut", a.cut, "--no-fetch", "--kinds", "vertical"], cwd=ROOT)
reg = (ROOT / "src/vertical/scenes/registry.ts").read_text()
names = dict(re.findall(r'id: "([^"]+)", name: "([^"]+)"', reg))
vo = json.loads((ROOT / f"public/data/vo.{a.cut}.json").read_text())
fps = project_fps()
only = set(a.scenes.split(",")) if a.scenes else None
out = ROOT / a.out
out.mkdir(parents=True, exist_ok=True)
sheets = []
for s in vo["scenes"]:
    if s["id"] not in names or (only and s["id"] not in only):
        continue
    dur = frames(max(s.get("minSeconds", 0) * 1000, s["leadInMs"] + s["durationMs"] + s["tailMs"]), fps)
    pts = {6: "start", dur - 4: "end"}
    for l in s["lines"]:
        for k, v in (l.get("anchors") or {}).items():
            pts.setdefault(min(dur - 4, max(0, frames(s["leadInMs"] + v, fps) + a.after)), k)
    comp = f"V-{names[s['id']]}"
    lst = out / f"{comp}.txt"
    lst.write_text("\n".join(f"{fr} {lab}" for fr, lab in sorted(pts.items())))
    r = subprocess.run(["node", str(HERE / "stills.mjs"), comp, str(out / comp), f"@{lst}", "--scale", str(a.scale), "--props", json.dumps({"lang": a.cut})],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr[-2000:])
    pngs = [p for p in r.stdout.split("\n") if p.endswith(".png")]
    sheet = out / f"sheet_{s['id']}.png"
    subprocess.run([sys.executable, str(HERE / "contact_sheet.py"), str(sheet), *pngs, "--cols", "6", "--cell", "270x480"],
                   check=True, capture_output=True)
    sheets.append(sheet)
if not sheets:
    sys.exit(f"no vertical scene of src/vertical/scenes/registry.ts is in public/data/vo.{a.cut}.json — build the timeline "
             f"first (python3 scripts/vo.py build --lang {a.cut}; the 'none' backend gives estimated timings for free)")
print("\n".join(map(str, sheets)))
