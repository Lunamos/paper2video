#!/usr/bin/env python3
"""Build a small local CJK font subset (default: Noto Sans SC / 思源黑体) for the CJK cuts, and check that it
covers every character the video can show.

Why: loading Noto Sans SC from Google Fonts at render time means ~100 unicode-range slices per
weight, i.e. hundreds of requests per render tab (slow, flaky). Instead, collect every character the
video can show that the Latin fonts (Inter / Source Serif / JetBrains Mono, latin + latin-ext) do not
cover - CJK, full-width punctuation, Greek, arrows, maths - from scenes.json, every JSON in
public/data/ (captions, data labels) and src/ (code, comments stripped), and ask Google Fonts for exactly
those glyphs (css2 `text=` parameter), one woff2 per weight.

Writes public/fonts/<lang>/<Family>-<weight>.woff2 and the manifest src/theme/fonts-<lang>.json:
  {"family": "<Family> Subset", "chars": N, "text": "<the characters>", "files": {"400": "fonts/zh/NotoSansSC-400.woff2", ...},
   "hand": {"family": "<Hand> Subset", "file": "..."}}       # only with --hand
The template's theme loads these with FontFace and uses the family as the CJK fallback.

--check (finalize.sh and covers.sh run it before rendering; text_check.py too): rebuilds the subset when the
text has characters the manifest does not list, then reads every weight's cmap and exits 1 listing each
character the font lacks - such a glyph would silently fall back to a system font in the render.

  python3 scripts/zh_font_subset.py [--lang zh] [--family "Noto Sans SC"] [--weights 400,500,700] [--hand "Long Cang"]
  python3 scripts/zh_font_subset.py --check [--lang zh] [--no-fetch]
"""
from __future__ import annotations  # PEP 604 annotations on the macOS system Python 3.9

import argparse
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import CJK, ROOT, is_cjk_lang, reexec_with  # noqa: E402

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
BASE = "，。、；：？！「」『』（）《》〈〉【】——……“”‘’·～"
# covered by the Latin fonts' latin + latin-ext subsets (Inter first in every stack): no need for the CJK subset
LATIN = re.compile(r"[\x00-\x7f -˿Ḁ-ỿ -⁯₠-⃀™↑↓−﻿]")
IGNORABLE = re.compile(r"[\s​-‏⁠-⁤︀-️]")
DEFAULTS = {"family": "Noto Sans SC", "weights": "400,500,600,700,900"}


def needs_subset(ch: str) -> bool:
    return not LATIN.match(ch) and not IGNORABLE.match(ch)


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


def strip_comments(src: str) -> str:
    """TS/TSX source without // and /* */ comments (string and template literals kept)."""
    out, i, n, q = [], 0, len(src), None
    while i < n:
        c = src[i]
        if q:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 1
            elif c == q:
                q = None
        elif c in "\"'`":
            q = c
            out.append(c)
        elif src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def collect() -> tuple[str, dict[str, str]]:
    """(the characters the subset must hold, {character: first place it was seen})."""
    where: dict[str, str] = {}

    def add(text: str, place: str):
        for ch in text:
            if needs_subset(ch) and ch not in where:
                where[ch] = place

    add(BASE, "base set")
    sj = ROOT / "scenes.json"
    if sj.exists():
        for s in strings(json.loads(sj.read_text())):
            add(s, "scenes.json")
    for f in sorted((ROOT / "public" / "data").glob("*.json")):
        if f.name == "zh_breaks.json":  # derived from src/ and the vo files
            continue
        try:
            for s in strings(json.loads(f.read_text())):
                add(s, str(f.relative_to(ROOT)))
        except ValueError:
            pass
    for f in sorted((ROOT / "src").rglob("*.ts*")):
        add(strip_comments(f.read_text(errors="ignore")), str(f.relative_to(ROOT)))
    return "".join(sorted(where)), where


def fetch(family, weight, text) -> bytes:
    spec = f"{family}:wght@{weight}" if weight else family
    q = urllib.parse.urlencode({"family": spec, "text": text, "display": "block"})
    css = urllib.request.urlopen(urllib.request.Request(f"https://fonts.googleapis.com/css2?{q}", headers={"User-Agent": UA}),
                                 timeout=60).read().decode()
    urls = re.findall(r"url\((https://[^)]+)\)", css)
    if len(urls) != 1:
        sys.exit(f"unexpected css for {spec}: {len(urls)} font urls")
    return urllib.request.urlopen(urllib.request.Request(urls[0], headers={"User-Agent": UA}), timeout=60).read()


def manifest_path(lang: str) -> pathlib.Path:
    return ROOT / "src" / "theme" / f"fonts-{lang}.json"


