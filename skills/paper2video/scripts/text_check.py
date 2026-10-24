#!/usr/bin/env python3
"""Typography check before rendering (reference/visual-style.md "Typography"): lays out every caption of a cut with
the template's own code (scripts/caption_layout.mjs -> src/typography/captions.ts) for the 16:9 film and the 9:16
cut, checks the CJK font subset, and lists every rule a caption breaks.

ERROR (exit 1)
  glyph     a displayed character the font subset lacks (zh_font_subset.py --check; a stale subset is rebuilt first)
  start     a line starts with closing punctuation (，。、；：！？）》」』”’…—)
  end       a line ends with opening punctuation (（《「『“‘)
  split     a line break inside a word (jieba), or between a number and its unit
  orphan    the last line of a two-line caption is shorter than 3 CJK characters
  overflow  a line longer than the measure + 10 %
  forced    no layout kept every rule: shorten the line in scenes.json or split it at a clause
WARN
  ragged    the last line is under 35 % of the line above
  short     a caption page under 3 characters (a flash)
  stale     zh_breaks.json was built from another vo file (re-run scripts/zh_breaks.py), or the font subset lacks new
            characters (--no-fetch; finalize.sh / covers.sh rebuild it)
  period    an on-screen string in src/ ends with ，/。 (<Words> drops it in centred text; write it without)
INFO (file only)
  wide      a line over the measure, within the 10 % slack (the renderer shrinks the font <= 6 % / widens the box)

Usage: python3 scripts/text_check.py [--cut zh] [--kinds wide,vertical] [--no-fonts] [--no-fetch]
       full list -> review/text_check.<cut>.txt; prints a summary. Run it after zh_breaks.py, before rendering.
"""
from __future__ import annotations  # PEP 604 annotations on the macOS system Python 3.9

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import warnings

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import CJK, ROOT, reexec_with  # noqa: E402

warnings.filterwarnings("ignore", category=SyntaxWarning)  # jieba's old regexes
reexec_with(["jieba", "fontTools", "brotli"])
import zh_breaks  # noqa: E402  (jieba, user words, on-screen strings)
import zh_font_subset  # noqa: E402

LATIN = re.compile(r"[A-Za-z0-9]")


