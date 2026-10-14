#!/usr/bin/env python3
"""Check a finished cut before upload, and say what was checked.

  streams    video/audio codecs, size, frame rate, sample rate
  duration   file vs. the timeline built from public/data/vo.<cut>.json
  loudness   integrated loudness and true peak (target -14 LUFS, <= -1 dBTP)
  asr        the full mix (music and SFX included) transcribed and compared with the captions of every scene,
             plus the key terms of scenes.json (`keyTerms`) - catches a wrong take, a muted scene, music
             drowning the voice. Default engine: local faster-whisper (free); `--asr scribe` uses ElevenLabs
             (paid, same subscription as the voice).
  motion     consecutive-frame differences on a grid (caption band ignored): per scene the share of still frames,
             and runs >= 1 s in which nearly every part of the picture that holds content changes at once - a
             full-frame zoom, drift or shake, or sub-pixel jitter of everything (scene fades are skipped). Normal
             animation changes only a few regions. Check each run by rendering two stills one frame apart.

Usage: python3 scripts/verify.py out/video_en.mp4 --cut en [--asr whisper|scribe|none] [--whisper-model small]
       [--no-motion] [--ignore-bottom 0.2]
Writes notes/verify.<name>.json.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import ROOT, load_script, load_vo, project_fps, reexec_with, scene_spans, strip_tags, text_lang  # noqa: E402


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def loud(path):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    tail = err[err.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", tail)
    p = re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", tail)
    return float(i.group(1)), float(p.group(1)) if p and p.group(1) != "-inf" else None


def motion(path, spans, fps, ignore_bottom, w=960, h=540, thresh=6, gx=8, gy=6):
    """Per frame pair: which grid cells that hold content (edges) changed. Normal animation changes a few cells;
    a full-frame move (zoom, shake, drift) or sub-pixel jitter changes nearly all of them at once."""
    import numpy as np
    ch_ = int(h * (1 - ignore_bottom))
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={w}:{h}:flags=area,format=gray",
                             "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    cw, chh = w // gx, ch_ // gy
    prev, still, glob = None, [], []
    n = w * h
    while True:
        buf = proc.stdout.read(n)
        if len(buf) < n:
            break
        f = np.frombuffer(buf, np.uint8).reshape(h, w)[: chh * gy, : cw * gx].astype(np.int16)
        if prev is None:
            still.append(True)
            glob.append(0.0)
        else:
            changed = (np.abs(f - prev) > thresh).reshape(gy, chh, gx, cw).sum((1, 3))
            edges = ((np.abs(np.diff(prev, axis=1, append=prev[:, -1:])) > 40)
                     | (np.abs(np.diff(prev, axis=0, append=prev[-1:])) > 40)).reshape(gy, chh, gx, cw).sum((1, 3))
            content = edges >= 40
            still.append(bool(changed.sum() == 0))
            glob.append(float((changed[content] >= 5).mean()) if content.sum() >= 6 else 0.0)
        prev = f
    proc.wait()
    bounds = [t for _, t, _ in spans] + ([spans[-1][1] + spans[-1][2]] if spans else [])

    def scene_at(fr):
        for s, t, d in spans:
            if t <= fr < t + d:
                return s["id"], fr - t
        return "-", fr

    runs, start = [], None
    for i, v in enumerate(glob + [0.0]):
        g = v >= 0.6 and not any(abs(i - b) <= 20 for b in bounds)  # scene fades sit on the boundaries
        if g and start is None:
            start = i
        elif not g and start is not None:
            if i - start >= fps:  # >= 1 s: a fade is shorter; a zoom, drift or jitter is not
                sid, off = scene_at(start)
                runs.append({"from": round(start / fps, 2), "to": round(i / fps, 2), "scene": sid, "sceneFrame": off,
                             "meanShareOfCellsChanging": round(sum(glob[start:i]) / (i - start), 2)})
            start = None
    per_scene = {}
    for s, t, d in spans:
        seg = still[t: t + d]
        if seg:
            per_scene[s["id"]] = round(sum(seg) / len(seg), 2)
    return {"frames": len(still), "stillShareByScene": per_scene, "fullFrameMotionRuns": runs}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--cut", help="voice cut id (vo.<cut>.json) for duration, ASR and scene names")
    ap.add_argument("--asr", choices=["whisper", "scribe", "none"], default="whisper")
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--no-motion", action="store_true")
    ap.add_argument("--ignore-bottom", type=float, default=0.2, help="share of the frame height kept for captions")
    a = ap.parse_args()
    reexec_with(["numpy"])
    video = pathlib.Path(a.video)
    fps = project_fps()
    res, warn = {"file": str(video)}, []

    pr = probe(video)
    v = next(s for s in pr["streams"] if s["codec_type"] == "video")
    au = next((s for s in pr["streams"] if s["codec_type"] == "audio"), None)
    num, den = (int(x) for x in v["r_frame_rate"].split("/"))
    dur = float(pr["format"]["duration"])
    res["streams"] = {"video": f"{v['codec_name']} {v['width']}x{v['height']} {num / den:.3g} fps {v.get('pix_fmt')}",
                      "audio": f"{au['codec_name']} {au['sample_rate']} Hz {au['channels']} ch" if au else None,
                      "durationS": round(dur, 2)}
    print(f"streams   {res['streams']['video']} | {res['streams']['audio']} | {dur:.2f}s")
    if not au:
        warn.append("no audio stream")

    spans = []
    if a.cut:
        spans = scene_spans(load_vo(a.cut), fps)
        total = (spans[-1][1] + spans[-1][2]) / fps if spans else 0
        res["timelineS"] = round(total, 2)
        ok = abs(dur - total) < 0.25
        print(f"duration  {'PASS' if ok else 'WARN'} file {dur:.2f}s vs timeline {total:.2f}s")
        if not ok:
            warn.append(f"duration differs from the timeline by {dur - total:+.2f}s (re-render after the last vo build?)")

    if au:
        i, tp = loud(video)
        res["loudness"] = {"I": i, "truePeak": tp}
        ok = -15 <= i <= -13 and (tp is None or tp <= -1.0)
        print(f"loudness  {'PASS' if ok else 'WARN'} {i} LUFS, true peak {tp} dBFS")
        if not ok:
            warn.append("loudness outside -14±1 LUFS or true peak above -1 dBFS")

    if au and a.cut and a.asr != "none":
        import voice_qa
        script = load_script()
        tl = text_lang(script, a.cut)
        sl = script.get("voices", {}).get(a.cut, {}).get("language", tl)  # spoken language (see vo.py "language")
        scenes = [s for s in script["scenes"] if tl in s]
        caption = " ".join(strip_tags(l["text"]) for s in scenes for l in s[tl]["lines"])
        spoken = " ".join(strip_tags(l.get("tts", l["text"])) for s in scenes for l in s[tl]["lines"])
        with tempfile.TemporaryDirectory() as td:
            wav = pathlib.Path(td) / "mix.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-ac", "1", "-ar", "16000", str(wav)], check=True)
            print(f"asr       transcribing the full mix ({a.asr}) ...", flush=True)
            r = voice_qa.asr(str(wav), sl, a.asr, a.whisper_model)
        sc_cap, sc_say = voice_qa.score(caption, sl, r), voice_qa.score(spoken, sl, r)
        best = min((sc_cap, sc_say), key=lambda x: x["err"])
        cfg = script["voices"][a.cut]
        terms = cfg.get("keyTerms", []) + [t for s in scenes for t in s[tl].get("keyTerms", [])]
        lost = []
        for term in dict.fromkeys(terms):
            alts = [x.lower() for x in term.split("|") if x]
            want = sum(spoken.lower().count(x) for x in alts)
            got = sum(r["text"].lower().count(x) for x in alts)
            if got < want:
                lost.append(f"{term.split('|')[0]} ({got}/{want})")
        res["asr"] = {"engine": r["engine"], "err": best["err"], "diffs": best["diffs"], "lostTerms": lost, "text": r["text"]}
        ok = best["err"] < 0.08 and not lost
        print(f"asr       {'PASS' if ok else 'WARN'} error {best['err']:.3f} ({r['engine']}; digits vs words and names "
              f"count as errors, compare with the per-scene report){'; lost terms: ' + ', '.join(lost) if lost else ''}")
        if lost:
            print("            a term lost in every occurrence is usually the ASR's own spelling (whisper writes Qwen as 'Quen'):"
                  " look at the diffs, add that spelling to keyTerms, or re-check a short segment with --asr scribe")
        for d in best["diffs"][:25]:
            print(f"            {d}")
        if not ok:
            warn.append("full-mix ASR: read the diffs above (a misread, a missing scene, or music too loud?)")

    if not a.no_motion:
        print("motion    decoding frames ...", flush=True)
        m = motion(video, spans, fps, a.ignore_bottom)
        res["motion"] = m
        runs = m["fullFrameMotionRuns"]
        print(f"motion    {'WARN' if runs else 'PASS'} {len(runs)} full-frame motion run(s) >= 1 s; still share by scene: "
              + ", ".join(f"{k} {v:.0%}" for k, v in m["stillShareByScene"].items()))
        for r in runs:
            print(f"            {r['from']:7.2f}-{r['to']:7.2f}s {r['scene']} (+{r['sceneFrame']}f) "
                  f"{r['meanShareOfCellsChanging']:.0%} of content cells changing")
        if runs:
            warn.append("full-frame motion (zoom/drift/jitter?): look at those spans, two stills one frame apart")

    res["warnings"] = warn
    out = ROOT / "notes" / f"verify.{video.stem}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(("ALL PASS" if not warn else f"{len(warn)} warning(s): " + " | ".join(warn)) + f"  -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