def build(lang: str, family: str, weights: str, hand: str | None, text: str) -> dict:
    out = ROOT / "public" / "fonts" / lang
    out.mkdir(parents=True, exist_ok=True)
    stem = family.replace(" ", "")
    manifest = {"family": f"{family} Subset", "chars": len(text), "text": text, "files": {}}
    for w in [int(x) for x in weights.split(",")]:
        data = fetch(family, w, text)
        dst = out / f"{stem}-{w}.woff2"
        dst.write_bytes(data)
        manifest["files"][str(w)] = f"fonts/{lang}/{dst.name}"
        print(f"{family} {w}: {len(data) / 1024:.0f} KB")
    if hand:
        data = fetch(hand, None, text)
        dst = out / f"{hand.replace(' ', '')}-400.woff2"
        dst.write_bytes(data)
        manifest["hand"] = {"family": f"{hand} Subset", "file": f"fonts/{lang}/{dst.name}"}
        print(f"{hand}: {len(data) / 1024:.0f} KB")
    dst = manifest_path(lang)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"{len(text)} characters -> {out.relative_to(ROOT)}, manifest {dst.relative_to(ROOT)}")
    return manifest


def check(lang: str = "zh", fetch_ok: bool = True) -> list[tuple[str, str, str]]:
    """Rebuild a stale subset (if allowed), then [(char, weight, first place seen)] for every glyph the subset lacks;
    weight "stale" = a character the subset was not built with (fetch_ok=False). Needs fontTools + brotli
    (text_check.py and --check pull them in through uv)."""
    from fontTools.ttLib import TTFont

    text, where = collect()
    mp = manifest_path(lang)
    m = json.loads(mp.read_text()) if mp.exists() else {"files": {}}
    if not any(CJK.match(c) for c in text) and not m.get("files"):
        return []  # no CJK text at all: nothing to subset
    stale = set(text) - set(m.get("text", "")) if m.get("files") else set(text)
    if stale and not fetch_ok:
        out = [(c, "stale", where.get(c, "?")) for c in sorted(stale)]
        for w, rel in m.get("files", {}).items():
            cmap = TTFont(ROOT / "public" / rel).getBestCmap()
            out += [(c, w, where.get(c, "?")) for c in text if c not in stale and ord(c) not in cmap]
        return out
    if stale:
        print(f"font subset: {len(stale)} new character(s) ({''.join(sorted(stale))[:40]}) -> rebuilding")
        family = m.get("family", DEFAULTS["family"] + " Subset").removesuffix(" Subset")
        weights = ",".join(m["files"]) if m.get("files") else DEFAULTS["weights"]
        hand = m.get("hand", {}).get("family", "").removesuffix(" Subset") or None
        m = build(lang, family, weights, hand, text)
    missing = []
    for w, rel in m["files"].items():
        cmap = TTFont(ROOT / "public" / rel).getBestCmap()
        missing += [(c, w, where.get(c, "?")) for c in text if ord(c) not in cmap]
    return missing


def report(missing, lang) -> int:
    if not missing:
        print(f"font subset ({lang}): every displayed character is covered")
        return 0
    chars = sorted({c for c, _, _ in missing})
    print(f"FAIL font subset ({lang}): {len(chars)} character(s) have no glyph and would fall back to a system font"
          + (" (weight 'stale': not in the subset yet; run without --no-fetch to rebuild)" if any(w == "stale" for _, w, _ in missing) else "") + ":")
    for c in chars:
        ws = sorted({w for x, w, _ in missing if x == c})
        place = next(p for x, _, p in missing if x == c)
        print(f"  {c}  U+{ord(c):04X}  weights {','.join(ws)}  (first seen in {place})")
    print("  fix: replace the character (e.g. 10⁶ -> KaTeX 10^{6} or a <sup>), use another --family, or load a font that has it")
    return 1


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lang", default="zh", help="CJK language; names the output folder and manifest")
    p.add_argument("--family", default=DEFAULTS["family"], help="Google Fonts family (Noto Sans JP for Japanese, ...)")
    p.add_argument("--weights", default=DEFAULTS["weights"])
    p.add_argument("--hand", help="optional handwriting family for annotations, e.g. 'Long Cang'")
    p.add_argument("--check", action="store_true", help="rebuild if stale, then fail on any character the font lacks")
    p.add_argument("--no-fetch", action="store_true", help="with --check: report a stale subset instead of rebuilding it")
    a = p.parse_args()
    if not is_cjk_lang(a.lang):
        sys.exit(f"{a.lang} is not a CJK language")
    if a.check:
        reexec_with(["fontTools", "brotli"])
        sys.exit(report(check(a.lang, not a.no_fetch), a.lang))
    text, _ = collect()
    build(a.lang, a.family, a.weights, a.hand, text)


if __name__ == "__main__":
    main()