def layout(cut: str, kinds: list[str]) -> dict | None:
    r = subprocess.run(["node", str(HERE / "caption_layout.mjs"), cut, "--kind", "both" if len(kinds) > 1 else kinds[0]],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        print(f"WARN captions not checked: {r.stderr.strip()[-300:]}")
        return None
    return json.loads(r.stdout)


def check_captions(d: dict, issues: list):
    zh = d["zh"]
    slack = d["slack"]
    closing, opening = d["closing"], d["opening"]
    for kind, lines in d["layouts"].items():
        for ln in lines:
            words, sp, ok = ln["words"], ln["sp"], set(ln["ok"])
            joined = "".join(words)
            jb = set(zh_breaks.offsets(joined)) if zh and CJK.search(joined) else None
            starts, o = [], 0
            for w in words:
                starts.append(o)
                o += len(w)

            def show(a, b):
                return "".join((" " if sp[i] and i > a else "") + words[i] for i in range(a, b))

            where = lambda p, r: f"{ln['key']} [{kind} p{p + 1}" + (f" l{r + 1}]" if len(ln['pages'][p]) > 1 else "]")  # noqa: E731
            if ln["forced"]:
                issues.append(("ERROR", "forced", where(0, 0), " || ".join(" / ".join(show(a, b) for a, b in pg) for pg in ln["pages"])))
            n_pages = len(ln["pages"])
            for p, (pg, ws) in enumerate(zip(ln["pages"], ln["widths"])):
                for r, ((a, b), w) in enumerate(zip(pg, ws)):
                    text = show(a, b)
                    if a > 0:
                        prev, nxt = words[a - 1], words[a]
                        word_edge = bool(sp[a]) or bool(LATIN.match(nxt[0])) != bool(LATIN.match(prev[-1]))
                        if a not in ok or (jb is not None and starts[a] not in jb and not word_edge):
                            issues.append(("ERROR", "split", where(p, r), f"{show(max(0, a - 3), a)} | {show(a, min(len(words), a + 3))}"))
                        if nxt[0] in closing:
                            issues.append(("ERROR", "start", where(p, r), text))
                    if b < len(words) and words[b - 1][-1] in opening:
                        issues.append(("ERROR", "end", where(p, r), text))
                    per = ln["per"]
                    if w > per * (1 + slack) + 0.01:
                        issues.append(("ERROR", "overflow", where(p, r), f"{text}  ({w:g} > {per} + 10 %)"))
                    elif w > per + 0.01:
                        issues.append(("INFO", "wide", where(p, r), f"{text}  ({w:g} / {per})"))
                    min_len = 3 if zh else 6
                    if r > 0 and r == len(pg) - 1:
                        if w < min_len:
                            issues.append(("ERROR", "orphan", where(p, r), f"{show(*pg[r - 1])} / {text}"))
                        elif w < 0.35 * ws[r - 1]:
                            issues.append(("WARN", "ragged", where(p, r), f"{show(*pg[r - 1])} / {text}"))
                if len(pg) == 1 and n_pages > 1 and ws[0] < (3 if zh else 6):
                    issues.append(("WARN", "short", where(p, 0), show(*pg[0])))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cut", default="zh")
    ap.add_argument("--kinds", default="wide,vertical", help="caption layouts to check: wide (16:9), vertical (9:16)")
    ap.add_argument("--no-fonts", action="store_true")
    ap.add_argument("--no-fetch", action="store_true", help="report a stale font subset instead of rebuilding it")
    ap.add_argument("--lang", default="zh", help="CJK font subset to check")
    a = ap.parse_args()
    issues: list[tuple[str, str, str, str]] = []

    if not a.no_fonts:
        missing = zh_font_subset.check(a.lang, not a.no_fetch)
        stale = "".join(sorted({c for c, w, _ in missing if w == "stale"}))
        if stale:
            issues.append(("WARN", "stale", "font subset", f"{len(stale)} character(s) not in it yet ({stale[:30]}): finalize.sh / covers.sh "
                           "rebuild it, or python3 scripts/zh_font_subset.py --check"))
        missing = [m for m in missing if m[1] != "stale"]
        for c in sorted({c for c, _, _ in missing}):
            ws = ",".join(sorted({w for x, w, _ in missing if x == c}))
            place = next(p for x, _, p in missing if x == c)
            issues.append(("ERROR", "glyph", f"U+{ord(c):04X} {c}", f"missing in weight {ws}; first seen in {place}"))

    zh_breaks.load_words()
    vo_path = ROOT / f"public/data/vo.{a.cut}.json"
    d = layout(a.cut, a.kinds.split(",")) if vo_path.exists() else None
    if d:
        if d["zh"]:
            table_path = ROOT / "public/data/zh_breaks.json"
            src = json.loads(table_path.read_text()).get("_src", {}) if table_path.exists() else {}
            if src.get("vo") != hashlib.sha1(vo_path.read_bytes()).hexdigest()[:12]:
                issues.append(("WARN", "stale", "zh_breaks.json", f"not built from the current vo.{a.cut}.json: python3 scripts/zh_breaks.py --cut {a.cut}"))
        check_captions(d, issues)
    trail = re.compile(r"[，。]$")
    for s in sorted(zh_breaks.screen_strings(ROOT)):
        if trail.search(s) and len(s) <= 40:
            issues.append(("WARN", "period", "src", s))

    out = ROOT / "review" / f"text_check.{a.cut}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(f"{lvl:5} {kind:8} {where}  {msg}\n" for lvl, kind, where, msg in issues))
    errors = [i for i in issues if i[0] == "ERROR"]
    counts = {}
    for lvl, kind, *_ in issues:
        counts[f"{lvl} {kind}"] = counts.get(f"{lvl} {kind}", 0) + 1
    n_lines = sum(len(v) for v in d["layouts"].values()) if d else 0
    print(f"text check ({a.cut}): {n_lines} caption layouts, "
          + (", ".join(f"{k} {v}" for k, v in sorted(counts.items()) if not k.startswith("INFO")) or "no errors or warnings"))
    for lvl, kind, where, msg in [i for i in issues if i[0] == "ERROR"][:15] + [i for i in issues if i[0] == "WARN"][:8]:
        print(f"  {lvl:5} {kind:8} {where}  {msg}")
    if issues:
        print(f"  full list: {out.relative_to(ROOT)}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
