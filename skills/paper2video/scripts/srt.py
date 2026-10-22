#!/usr/bin/env python3
"""Export the captions of a cut as .srt (YouTube CC, Bilibili subtitles, editing apps).

Pages are the burned-in 16:9 captions, laid out by the template's own code (scripts/caption_layout.mjs ->
src/typography/captions.ts: one line per page, ≤ 18 CJK / ≈ 58 Latin characters, clause boundaries first, never
inside a word, kinsoku, no orphan page). CJK: full-width punctuation at a page end is dropped and mid-page
punctuation becomes a space, as in Chinese subtitle practice. A project without src/typography falls back to the
older paging below (which mirrors its older Captions.tsx). Each cue ends 0.6 s after its last word (or when the next
cue starts).

Usage: python3 scripts/srt.py <cut> [--out out/<cut>.srt] [--fps 30]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import CJK, ROOT, SCRIPTS, frames, is_cjk_lang, load_vo, project_fps, scene_spans  # noqa: E402

LIMIT_LATIN, LIMIT_CJK = 58, 18
HOLD = 0.6  # s a cue stays up after its last word


def tlen(w, cjk):
    if not cjk:
        return len(w["w"]) + 1
    n = len(CJK.findall(w["w"]))
    return n + (len(w["w"]) - n) * 0.55 + (0.5 if w.get("sp") else 0)


def paginate(words, cjk):
    limit = LIMIT_CJK if cjk else LIMIT_LATIN
    L = lambda ws: sum(tlen(w, cjk) for w in ws)  # noqa: E731
    if L(words) <= limit:
        return [words]
    clauses, cur = [], []
    for w in words:
        cur.append(w)
        if re.search(r"[,:;.!?，。：；！？、…」—]$", w["w"]):
            clauses.append(cur)
            cur = []
    if cur:
        clauses.append(cur)
    pieces = []
    for c in clauses:
        if L(c) <= limit:
            pieces.append(c)
            continue
        target = L(c) / -(-L(c) // limit)
        part = []
        for w in c:
            if part and L(part) + tlen(w, cjk) > target + (1 if cjk else 4):
                pieces.append(part)
                part = []
            part.append(w)
        if part:
            pieces.append(part)
    pages, page = [], []
    for pc in pieces:
        if page and L(page) + L(pc) > limit:
            pages.append(page)
            page = []
        page += pc
    if page:
        pages.append(page)
    return pages


def template_pages(cut):
    """{"<scene>:<line>": layout} of the burned-in 16:9 captions (caption_layout.mjs), or None if unavailable."""
    r = subprocess.run(["node", str(SCRIPTS / "caption_layout.mjs"), cut, "--kind", "wide"], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        print(f"NOTE: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'caption_layout.mjs failed'}; using the older paging")
        return None
    return {l["key"]: l for l in json.loads(r.stdout)["layouts"]["wide"]}


def text_of(ws, cjk):
    out = ""
    for i, w in enumerate(ws):
        t = w["w"]
        if cjk:
            stripped = re.sub(r"[，。、；：,.;:…]+$", "", t)
            t = stripped + ("" if i == len(ws) - 1 or stripped == t else " ")
        out += (" " if i and w.get("sp") else "") + t
    return out.strip()


def timecode(frame, fps):
    ms = round(frame / fps * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def cues(cut, fps):
    """[(fromFrame, toFrame, text)] for the whole cut."""
    vo = load_vo(cut)
    cjk = is_cjk_lang(vo["meta"].get("textLang", cut))
    pages = []
    table = template_pages(cut)
    for s, t0, _ in scene_spans(vo, fps):
        lead = s["leadInMs"]
        for l in s["lines"]:
            lay = table.get(f"{s['id']}:{l['id']}") if table else None
            if lay:
                ws = [{"w": w, "sp": sp, "from": t0 + frames(lead + a, fps), "to": t0 + frames(lead + b, fps)}
                      for w, sp, (a, b) in zip(lay["words"], lay["sp"], lay["ms"])]
                pgs = [ws[pg[0][0]:pg[-1][1]] for pg in lay["pages"]]
            else:
                ws = [{"w": w["w"], "sp": w.get("sp", 0), "from": t0 + frames(lead + w["startMs"], fps),
                       "to": t0 + frames(lead + w["endMs"], fps)} for w in l["words"]]
                pgs = paginate(ws, cjk) if ws else []
            for pg in pgs:
                pages.append((max(0, pg[0]["from"]), pg[-1]["to"], text_of(pg, cjk)))
    hold = round(HOLD * fps)
    return [(a, min(b + hold, pages[i + 1][0] if i + 1 < len(pages) else b + hold), txt) for i, (a, b, txt) in enumerate(pages)]


def write_srt(cut, out, fps):
    cs = cues(cut, fps)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(f"{i + 1}\n{timecode(a, fps)} --> {timecode(b, fps)}\n{txt}\n" for i, (a, b, txt) in enumerate(cs)))
    return len(cs)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cut", nargs="?", default="en")
    p.add_argument("--out")
    p.add_argument("--fps", type=int, default=project_fps())
    a = p.parse_args()
    if a.out:
        out = pathlib.Path(a.out)
    else:  # out/<slug>_<cut>.srt, slug = package.json "name" (the workspace convention); else out/<cut>.srt
        try:
            slug = json.loads((ROOT / "package.json").read_text()).get("name", "")
        except (OSError, ValueError):
            slug = ""
        out = ROOT / "out" / (f"{slug}_{a.cut}.srt" if slug and slug != "paper-video" else f"{a.cut}.srt")
    print(f"{write_srt(a.cut, out, a.fps)} cues -> {out}")


if __name__ == "__main__":
    main()
