#!/usr/bin/env python3
"""Word boundaries for Chinese on-screen text: public/data/zh_breaks.json = {"<scene>:<line>": [character offsets
where a caption line may break], "t:<string>": [...], "_src": {...}}, computed with jieba.

- "<scene>:<line>": the caption words of public/data/vo.<cut>.json joined without spaces, exactly as
  src/typography/captions.ts joins them (16:9 and vertical captions).
- "t:<string>": every CJK string literal / JSX text in src/ (whitespace removed), for <Words> in
  src/typography/ZhText.tsx (headlines, cards, claims).
The renderer intersects these with Intl.Segmenter's boundaries (each catches the other's slips: Intl.Segmenter alone
splits 金门大桥 as 金门|大|桥, jieba alone 很|久). Words jieba gets wrong can be added to `notes/zh_words.txt` (one per
line, jieba user-dictionary format) and to `keyTerms` in scenes.json (the part before `|`).

Re-run after every Chinese voice build and after changing Chinese text in src/:
  python3 scripts/zh_breaks.py [--cut zh]        (pulls jieba in through uv if needed)
"""
import argparse
import hashlib
import json
import logging
import pathlib
import re
import sys
import warnings

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import CJK, ROOT, load_script, reexec_with  # noqa: E402

warnings.filterwarnings("ignore")  # jieba's old regexes
reexec_with(["jieba"])
import jieba  # noqa: E402

jieba.setLogLevel(logging.ERROR)


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


def screen_strings(root: pathlib.Path) -> set[str]:
    """CJK string literals and JSX text in src/ (JSX text with its whitespace collapsed the way JSX does)."""
    found = set()
    for f in sorted((root / "src").rglob("*.ts*")):
        code = strip_comments(f.read_text(errors="ignore"))
        for m in re.finditer(r"([\"'`])((?:(?!\1)[^\\\n]|\\.)*)\1", code):
            for part in re.split(r"\$\{[^}]*\}", m.group(2)):
                if CJK.search(part):
                    found.add(part)
        for m in re.finditer(r">([^<>{}]+)<", code):
            text = " ".join(x.strip() for x in m.group(1).splitlines() if x.strip())
            if CJK.search(text):
                found.add(text)
    return found


def offsets(text: str) -> list[int]:
    offs, o = [], 0
    for tok in jieba.cut(text, HMM=True):
        if o > 0:
            offs.append(o)
        o += len(tok)
    return offs


def load_words():
    user = ROOT / "notes/zh_words.txt"
    if user.exists():
        jieba.load_userdict(str(user))
    try:
        for s in load_script().get("voices", {}).values():
            for t in s.get("keyTerms", []) if isinstance(s, dict) else []:
                w = t.split("|")[0].strip()
                if CJK.search(w):
                    jieba.add_word(w)
    except SystemExit:
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cut", default="zh")
    a = ap.parse_args()
    load_words()
    path = ROOT / f"public/data/vo.{a.cut}.json"
    raw = path.read_bytes()
    vo = json.loads(raw)
    out = {"_src": {"cut": a.cut, "vo": hashlib.sha1(raw).hexdigest()[:12]}}
    for s in vo["scenes"]:
        for l in s["lines"]:
            out[f"{s['id']}:{l['id']}"] = offsets("".join(w["w"] for w in l["words"]))
    strings = screen_strings(ROOT)
    trim = re.compile(r"[，。、；：,;:]+$")
    for t in strings:
        for v in {t, trim.sub("", t)}:  # <Words> drops a trailing ，。 before looking the string up
            key = "".join(v.split())
            if key:
                out[f"t:{key}"] = offsets(key)
    (ROOT / "public/data/zh_breaks.json").write_text(json.dumps(out, ensure_ascii=False))
    n_lines = sum(len(s["lines"]) for s in vo["scenes"])
    print(f"{n_lines} caption lines + {len(strings)} on-screen strings -> public/data/zh_breaks.json")


if __name__ == "__main__":
    main()
