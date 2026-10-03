#!/usr/bin/env python3
"""Voice-over builder: scenes.json -> one audio clip per scene + word-timed timeline JSON.

Backends (per cut, scenes.json `voices.<cut>.backend`):
  elevenlabs  paid, best quality. v3 models + audio tags ([curious], [excited], [chuckles] ...),
              character alignment from /with-timestamps. Key: ELEVENLABS_API_KEY (env or .env).
              Several seeds per scene; each take is checked by an ASR round-trip (Scribe) and
              pitch-variation stats, and the best is picked automatically.
  edge        free, no key: Microsoft Edge neural voices via the `edge-tts` package (run through
              uv automatically). Word timings from WordBoundary events. Audio tags are stripped.
  gpt-sovits  open-source voice cloning served by a GPT-SoVITS api_v2 server (local GPU or a remote one
              through an ssh tunnel that vo.py can open itself: voices.<cut>.ssh / startCmd). Free per take,
              so several seeds per scene; one local faster-whisper pass per take gives word timings and
              the ASR check. Reference audio + its transcript set the timbre and the mood.
  fish        Fish Audio's HTTP API (fishaudio.org, /api/open/v3/speech/tts): paid per character (CJK 1 credit,
              other characters half), so the balance is checked first as for ElevenLabs. No seed parameter: each
              take is a fresh random read, cached under its seed label. Timings + ASR check from local faster-whisper.
              Key: FISH_API_KEY (or voices.<cut>.keyEnv).
  recorded    your own narration: recordings/<cut>/<scene_id>.(wav|mp3|m4a|flac). Word timings from
              local faster-whisper, aligned to the script. Interior pauses kept unless --tighten.
  none        no audio: a silent timeline from reading speed, so captions and anchors still work.

Why one request per scene: generating each line separately makes every sentence start "cold";
a whole-scene read flows like a person talking.

Pipeline per scene and take:
  synth (hash-cached by text + voice + model + settings + seed)
  -> graded pause tightening (clause < line break < sentence < ellipsis), per-line minimum gaps
     (`pauseAfterMs`), optional tempo
  -> polish (rumble high-pass, gentle compression, presence) + loudness normalisation
  -> QA (prosody always; ASR when choosing between takes) -> pick (manual picks file wins;
     `"pick": "steady"` on a scene prefers an even delivery)
Outputs public/audio/<cut>/<scene>.mp3, public/data/vo.<cut>.json (version 2, read by
src/timeline/timeline.ts) and notes/vo_report.<cut>.json.

ElevenLabs / Fish Audio: before every paid batch the subscription quota is queried, the billable characters of
all uncached requests are estimated and printed, and the run aborts if they exceed the remainder.
Keys are only read from the environment or .env and are never printed or written anywhere.

Usage:
  python3 scripts/vo.py build --lang en [--scene s_intro,s_method] [--seeds 11,23] [--takes 2] [--dry-run]
  python3 scripts/vo.py audition --lang en --voices a=VOICE_ID,b=VOICE_ID [--model eleven_v4,eleven_v3] [--text "..."]
  python3 scripts/vo.py audition --lang zh --backend edge --voices yunxi=zh-CN-YunxiNeural,xiaoxiao=zh-CN-XiaoxiaoNeural
(numpy / edge-tts / faster-whisper are pulled in through `uv run --with ...` when needed.)
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import difflib
import hashlib
import http.client
import json
import math
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import (CJK, ROOT, dur_s, env_key, load_script, normalise, reexec_with,  # noqa: E402
                    run_with, strip_tags)

CACHE = ROOT / "audio_cache"
API = "https://api.elevenlabs.io"
COST = {"eleven_v4": 1.0, "eleven_v4_turbo": 1.0, "eleven_v3": 1.0, "eleven_v3_conversational": 0.5, "eleven_multilingual_v2": 1.0, "eleven_flash_v2_5": 0.5,
        "eleven_turbo_v2_5": 0.5}
TARGET_LUFS = -19.0  # voice level before the final -14 LUFS master (music sits at -17.4 and is ducked)
MAX_PAUSE = 0.42  # s, fallback cap for silences inside a scene
EDGE_KEEP = 0.05  # s of silence kept at the start / end of a scene clip
DEFAULT_SEEDS = [11, 23, 37]
OPENERS = set("（(「『“‘《〈[")
AUDITION_TEXT = {
    "en": ("[curious] Have you ever wondered why a model gets the easy cases right, and the hard ones wrong? "
           "[excited] In the next few minutes, we'll see exactly where it breaks... and one small idea that fixes it."),
    "zh": ("[curious] 你有没有想过，为什么模型简单的题都做对了，难一点就不行？"
           "[excited] 接下来几分钟，我们来看看它到底卡在哪里……以及一个很小的改动，怎么把它修好。"),
}


# ================================================================ timings
def char_times(text: str, words) -> list[tuple[int, int]]:
    """Per-character (startMs, endMs) for `text` from any word list [(word, start_s, end_s)].

    Spoken characters of the script (letters, digits, CJK) are aligned to the characters of the
    recognised / synthesised words with difflib; mismatched spans share their time proportionally,
    unmatched characters are interpolated, and spaces / punctuation inherit the previous end time.
    Used by the edge and recorded backends so the rest of the pipeline sees one format."""
    spoken = lambda c: c.isalnum() or bool(CJK.match(c))  # noqa: E731
    tpos = [i for i, c in enumerate(text) if spoken(c)]
    tch = [text[i].lower() for i in tpos]
    wch, wt = [], []
    for w, s, e in words:
        cs = [c.lower() for c in w if spoken(c)]
        for k, c in enumerate(cs):
            wch.append(c)
            wt.append((s + (e - s) * k / len(cs), s + (e - s) * (k + 1) / len(cs)))
    got: dict[int, tuple[float, float]] = {}
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=tch, b=wch, autojunk=False).get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                got[i1 + k] = wt[j1 + k]
        elif op == "replace":
            s0, s1 = wt[j1][0], wt[j2 - 1][1]
            n = i2 - i1
            for k in range(n):
                got[i1 + k] = (s0 + (s1 - s0) * k / n, s0 + (s1 - s0) * (k + 1) / n)
    # interpolate spoken characters that found no counterpart
    known = sorted(got)
    for k in range(len(tpos)):
        if k in got:
            continue
        prev = max((j for j in known if j < k), default=None)
        nxt = min((j for j in known if j > k), default=None)
        a = got[prev][1] if prev is not None else (got[nxt][0] if nxt is not None else 0.0)
        b = got[nxt][0] if nxt is not None else a
        span = (nxt if nxt is not None else len(tpos)) - (prev if prev is not None else -1)
        pos = k - (prev if prev is not None else -1)
        t = a + (b - a) * (pos - 0.5) / span
        got[k] = (t, t)
    times, last, k = [], (0, 0), 0
    for i in range(len(text)):
        if k < len(tpos) and tpos[k] == i:
            s, e = got[k]
            last = (round(s * 1000), round(e * 1000))
            times.append(last)
            k += 1
        else:
            times.append((last[1], last[1]))
    return times


def reading_times(lines, cfg) -> tuple[list[tuple[int, int]], int]:
    """`none` backend: synthetic per-character times from reading speed (chars/s) and punctuation.
    cfg: cps (latin letters/digits per s, default 15), cpsCjk (CJK characters per s, default 5)."""
    cps, cps_cjk = cfg.get("cps", 15.0), cfg.get("cpsCjk", 5.0)
    times, t = [], 0.0
    for n, l in enumerate(lines):
        for c in l["say"]:
            if CJK.match(c) or c.isalnum():
                d = 1000 / (cps_cjk if CJK.match(c) else cps)
                times.append((round(t), round(t + d)))
                t += d
            else:
                times.append((round(t), round(t)))
                t += 380 if c in ".!?。！？…" else 200 if c in ",;:，；：、—" else 0
        if n < len(lines) - 1:
            times.append((round(t), round(t)))  # the joining space
            t += max(300, l.get("pauseAfterMs", 0))
    return times, round(t)


def estimate_length(scenes, tl, cfg, defaults, strip) -> float:
    """Film length in seconds from reading speed (EN ~150 wpm, ZH ~5 characters/s incl. pauses) plus each scene's
    lead-in/tail - within ~10 % of the voiced length, good enough to cut the script to length before paying."""
    total = 0.0
    for sc in scenes:
        block = sc[tl]
        _, ms = reading_times(prepare_lines(block, strip), {"cps": cfg.get("cps", 15.0), "cpsCjk": cfg.get("cpsCjk", 5.0)})
        lead = block.get("leadInMs", sc.get("leadInMs", defaults.get("leadInMs", 250)))
        tail = block.get("tailMs", sc.get("tailMs", defaults.get("tailMs", 350)))
        total += max(block.get("minSeconds", sc.get("minSeconds", 0)), (lead + ms + tail) / 1000)
    return total


# ================================================================ elevenlabs
def el_req(path, payload=None, timeout=240):
    r = urllib.request.Request(API + path, data=json.dumps(payload).encode() if payload is not None else None,
                               headers={"xi-api-key": env_key("ELEVENLABS_API_KEY"), "Content-Type": "application/json"},
                               method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} on {path.split('?')[0]}: {e.read().decode(errors='replace')[:400]}") from None


def el_quota():
    s = el_req("/v1/user/subscription")
    return s["character_limit"] - s["character_count"], s


def el_settings(model, stability):
    if model.startswith(("eleven_v3", "eleven_v4")):
        vs = {"stability": stability, "similarity_boost": 0.8}
        if model == "eleven_v3_conversational":
            vs["use_speaker_boost"] = True
        return vs
    return {"stability": stability, "similarity_boost": 0.8, "style": 0.25, "use_speaker_boost": True}


def cache_key(**parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def el_key(text, voice, model, stability, seed, lang):
    return cache_key(t=text, v=voice, m=model, s=el_settings(model, stability), seed=seed, l=lang)


def el_synth(text, voice, model, stability, seed, lang):
    """One ElevenLabs request (cached). Returns (key, mp3, per-char times, fresh)."""
    key = el_key(text, voice, model, stability, seed, lang)
    d = CACHE / "elevenlabs"
    mp3, meta = d / f"{key}.mp3", d / f"{key}.json"
    fresh = not (mp3.exists() and meta.exists())
    if fresh:
        payload = {"text": text, "model_id": model, "voice_settings": el_settings(model, stability), "seed": seed}
        if lang.split("-")[0] != "en":
            payload["language_code"] = lang.split("-")[0]
        url = f"/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128"
        try:
            out = el_req(url, payload)
        except RuntimeError as e:
            if "language" not in str(e):
                raise
            payload.pop("language_code")
            out = el_req(url, payload)
        d.mkdir(parents=True, exist_ok=True)
        mp3.write_bytes(base64.b64decode(out["audio_base64"]))
        meta.write_text(json.dumps({"text": text, "voice": voice, "model": model, "seed": seed, "lang": lang,
                                    "alignment": out.get("alignment") or out.get("normalized_alignment")}, ensure_ascii=False))
    al = json.loads(meta.read_text())["alignment"]
    return key, mp3, el_times(text, al), fresh


def el_times(text, al):
    """Character alignment -> per-character ms (maps by difflib if the service normalised the text)."""
    chars = "".join(al["characters"])
    if chars == text:
        idx = list(range(len(text)))
    else:
        mp = {}
        for op, i1, i2, j1, _ in difflib.SequenceMatcher(a=text, b=chars, autojunk=False).get_opcodes():
            if op == "equal":
                mp.update({i1 + k: j1 + k for k in range(i2 - i1)})
        idx = [mp.get(i) for i in range(len(text))]
    st, en = al["character_start_times_seconds"], al["character_end_times_seconds"]
    times, last = [], (0, 0)
    for j in idx:
        if j is not None:
            last = (round(st[j] * 1000), round(en[j] * 1000))
        times.append(last)
    return times


# ================================================================ edge-tts
def edge_synth(text, cfg, lang):
    """Free Edge neural voice (cached). Returns (key, mp3, per-char times, fresh)."""
    voice, rate, pitch = cfg["voice"], cfg.get("rate", "+0%"), cfg.get("pitch", "+0Hz")
    key = cache_key(t=text, v=voice, r=rate, p=pitch, b="edge")
    d = CACHE / "edge"
    mp3, meta = d / f"{key}.mp3", d / f"{key}.json"
    fresh = not (mp3.exists() and meta.exists())
    if fresh:
        d.mkdir(parents=True, exist_ok=True)
        src = d / f"{key}.txt"
        src.write_text(text)
        out = run_with(["edge-tts"], pathlib.Path(__file__).resolve(), ["_edge", str(src), voice, rate, pitch, str(mp3)])
        src.unlink()
        if not out["words"]:
            sys.exit(f"edge-tts returned no word boundaries for voice {voice}")
        meta.write_text(json.dumps({"text": text, "voice": voice, "words": out["words"]}, ensure_ascii=False))
    return key, mp3, char_times(text, json.loads(meta.read_text())["words"]), fresh


def _edge_worker(argv):
    """Runs inside the edge-tts environment; writes the mp3 and prints {"words": [[w, s, e], ...]}."""
    import asyncio

    import edge_tts
    src, voice, rate, pitch, out = argv
    text = pathlib.Path(src).read_text()

    async def go():
        try:  # edge-tts >= 7 emits SentenceBoundary unless asked for words
            comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
        except TypeError:
            comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        words = []
        with open(out, "wb") as f:
            async for ch in comm.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    words.append([ch["text"], ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7])
        return words

    print(json.dumps({"words": asyncio.run(go())}, ensure_ascii=False))


# ================================================================ recorded
def recorded_take(cut, scene_id, text, lang, cfg):
    """User narration + faster-whisper word timings (cached by audio bytes + script)."""
    found = [p for ext in ("wav", "mp3", "m4a", "flac") if (p := ROOT / "recordings" / cut / f"{scene_id}.{ext}").exists()]
    if not found:
        sys.exit(f"missing recording: recordings/{cut}/{scene_id}.wav|mp3|m4a|flac")
    audio = found[0]
    model = cfg.get("whisperModel", "small")
    key = cache_key(a=hashlib.sha256(audio.read_bytes()).hexdigest(), t=text, m=model, b="recorded")
    meta = CACHE / "recorded" / f"{key}.json"
    fresh = not meta.exists()
    if fresh:
        import voice_qa
        print(f"   transcribing {audio.relative_to(ROOT)} with faster-whisper ({model}) ...")
        res = voice_qa.whisper(audio, lang, model, prompt=text)
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(json.dumps(res, ensure_ascii=False))
    res = json.loads(meta.read_text())
    return key, audio, char_times(text, res["words"]), fresh, res


# ================================================================ gpt-sovits (any GPT-SoVITS api_v2 server)
GS_PARAMS = {"top_k": 5, "top_p": 0.8, "temperature": 0.7, "text_split_method": "cut1", "speed_factor": 1.0,
             "repetition_penalty": 1.35, "batch_size": 1, "split_bucket": False, "parallel_infer": True,
             "fragment_interval": 0.3}
_tunnel = None


def gs_up(url) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/docs", timeout=4) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def gs_ensure(cfg):
    """Make the server reachable at cfg.url. If it is not and cfg.ssh is set: run cfg.startCmd on that host
    (idempotent; it should start the server only if needed) and open our own tunnel, closed when vo.py exits.
    Another process's tunnel on the same port is reused as is."""
    global _tunnel
    import atexit
    import time
    url = cfg.get("url", "http://127.0.0.1:9880").rstrip("/")
    if gs_up(url):
        return url
    host = cfg.get("ssh")
    if not host:
        sys.exit(f"GPT-SoVITS server not reachable at {url} (start it, or set voices.<cut>.ssh / startCmd)")
    if cfg.get("startCmd"):
        print(f"   starting server: ssh {host} {cfg['startCmd']}")
        r = subprocess.run(["ssh", host, cfg["startCmd"]], capture_output=True, text=True, timeout=600)
        print("   " + (r.stdout.strip().splitlines() or ["(no output)"])[-1])
        if r.returncode:
            sys.exit(f"startCmd failed:\n{r.stdout[-800:]}{r.stderr[-800:]}")
    port = int(url.rsplit(":", 1)[1].split("/")[0])
    if _tunnel is not None and _tunnel.poll() is None:
        _tunnel.terminate()
    _tunnel = subprocess.Popen(["ssh", "-N", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
                                "-L", f"{port}:127.0.0.1:{cfg.get('remotePort', port)}", host],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    atexit.register(lambda: _tunnel.poll() is None and _tunnel.terminate())
    for _ in range(40):
        if gs_up(url):
            return url
        time.sleep(0.5)
    sys.exit(f"GPT-SoVITS server still not reachable at {url} after starting it and opening a tunnel to {host}")


def gs_request(cfg, text, lang, seed) -> dict:
    """The api_v2 /tts payload: defaults < cfg.params; reference audio and prompt are paths on the server."""
    if not cfg.get("refAudio"):
        sys.exit("voices.<cut>.refAudio (reference wav path on the server) is required for gpt-sovits")
    lang2 = lang.split("-")[0]
    return {**GS_PARAMS, **cfg.get("params", {}), "text": text, "text_lang": cfg.get("textLang", lang2),
            "ref_audio_path": cfg["refAudio"], "prompt_text": cfg.get("promptText", ""),
            "prompt_lang": cfg.get("promptLang", lang2), "aux_ref_audio_paths": cfg.get("auxRefAudio", []),
            "seed": seed if seed is not None else -1, "media_type": "wav", "streaming_mode": False}


def asr_engine(cfg, backend, asr_flag):
    """Which ASR checks a take. ElevenLabs: Scribe (bills the same account) only when the voice asks for it with
    "asrEngine": "scribe"; by default the free local faster-whisper. "asrEngine": "none" skips the check."""
    e = cfg.get("asrEngine")
    if e:
        return None if e == "none" else e
    return "whisper" if backend == "elevenlabs" or asr_flag else None


def gs_synth(text, cfg, lang, seed):
    """One GPT-SoVITS take (cached) + local faster-whisper words for timing and QA.
    Returns (key, wav, per-char times, fresh, asr_result)."""
    req = gs_request(cfg, text, lang, seed)
    model = cfg.get("whisperModel", "medium")
    key = cache_key(r={k: v for k, v in req.items() if k != "media_type"}, m=cfg.get("model", ""), b="gpt-sovits")
    d = CACHE / "gpt-sovits"
    wav, meta = d / f"{key}.wav", d / f"{key}.{model}.json"
    fresh = not wav.exists()
    if fresh:
        url = gs_ensure(cfg)
        body = json.dumps(req, ensure_ascii=False).encode()
        for attempt in (1, 2, 3):
            try:
                r = urllib.request.Request(f"{url}/tts", data=body, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(r, timeout=max(120, len(text) * 2)) as f:
                    data = f.read()
                break
            except urllib.error.HTTPError as e:
                sys.exit(f"GPT-SoVITS HTTP {e.code}: {e.read()[:400].decode(errors='replace')}")
            except (urllib.error.URLError, OSError, http.client.HTTPException):  # incl. IncompleteRead
                if attempt == 3:
                    raise
                time.sleep(5 * attempt)
                url = gs_ensure(cfg)  # e.g. a borrowed tunnel went away mid-response
        if data[:4] != b"RIFF":
            sys.exit(f"GPT-SoVITS returned no WAV: {data[:200]!r}")
        d.mkdir(parents=True, exist_ok=True)
        wav.write_bytes(data)
    if not meta.exists():
        import voice_qa
        res = voice_qa.whisper(wav, lang, model)  # neutral prompt: transcript doubles as an independent check
        meta.write_text(json.dumps(res, ensure_ascii=False))
    res = json.loads(meta.read_text())
    if dur_s(wav) > max(8.0, 0.45 * len(re.sub(r"\s", "", text))):
        print(f"   WARNING {key}: {dur_s(wav):.0f}s audio for {len(text)} chars - the model probably ran on "
              f"(repeated or invented speech); its ASR error will show it")
    return key, wav, char_times(text, res["words"]), fresh, res


# ================================================================ fish (Fish Audio HTTP API, fishaudio.org)
FISH_API = "https://fishaudio.org/api/open"


def fish_req(cfg, path, payload=None, timeout=60):
    """One Fish Audio request. JSON in, (bytes, headers) out. HTTP errors -> RuntimeError with the status
    (the key is only ever sent in the Authorization header)."""
    key = env_key(cfg.get("keyEnv", "FISH_API_KEY"))
    r = urllib.request.Request(cfg.get("url", FISH_API).rstrip("/") + path,
                               data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None,
                               headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                               method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as f:
            return f.read(), f.headers
    except urllib.error.HTTPError as e:
        err = RuntimeError(f"Fish Audio HTTP {e.code} on {path}: {e.read()[:400].decode(errors='replace')}")
        err.status = e.code
        raise err from None


def fish_cmd(cfg, args, payload=None):
    """`voices.<cut>.synthCmd` (a list, run from the project folder): an external helper that does the synthesis instead of
    the HTTP API - e.g. one that goes through a logged-in browser session for a plan the API does not bill. Called as
    `<cmd> quota` -> {"remaining": n} and `<cmd> tts <out>` with the request JSON on stdin -> {"creditsUsed": n}."""
    r = subprocess.run([*cfg["synthCmd"], *args], input=json.dumps(payload, ensure_ascii=False) if payload else None,
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        raise RuntimeError(f"synthCmd {' '.join(args[:1])} failed: {r.stderr.strip()[-400:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def fish_quota(cfg):
    """API credits left (a separate balance from the website's membership credits), or the helper's balance."""
    if cfg.get("synthCmd"):
        q = fish_cmd(cfg, ["quota"])
        return q.get("remaining", 0), {"credits": q.get("remaining", "-")}
    data, _ = fish_req(cfg, "/v1/profile")
    p = json.loads(data)
    return p.get("api_quota_remaining", 0), p


def fish_cost(text, cfg) -> float:
    """Billable credits of one request: CJK characters 1, every other character (punctuation, latin, spaces) 0.5, rounded
    up per request (the published API rule, matched to X-OpenAPI-Credits-Used; some models bill at a multiple:
    voices.<cut>.creditsPerChar)."""
    n_cjk = len(CJK.findall(text))
    return math.ceil((n_cjk + 0.5 * (len(text) - n_cjk)) * cfg.get("creditsPerChar", 1.0))


def fish_request(cfg, text, lang) -> dict:
    if not cfg.get("voice"):
        sys.exit("voices.<cut>.voice (a Fish Audio voiceId) is required for the fish backend")
    req = {"text": text, "voiceId": cfg["voice"], "modelId": cfg.get("model", "fishaudio-s21pro"),
           "format": cfg.get("format", "wav"), "language": cfg.get("language", lang.split("-")[0])}
    if cfg.get("instruction"):
        req["instruction"] = cfg["instruction"]
    return {**req, **cfg.get("params", {})}


def fish_key(cfg, text, lang, seed):
    return cache_key(r=fish_request(cfg, text, lang), seed=seed, b="fish")


def fish_synth(text, cfg, lang, seed):
    """One Fish Audio take (cached) + local faster-whisper words for timing and QA. The API has no seed: `seed` only
    labels the take (and keys the cache), so a take is reproducible from the cache, never from the API.
    Returns (key, audio, per-char times, fresh, asr_result, credits_used)."""
    req = fish_request(cfg, text, lang)
    model = cfg.get("whisperModel", "medium")
    key = fish_key(cfg, text, lang, seed)
    d = CACHE / "fish"
    audio, meta, asr_path = d / f"{key}.{req['format']}", d / f"{key}.json", d / f"{key}.{model}.json"
    fresh, used = not audio.exists(), 0.0
    if fresh:
        for attempt in (1, 2, 3):
            if cfg.get("synthCmd"):
                d.mkdir(parents=True, exist_ok=True)
                try:
                    res_cmd = fish_cmd(cfg, ["tts", str(audio)], req)
                    data, h = audio.read_bytes(), {"Content-Type": "audio/" + req["format"],
                                                   "X-OpenAPI-Credits-Used": res_cmd.get("creditsUsed", 0)}
                    break
                except RuntimeError as e:
                    if attempt == 3:
                        sys.exit(str(e))
                    time.sleep(10 * attempt)
                    continue
            try:
                data, h = fish_req(cfg, "/v3/speech/tts", req, timeout=max(120, len(text) * 2))
                break
            except RuntimeError as e:
                status = getattr(e, "status", 0)
                if status == 402:
                    sys.exit(f"ABORT: Fish Audio says the API credits are used up ({e})")
                if status not in (429, 500, 502, 503, 504) or attempt == 3:
                    sys.exit(str(e))
            except (urllib.error.URLError, OSError, http.client.HTTPException):
                if attempt == 3:
                    raise
            time.sleep(5 * attempt)
        if not h.get("Content-Type", "").startswith("audio/"):
            sys.exit(f"Fish Audio returned no audio: {data[:200]!r}")
        used = float(h.get("X-OpenAPI-Credits-Used") or 0)
        ignored = h.get("X-OpenAPI-Ignored-Parameters")
        if ignored:
            print(f"   NOTE {key}: the API ignored {ignored} for model {req['modelId']}")
        d.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(data)
        meta.write_text(json.dumps({"request": {k: v for k, v in req.items() if k != "text"}, "seed": seed, "creditsUsed": used,
                                    "ignored": ignored, "quotaRemaining": h.get("X-OpenAPI-Quota-Remaining")}, ensure_ascii=False))
    if not asr_path.exists():
        import voice_qa
        res = voice_qa.whisper(audio, lang, model)  # neutral prompt: transcript doubles as an independent check
        asr_path.write_text(json.dumps(res, ensure_ascii=False))
    res = json.loads(asr_path.read_text())
    if dur_s(audio) > max(8.0, 0.45 * len(re.sub(r"\s", "", text))):
        print(f"   WARNING {key}: {dur_s(audio):.0f}s audio for {len(text)} chars - probably repeated or invented speech")
    return key, audio, char_times(text, res["words"]), fresh, res, used


# ================================================================ tokens
def tokenize(text, times=None):
    """Caption tokens: latin words / numbers, single CJK characters. Punctuation sticks to the
    neighbouring token; [tags] are skipped. Returns dicts with w, sp (preceded by a space),
    c0/c1 (char span) and, if times are given, startMs/endMs of the token's letters."""
    toks, cur, pending, space = [], None, "", False
    i, n = 0, len(text)

    def close():
        nonlocal cur
        if cur is not None:
            toks.append(cur)
            cur = None

    while i < n:
        ch = text[i]
        if ch == "[" and (j := text.find("]", i)) != -1:
            close()
            i = j + 1
            continue
        is_num_sep = ch in ".,:" and 0 < i < n - 1 and text[i - 1].isdigit() and text[i + 1].isdigit()
        if ch.isspace():
            close()
            space = True
        elif CJK.match(ch):
            close()
            cur = {"w": pending + ch, "sp": space, "c0": i, "c1": i + 1}
            if times:
                cur["startMs"], cur["endMs"] = times[i]
            close()
            pending, space = "", False
        elif ch.isalnum() or ch in "'’-%" or is_num_sep:
            if cur is None:
                cur = {"w": pending + ch, "sp": space, "c0": i, "c1": i + 1}
                if times:
                    cur["startMs"], cur["endMs"] = times[i]
                pending, space = "", False
            else:
                cur["w"] += ch
                cur["c1"] = i + 1
                if times:
                    cur["endMs"] = times[i][1]
        elif ch in OPENERS:
            close()
            pending += ch
        elif cur is not None:
            cur["w"] += ch
        elif toks:
            toks[-1]["w"] += ch
        i += 1
    close()
    return toks


def key_of(w):
    return re.sub(r"[^\w]", "", w.lower())


def align_display(display_toks, tts_toks):
    """Give caption (text) tokens the timings of the spoken (tts) tokens via sequence alignment."""
    a = [key_of(t["w"]) for t in display_toks]
    b = [key_of(t["w"]) for t in tts_toks]
    out = [dict(t) for t in display_toks]
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                out[i1 + k]["startMs"], out[i1 + k]["endMs"] = tts_toks[j1 + k]["startMs"], tts_toks[j1 + k]["endMs"]
        elif op == "replace":
            s0, s1 = tts_toks[j1]["startMs"], tts_toks[j2 - 1]["endMs"]
            lens = [max(1, len(a[i])) for i in range(i1, i2)]
            tot, acc = sum(lens), 0
            for k, L in enumerate(lens):
                out[i1 + k]["startMs"] = round(s0 + (s1 - s0) * acc / tot)
                acc += L
                out[i1 + k]["endMs"] = round(s0 + (s1 - s0) * acc / tot)
        elif op == "delete":
            t = tts_toks[j1 - 1]["endMs"] if j1 > 0 else (tts_toks[0]["startMs"] if tts_toks else 0)
            for k in range(i1, i2):
                out[k]["startMs"] = out[k]["endMs"] = t
    last = 0
    for t in out:
        if "startMs" not in t:
            t["startMs"] = t["endMs"] = last
        last = t["endMs"]
    return out


def find_anchor(text, disp, words, target):
    """Latin target: first token equal to it (else prefix). CJK / other: substring -> covering token."""
    k = key_of(target)
    if not CJK.search(target):
        for d, w in zip(disp, words):
            if key_of(d["w"]) == k:
                return w["startMs"]
        for d, w in zip(disp, words):
            if key_of(d["w"]).startswith(k):
                return w["startMs"]
    pos = text.find(target)
    if pos < 0:
        return None
    return next((w["startMs"] for d, w in zip(disp, words) if d["c1"] > pos), None)


def lines_json(scene_id, lines, per_line):
    """Caption words + anchors per line, in the vo.<cut>.json v2 format."""
    out = []
    for l, toks in zip(lines, per_line):
        disp = tokenize(l["text"])
        words = align_display(disp, toks) if toks else disp
        anchors = {}
        for name, w in (l.get("anchors") or {}).items():
            hit = find_anchor(l["text"], disp, words, w)
            if hit is None:
                print(f"   ! anchor '{name}' -> '{w}' not found in {scene_id}.{l['id']}")
                continue
            anchors[name] = hit
        out.append({"id": l["id"], "text": l["text"],
                    "startMs": words[0].get("startMs", 0) if words else 0, "endMs": words[-1].get("endMs", 0) if words else 0,
                    "words": [{"w": w["w"], "startMs": w.get("startMs", 0), "endMs": w.get("endMs", 0), "sp": 1 if w.get("sp") else 0}
                              for w in words],
                    "anchors": anchors})
    return out


# ================================================================ audio processing
def silences(path, noise_db=-40, min_d=0.12):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", f"silencedetect=noise={noise_db}dB:d={min_d}",
                        "-f", "null", "-"], capture_output=True, text=True)
    out, cur = [], None
    for line in r.stderr.splitlines():
        if m := re.search(r"silence_start: (-?[0-9.]+)", line):
            cur = max(0.0, float(m.group(1)))
        if (m := re.search(r"silence_end: ([0-9.]+)", line)) and cur is not None:
            out.append((cur, float(m.group(1))))
            cur = None
    if cur is not None:
        out.append((cur, dur_s(path)))
    return out


def edit_audio(src, dst, cuts, inserts):
    """Remove `cuts` [(a, b)] and insert silence `inserts` [(t, secs)] (original-timeline seconds).
    Writes mono 44.1 kHz WAV and returns remap(sec) from the original to the edited timeline."""
    dur = dur_s(src)
    events = sorted([(a, "cut", b) for a, b in cuts] + [(t, "ins", s) for t, s in inserts])
    segs, t = [], 0.0
    for at, kind, val in events:
        if at > t:
            segs.append(("a", t, at))
        if kind == "cut":
            t = max(t, val)
        else:
            t = max(t, at)
            segs.append(("s", val, None))
    if t < dur:
        segs.append(("a", t, dur))
    parts = [f"[0:a]atrim={x:.4f}:{y:.4f},asetpts=PTS-STARTPTS[p{i}]" if k == "a" else
             f"anullsrc=r=44100:cl=mono,atrim=0:{x:.4f},asetpts=PTS-STARTPTS[p{i}]" for i, (k, x, y) in enumerate(segs)]
    fc = ";".join(parts) + ";" + "".join(f"[p{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=0:a=1[out]"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-filter_complex", fc, "-map", "[out]",
                    "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(dst)], check=True)

    def remap(sec):
        shift = 0.0
        for at, kind, val in events:
            if kind == "cut":
                if sec >= val:
                    shift -= val - at
                elif sec > at:
                    shift -= sec - at
            elif sec >= at:
                shift += val
        return sec + shift

    return remap


def polish(src, dst):
    """Standard VO polish: rumble high-pass + gentle 2.5:1 compression (keeps expressive peaks from
    jumping out over the music) + a little presence."""
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af",
                    "highpass=f=70,acompressor=threshold=-24dB:ratio=2.5:attack=8:release=120:makeup=1.5,"
                    "equalizer=f=3500:t=q:w=1.0:g=1.5", "-c:a", "pcm_s16le", str(dst)], check=True)


def line_offsets(text, lines):
    offs, pos = [], 0
    for l in lines:
        s = text.find(l["say"], pos)
        offs.append((s, s + len(l["say"])))
        pos = s + len(l["say"])
    return offs


def process_take(scene_id, lines, text, times, audio, workdir, cfg, tighten=True):
    """Tighten + gaps + tempo + polish + normalise one take. Returns (final_mp3, lines_json, durationMs).

    Graded pauses: the longest silence allowed depends on what the script says there
    (plain word gap 0.2 s < comma 0.28 < sentence 0.45 < sentence + new line 0.5 < ellipsis 0.55),
    scaled by cfg.pauseScale. Breaths (above -50 dB) survive. `pauseAfterMs` on a line then
    guarantees a minimum gap after it."""
    tempo, pause_scale = cfg.get("tempo", 1.0), cfg.get("pauseScale", 1.0)
    offs = line_offsets(text, lines)
    all_toks = tokenize(text, times)
    per_line = [[t for t in all_toks if a <= t["c0"] < b] for a, b in offs]
    spoken = [i for i, ch in enumerate(text) if ch.isalnum() or CJK.match(ch)]
    line_starts = {a for a, _ in offs}

    def allowed_pause(a_sec):
        before = [i for i in spoken if times[i][1] <= a_sec * 1000 + 60]
        if not before:
            return cfg.get("maxPause", MAX_PAUSE)
        i = before[-1]
        nxt = next((j for j in spoken if j > i), None)
        gap = text[i + 1:nxt] if nxt is not None else text[i + 1:]
        new_line = nxt is not None and any(i < ls <= nxt for ls in line_starts)
        if "..." in gap or "…" in gap:
            cap = 0.55
        elif any(c in gap for c in ".!?。！？"):
            cap = 0.5 if new_line else 0.45
        elif "[" in gap:
            cap = 0.45
        elif any(c in gap for c in ",;:，；：、—–"):
            cap = 0.28
        else:
            cap = 0.2
        return cap * pause_scale

    dur = dur_s(audio)
    cuts = []
    for a, b in silences(audio, noise_db=-50):
        if a <= 0.01:
            if b - EDGE_KEEP > 0.02:
                cuts.append((0.0, b - EDGE_KEEP))
        elif b >= dur - 0.01:
            if dur - (a + EDGE_KEEP) > 0.02:
                cuts.append((a + EDGE_KEEP, dur))
        elif tighten and b - a > (cap := allowed_pause(a)):
            cuts.append((a + cap / 2, b - cap / 2))

    def tight(sec):
        shift = 0.0
        for a, b in cuts:
            if sec >= b:
                shift -= b - a
            elif sec > a:
                shift -= sec - a
        return sec + shift

    inserts = []
    for i, l in enumerate(lines[:-1]):
        want = l.get("pauseAfterMs")
        if not want or not per_line[i] or not per_line[i + 1]:
            continue
        e, s = per_line[i][-1]["endMs"] / 1000, per_line[i + 1][0]["startMs"] / 1000
        gap = tight(s) - tight(e)
        if gap * 1000 < want:
            mid = (e + s) / 2
            for a, b in cuts:  # keep the insert point outside any cut region
                if a < mid < b:
                    mid = a
            inserts.append((mid, (want / 1000) * tempo - gap))
    wav = workdir / f"{scene_id}.wav"
    remap = edit_audio(audio, wav, cuts, inserts)
    for toks in per_line:
        for t in toks:
            t["startMs"] = round(remap(t["startMs"] / 1000) * 1000 / tempo)
            t["endMs"] = round(remap(t["endMs"] / 1000) * 1000 / tempo)
    if abs(tempo - 1.0) > 1e-3:
        fast = workdir / f"{scene_id}_tempo.wav"
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav), "-af", f"atempo={tempo:.4f}",
                        "-c:a", "pcm_s16le", str(fast)], check=True)
        wav = fast
    polished = workdir / f"{scene_id}_polish.wav"
    polish(wav, polished)
    final = workdir / f"{scene_id}.mp3"
    normalise(polished, final, cfg.get("targetLufs", TARGET_LUFS))
    return final, lines_json(scene_id, lines, per_line), round(dur_s(final) * 1000)


# ================================================================ QA + picking
def qa_take(key, audio, text, lang, f0max, asr_engine=None, asr_result=None):
    """Prosody always; ASR score when an engine is given (or an existing transcript is passed)."""
    import voice_qa
    qa_path = CACHE / "qa" / f"{key}.{asr_engine or 'p'}.json"
    if qa_path.exists():
        return json.loads(qa_path.read_text())
    r = voice_qa.prosody(audio, fmax=f0max)
    if asr_result is None and asr_engine:
        asr_result = voice_qa.asr(audio, lang, asr_engine)
    if asr_result is not None:
        r |= voice_qa.score(text, lang, asr_result)
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    qa_path.write_text(json.dumps(r, ensure_ascii=False))
    return r


def steady_reference(cut, exclude, current=()):
    """Median pitch variation (semitones) of the picked takes of the other scenes
    (this run's picks first, else the cut's last report)."""
    rep_path = ROOT / "notes" / f"vo_report.{cut}.json"
    rows = list(current) or (json.loads(rep_path.read_text()) if rep_path.exists() else [])
    vals = sorted(t["qa"]["f0StdSt"] for r in rows if r["scene"] != exclude for t in r["takes"]
                  if t["seed"] == r["picked"] and t["qa"].get("f0StdSt"))
    return vals[len(vals) // 2] if vals else 4.5


def missing_terms(take, terms, spoken):
    """Key terms (names, the paper's core term) the ASR transcript lost: a misread like Qwen -> "queen" or
    千问 -> 千万 changes the meaning while barely moving the overall error rate. A term lists its accepted
    spellings separated by "|" ("Qwen|千问", or "熵|商" when tts respells a rare character); the number of
    occurrences in the spoken text (tts) is compared with the transcript."""
    asr = take["qa"].get("asr")
    if asr is None or not terms:
        return []
    asr, spoken = asr.lower(), spoken.lower()
    out = []
    for term in terms:
        alts = [a.lower() for a in term.split("|") if a]
        want = sum(spoken.count(a) for a in alts)
        if want and sum(asr.count(a) for a in alts) < want:
            out.append(term.split("|")[0])
    return out


def pick(takes, block, cut, scene_id, report, manual):
    """Manual pick wins. Else: fewest lost key terms, then accurate (ASR error within 0.02 of the best take), then
    expressive but not slow (one extra second must buy >= 0.8 semitones of pitch variation).
    `"pick": "steady"`: the take closest to the cut's typical expressiveness instead."""
    if manual is not None and any(t["seed"] == manual for t in takes):
        return next(t for t in takes if t["seed"] == manual)
    if len(takes) == 1:
        return takes[0]
    m0 = min(len(t.get("missing", [])) for t in takes)
    takes = [t for t in takes if len(t.get("missing", [])) == m0]
    e0 = min(t["qa"].get("err", 0) for t in takes)
    ok = [t for t in takes if t["qa"].get("err", 0) <= e0 + 0.02]
    d0 = min(t["durationMs"] for t in ok)
    if block.get("pick") == "steady":
        ref = steady_reference(cut, scene_id, report)
        return min(ok, key=lambda t: abs(t["qa"].get("f0StdSt", ref) - ref))
    return max(ok, key=lambda t: t["qa"].get("f0StdSt", 0) - 0.8 * (t["durationMs"] - d0) / 1000)


# ================================================================ commands
def prepare_lines(block, strip):
    """Lines with `say`: the string actually spoken (tts, falling back to text; tags stripped if needed)."""
    return [dict(l, say=strip_tags(l.get("tts", l["text"])) if strip else l.get("tts", l["text"])) for l in block["lines"]]


def log_paid(line):
    (ROOT / "notes").mkdir(exist_ok=True)
    with (ROOT / "notes" / "tts_log.md").open("a") as f:
        f.write(f"- {dt.datetime.now().isoformat(timespec='seconds')} {line}\n")


def build(args):
    script = load_script()
    cut = args.lang
    if cut not in script.get("voices", {}):
        sys.exit(f"scenes.json has no voices.{cut}")
    cfg = dict(script["voices"][cut])
    backend = args.backend or cfg.get("backend", "elevenlabs")
    tl = cfg.get("lang", cut)  # text language: a variant cut can read another cut's text with its own voice
    if backend != "none":
        reexec_with(["numpy"])
    voice, model, stability = args.voice or cfg.get("voice"), args.model or cfg.get("model", "eleven_v4"), cfg.get("stability", 0.5)
    seeds = [int(x) for x in args.seeds.split(",")] if args.seeds else cfg.get("seeds", DEFAULT_SEEDS)[: args.takes]
    defaults = script.get("defaults", {})
    only = set(args.scene.split(",")) if args.scene else None
    scenes = [s for s in script["scenes"] if tl in s and (only is None or s["id"] in only)]
    if only and (missing := only - {s["id"] for s in scenes}):
        sys.exit(f"unknown scene ids for {tl}: {', '.join(sorted(missing))}")
    picks_path = ROOT / "notes" / f"vo_picks.{cut}.json"
    picks = json.loads(picks_path.read_text()) if picks_path.exists() else {}
    strip = backend != "elevenlabs"
    tighten = args.tighten if args.tighten is not None else cfg.get("tighten", backend != "recorded")

    # a manual pick is always part of its scene's pool, so a plain rebuild keeps it
    pool = {sc["id"]: (seeds + ([picks[sc["id"]]] if picks.get(sc["id"]) is not None and picks[sc["id"]] not in seeds else []))
            if backend in ("elevenlabs", "gpt-sovits", "fish") else [None] for sc in scenes}
    print(f"[batch] cut={cut} text={tl} backend={backend} scenes={len(scenes)} voice={voice or '-'}")
    # anchors are matched in the caption `text` (not in `tts`): check before any audio is made
    bad = []
    for sc in scenes:
        for l in sc[tl]["lines"]:
            toks = [key_of(t) for t in re.split(r"\s+", l["text"]) if t]
            for name, target in (l.get("anchors") or {}).items():
                ok = target in l["text"] if CJK.search(target) or not target.strip() else any(t.startswith(key_of(target)) for t in toks) or target in l["text"]
                if not ok:
                    bad.append(f"{sc['id']}.{l['id']} {name} -> {target!r}")
    if bad:
        print("[anchors] not found in the caption text (anchors must be words of `text`, e.g. digits as written there, "
              "not the `tts` spelling):\n  " + "\n  ".join(bad))
        if backend in ("elevenlabs", "fish") and not args.dry_run:
            sys.exit("fix the anchors first (nothing was generated)")
    remaining = None
    if backend == "elevenlabs":
        if not voice:
            sys.exit(f"voices.{cut}.voice (an ElevenLabs voice id) is required")
        todo, chars = [], 0
        for sc in scenes:
            text = " ".join(l["say"] for l in prepare_lines(sc[tl], strip))
            for seed in pool[sc["id"]]:
                if not (CACHE / "elevenlabs" / f"{el_key(text, voice, model, stability, seed, tl)}.mp3").exists():
                    todo.append((sc["id"], seed))
                    chars += len(text)
        billable = round(chars * COST.get(model, 1.0))
        remaining, sub = el_quota()
        print(f"[quota] remaining={remaining} / {sub['character_limit']}")
        print(f"[estimate] takes/scene={len(seeds)} new_requests={len(todo)} chars={chars} est_billable={billable} "
              f"model={model} stability={stability}")
        if billable > remaining:
            sys.exit("ABORT: batch would exceed the remaining subscription quota")
    elif backend == "fish":
        todo, credits = 0, 0.0
        for sc in scenes:
            text = " ".join(l["say"] for l in prepare_lines(sc[tl], strip))
            for seed in pool[sc["id"]]:
                if not (CACHE / "fish" / f"{fish_key(cfg, text, tl, seed)}.{fish_request(cfg, text, tl)['format']}").exists():
                    todo += 1
                    credits += fish_cost(text, cfg)
        remaining, prof = fish_quota(cfg)
        print(f"[quota] Fish Audio API credits remaining={remaining} (membership credits, website only: {prof.get('credits', '-')})")
        print(f"[estimate] takes/scene={len(seeds)} new_requests={todo} est_credits={credits:.0f} model={cfg.get('model', 'fishaudio-s21pro')}")
        if credits > remaining:
            sys.exit("ABORT: batch would exceed the remaining Fish Audio API credits")
    est = estimate_length(scenes, tl, cfg, defaults, strip)
    print(f"[length] ≈ {est // 60:.0f}:{est % 60:02.0f} from reading speed (check it against the planned length; "
          f"trim filler, not explanation, before paying for voice)")
    if args.dry_run:
        return

    work = CACHE / "work" / cut
    work.mkdir(parents=True, exist_ok=True)
    out_audio = ROOT / "public" / "audio" / cut
    vo_path = ROOT / "public" / "data" / f"vo.{cut}.json"
    vo_path.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(vo_path.read_text()) if vo_path.exists() else {}
    keep = {s["id"]: s for s in old.get("scenes", [])} if old.get("version") == 2 else {}
    report, new_requests, spent = [], 0, 0.0
    for sc in scenes:
        block = sc[tl]
        lines = prepare_lines(block, strip)
        text = " ".join(l["say"] for l in lines)
        terms = cfg.get("keyTerms", []) + block.get("keyTerms", [])
        takes = []
        if backend == "none":
            times, dms = reading_times(lines, cfg)
            per_line = [[t for t in tokenize(text, times) if a <= t["c0"] < b] for a, b in line_offsets(text, lines)]
            takes.append({"seed": None, "final": None, "lines": lines_json(sc["id"], lines, per_line), "durationMs": dms, "qa": {},
                          "fresh": False})
        for seed in pool[sc["id"]] if backend != "none" else []:
            asr_result = None
            if backend == "elevenlabs":
                key, audio, times, fresh = el_synth(text, voice, model, stability, seed, tl)
            elif backend == "edge":
                key, audio, times, fresh = edge_synth(text, cfg, tl)
            elif backend == "gpt-sovits":
                key, audio, times, fresh, asr_result = gs_synth(text, cfg, tl, seed)
            elif backend == "fish":
                key, audio, times, fresh, asr_result, used = fish_synth(text, cfg, tl, seed)
                spent += used
            else:
                key, audio, times, fresh, asr_result = recorded_take(cut, sc["id"], text, tl, cfg)
            new_requests += fresh
            wd = work / f"{sc['id']}_{seed if seed is not None else backend}"
            wd.mkdir(exist_ok=True)
            final, lj, dms = process_take(sc["id"], lines, text, times, audio, wd, cfg, tighten)
            engine = asr_engine(cfg, backend, args.asr and asr_result is None)
            q = qa_take(key, audio, text, tl, cfg.get("f0Max", 420.0), engine, asr_result)
            takes.append({"seed": seed, "final": final, "lines": lj, "durationMs": dms, "qa": q, "fresh": fresh,
                          "missing": missing_terms({"qa": q}, terms, strip_tags(text))})
        best = pick(takes, {"pick": block.get("pick", sc.get("pick"))}, cut, sc["id"], report, picks.get(sc["id"]))
        for t in takes:
            q = t["qa"]
            print(f" {'*' if t is best else ' '} {sc['id']:16} seed={str(t['seed']):<4} {t['durationMs'] / 1000:5.1f}s "
                  f"err={q.get('err', '-')} f0std={q.get('f0StdSt', '-')} range={q.get('f0Range90St', '-')} "
                  f"events={q.get('events', [])} {'silent' if backend == 'none' else 'new' if t['fresh'] else 'cached'}"
                  + (f" LOST-TERMS={t['missing']}" if t.get("missing") else ""))
            for d in q.get("diffs", [])[:4]:
                print(f"      {d}")
        if best["final"]:
            out_audio.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(best["final"], out_audio / f"{sc['id']}.mp3")
        keep[sc["id"]] = {"id": sc["id"], "audio": f"audio/{cut}/{sc['id']}.mp3" if best["final"] else None,
                          "durationMs": best["durationMs"], "seed": best["seed"],
                          "minSeconds": block.get("minSeconds", sc.get("minSeconds", 0)),
                          "leadInMs": block.get("leadInMs", sc.get("leadInMs", defaults.get("leadInMs", 250))),
                          "tailMs": block.get("tailMs", sc.get("tailMs", defaults.get("tailMs", 350))),
                          "lines": best["lines"]}
        report.append({"scene": sc["id"], "picked": best["seed"],
                       "takes": [{k: v for k, v in t.items() if k in ("seed", "durationMs", "qa", "missing")} for t in takes]})
    order = [s["id"] for s in script["scenes"] if tl in s]
    vo = {"version": 2, "meta": {"lang": cut, "textLang": tl, "backend": backend, "voice": voice, "model": model if backend == "elevenlabs" else cfg.get("model") if backend in ("gpt-sovits", "fish") else None,
                                 "tempo": cfg.get("tempo", 1.0), "generated": dt.datetime.now().isoformat(timespec="seconds")},
          "scenes": [keep[i] for i in order if i in keep]}
    vo["meta"]["estimatedTotalMs"] = sum(max(s["minSeconds"] * 1000, s["leadInMs"] + s["durationMs"] + s["tailMs"]) for s in vo["scenes"])
    vo_path.write_text(json.dumps(vo, ensure_ascii=False, indent=1))
    rep_path = ROOT / "notes" / f"vo_report.{cut}.json"
    rep_path.parent.mkdir(exist_ok=True)
    merged = {r["scene"]: r for r in (json.loads(rep_path.read_text()) if rep_path.exists() else [])} | {r["scene"]: r for r in report}
    rep_path.write_text(json.dumps([merged[i] for i in order if i in merged], ensure_ascii=False, indent=1))
    if backend == "elevenlabs":
        remaining2, _ = el_quota()
        log_paid(f"build cut={cut} model={model} voice={voice} new_requests={new_requests} "
                 f"remaining_before={remaining} remaining_after={remaining2}")
        print(f"[quota] remaining {remaining2} (spent {remaining - remaining2} so far; the counter often lags — keep the books with the estimate above)")
    elif backend == "fish" and new_requests:
        remaining2, _ = fish_quota(cfg)
        log_paid(f"build cut={cut} backend=fish model={cfg.get('model', 'fishaudio-s21pro')} voice={voice} new_requests={new_requests} "
                 f"credits_used={spent:g} remaining_before={remaining} remaining_after={remaining2}")
        print(f"[quota] Fish Audio API credits remaining {remaining2} (this run used {spent:g})")
    missing = [i for i in order if i not in keep]
    # scenes kept from an earlier build (--scene) carry that build's caption text: flag edits made since
    script_text = {(s["id"], l["id"]): l["text"] for s in script["scenes"] if tl in s for l in s[tl]["lines"]}
    stale = [f"{s['id']}.{l['id']}" for s in vo["scenes"] for l in s["lines"] if script_text.get((s["id"], l["id"]), l["text"]) != l["text"]]
    if stale:
        print(f"[stale] caption text changed in scenes.json but not in this timeline: {', '.join(stale)} — "
              f"run a full build (cached takes, free; pin picks in notes/vo_picks.{cut}.json to keep the same audio)")
    print(f"[done] {vo_path.relative_to(ROOT)} total≈{vo['meta']['estimatedTotalMs'] / 1000:.1f}s"
          + (f"  (not built yet: {', '.join(missing)})" if missing else ""))


def audition(args):
    """Same text, several voices (and models): listenable files + QA numbers side by side."""
    script = load_script() if (ROOT / "scenes.json").exists() else {}
    backend = args.backend or script.get("voices", {}).get(args.lang, {}).get("backend", "elevenlabs")
    if backend not in ("elevenlabs", "edge"):
        sys.exit("audition supports the elevenlabs and edge backends")
    reexec_with(["numpy"])
    text = args.text or AUDITION_TEXT.get(args.lang.split("-")[0])
    if not text:
        sys.exit("give --text for this language")
    if backend == "edge":
        text = strip_tags(text)
    voices = [v.split("=", 1) if "=" in v else (v, v) for v in args.voices.split(",")]
    models = args.model.split(",") if backend == "elevenlabs" else ["edge"]
    remaining = None
    if backend == "elevenlabs":
        todo = [(n, v, m) for n, v in voices for m in models
                if not (CACHE / "elevenlabs" / f"{el_key(text, v, m, args.stability, args.seed, args.lang)}.mp3").exists()]
        billable = round(sum(len(text) * COST.get(m, 1.0) for _, _, m in todo))
        remaining, _ = el_quota()
        print(f"[quota] remaining={remaining}  [audition] {len(voices)} voices x {len(models)} models, new={len(todo)}, "
              f"chars/text={len(text)}, est_billable={billable}")
        if billable > remaining:
            sys.exit("ABORT: audition would exceed the remaining quota")
    if args.dry_run:
        return
    outdir = ROOT / "out" / "auditions"
    outdir.mkdir(parents=True, exist_ok=True)
    for name, v in voices:
        for m in models:
            if backend == "elevenlabs":
                key, mp3, _, _ = el_synth(text, v, m, args.stability, args.seed, args.lang)
            else:
                key, mp3, _, _ = edge_synth(text, {"voice": v, "rate": args.rate}, args.lang)
            dst = outdir / f"{args.lang}_{name}_{m.replace('eleven_', '')}.mp3"
            shutil.copyfile(mp3, dst)
            engine = asr_engine({}, backend, args.asr)
            q = qa_take(key, mp3, text, args.lang, args.f0max, engine)
            print(f"  {name:12} {m:26} {q['durationS']:5.1f}s f0med={q.get('f0MedianHz')} f0std={q.get('f0StdSt')} "
                  f"range={q.get('f0Range90St')} loudStd={q.get('loudStdDb')} pauses={q['pauses']} max={q['pauseMaxS']} "
                  f"err={q.get('err', '-')} events={q.get('events', [])}  -> {dst.relative_to(ROOT)}")
            for d in q.get("diffs", [])[:5]:
                print(f"      {d}")
    if backend == "elevenlabs":
        remaining2, _ = el_quota()
        log_paid(f"audition lang={args.lang} models={args.model} voices={args.voices} remaining_before={remaining} "
                 f"remaining_after={remaining2}")
        print(f"[quota] remaining {remaining2}")


def main():
    sys.stdout.reconfigure(line_buffering=True)  # progress visible in a redirected log (block-buffered otherwise)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build all (or some) scenes of one cut")
    b.add_argument("--lang", default="en", help="cut id = key in scenes.json voices (e.g. en, zh, zh_vertical)")
    b.add_argument("--backend", choices=["elevenlabs", "edge", "gpt-sovits", "fish", "recorded", "none"], help="override voices.<cut>.backend")
    b.add_argument("--voice", help="override voices.<cut>.voice")
    b.add_argument("--model", help="override voices.<cut>.model (elevenlabs)")
    b.add_argument("--scene", help="comma-separated scene ids (others keep their previous build)")
    b.add_argument("--seeds", help="comma-separated seeds, e.g. to widen one scene's pool (elevenlabs, gpt-sovits, fish)")
    b.add_argument("--takes", type=int, help="use only the first N configured seeds (elevenlabs, gpt-sovits, fish)")
    b.add_argument("--tighten", action=argparse.BooleanOptionalAction, default=None,
                   help="shorten long interior pauses (default: on, off for recorded)")
    b.add_argument("--asr", action="store_true", help="also ASR-check edge takes with local faster-whisper")
    b.add_argument("--dry-run", action="store_true", help="print the plan (and the ElevenLabs / Fish Audio quota estimate) only")
    a = sub.add_parser("audition", help="compare voices on one short text")
    a.add_argument("--lang", default="en")
    a.add_argument("--backend", choices=["elevenlabs", "edge"])
    a.add_argument("--voices", required=True, help="name=voice_id,... (edge: name=en-US-AndrewNeural,...)")
    a.add_argument("--model", default="eleven_v4", help="comma-separated ElevenLabs models")
    a.add_argument("--stability", type=float, default=0.5)
    a.add_argument("--seed", type=int, default=7)
    a.add_argument("--rate", default="+0%", help="edge speaking rate, e.g. +8%%")
    a.add_argument("--text")
    a.add_argument("--asr", action="store_true", help="edge: ASR-check with faster-whisper")
    a.add_argument("--f0max", type=float, default=420.0)
    a.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    build(args) if args.cmd == "build" else audition(args)


if __name__ == "__main__":
    if sys.argv[1:2] == ["_edge"]:
        _edge_worker(sys.argv[2:])
    else:
        main()
