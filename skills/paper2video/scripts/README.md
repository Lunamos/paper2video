# scripts/

Pipeline tools for the Remotion project. Run them from the project root (the folder holding
`scenes.json`) or set `PAPER_VIDEO_ROOT`. Python 3.10+, standard library only; `numpy`,
`edge-tts` and `faster-whisper` are pulled in automatically through `uv run --with ...` when a
step needs them (`figdata.py` is run with `uv run --with pymupdf ...` as in its usage line). `ffmpeg`/`ffprobe` must be on PATH. Keys are read from the environment or `.env`
and are never printed.

| Script | Purpose | Key? | Example |
|---|---|---|---|
| `vo.py` | Voice-over: one read per scene -> tighten pauses, min gaps, polish, normalise -> `public/audio/<cut>/*.mp3` + `public/data/vo.<cut>.json` (+ `notes/vo_report.<cut>.json`). Backends: `elevenlabs`, `edge`, `gpt-sovits` (self-hosted, via HTTP / ssh tunnel), `fish` (Fish Audio HTTP API), `recorded`, `none` | for `elevenlabs` and `fish` | `python3 scripts/vo.py build --lang en` |
| `vo.py audition` | Same short text in several voices, with QA numbers | only for `elevenlabs` | `python3 scripts/vo.py audition --lang en --backend edge --voices a=en-US-AndrewNeural,b=en-US-AvaNeural` |
| `voice_qa.py` | Prosody stats (YIN pitch variation, pauses) + ASR round-trip (Scribe with a key, else local faster-whisper) | no (optional) | `python3 scripts/voice_qa.py public/audio/en/s_intro.mp3 --text "..." --asr` |
| `music.py` | Music bed composed per music section (ElevenLabs), or level your own royalty-free track -> `public/audio/bgm_<cut>.mp3` at -17.4 LUFS; `--refit` re-times the generated bed after a voice-over change (no credits); `--refit --from en` reuses the English bed for another language's cut | only to generate | `python3 scripts/music.py --lang en --refit` |
| `sfx_synth.py` | Procedural SFX (whoosh, pop, tick, hit, stamp, shimmer, riser, powerdown) -> `public/audio/sfx/` | no | `python3 scripts/sfx_synth.py` |
| `srt.py` | Captions as `.srt` (the burned-in 16:9 pages, from `caption_layout.mjs`; CJK-style for zh/ja) | no | `python3 scripts/srt.py zh` |
| `text_check.py` | Typography check before rendering: lays out every caption of a cut (16:9 and 9:16) with the template's code and reports split words, lines starting with closing / ending with opening punctuation, orphans, overflow, glyphs missing from the font, stale `zh_breaks.json`; exit 1 on errors; full list → `review/text_check.<cut>.txt` (`review.py` / `vreview.py` run it first) | no | `python3 scripts/text_check.py --cut zh` |
| `caption_layout.mjs` | The caption pages of a cut as JSON, computed by the template's own `src/typography/captions.ts` (bundled with the project's esbuild); used by `text_check.py` and `srt.py` | no | `node scripts/caption_layout.mjs zh --kind vertical` |
| `timeline_info.py` | Scene start frames, durations and anchor frames (as `timeline.ts` computes them) | no | `python3 scripts/timeline_info.py en` |
| `zh_font_subset.py` | Local CJK font subset of every displayed character the Latin fonts lack (CJK, full-width punctuation, Greek, arrows; from `scenes.json`, `public/data/`, `src/`) -> `public/fonts/zh/`, `src/theme/fonts-zh.json`; `--check` rebuilds it when the text changed and exits 1 listing any character the font lacks (`finalize.sh` / `covers.sh` run it) | no | `python3 scripts/zh_font_subset.py --check` |
| `review.py` | Review stills: every anchor (once its beat has settled) plus scene starts/ends, rendered with one bundle (`stills.mjs`) and tiled into contact sheets per scene or for the film | no | `python3 scripts/review.py VIDEO-ZH zh --scenes s_method` |
| `vreview.py` | Contact sheets of the vertical scenes (`V-<Name>` previews) at every anchor, one sheet per scene | no | `python3 scripts/vreview.py --scenes s_intro,s_end` |
| `zh_breaks.py` | Chinese word boundaries (jieba; extra words from `notes/zh_words.txt` and `keyTerms`) for the captions (16:9 and vertical) and the CJK strings in `src/` (`<Words>`) → `public/data/zh_breaks.json`; re-run after each Chinese voice build and Chinese text change | no | `python3 scripts/zh_breaks.py` |
| `paper_shot.mjs` | The paper's first page for the title card background -> `public/shots/paper.png`: an arXiv id downloads the PDF to `data/arxiv_<id>.pdf` (reused) and renders page 1 (`pdftoppm` if installed, else PyMuPDF via `uv`; `--dpi 200`, `--page`); a local PDF or PDF URL likewise; any other URL: the first screen of the web article (Remotion's headless Chrome, light scheme, cookie banners removed; `--width`, `--height`, `--until`, `--hide`) | no | `node scripts/paper_shot.mjs 2309.16588` |
| `stills.mjs` | Many stills of one composition from a single bundle (used by `review.py`) | no | `node scripts/stills.mjs VIDEO-EN review/stills 120,480,900 --scale 0.5` |
| `contact_sheet.py` | Tile rendered stills into one review image | no | `python3 scripts/contact_sheet.py review/sheet.png review/stills/*.png` |
| `figdata.py` | Numbers from figure files: `dump` (vector PDF paths + labels), `images` (embedded raster panels), `heatmap` (colormap inversion of cells + their text), `markers` (digitise line+marker plots, overlay for checking) | no | `uv run --with pymupdf python scripts/figdata.py dump figs/fig3.pdf` |
| `covers.sh` | The standard cover set → `out/covers/` (`bilibili.jpg` at 3840×2160 + its 4:3 / 16:9 crop previews, `youtube.jpg` < 2 MB, `zh_3x4.jpg`, `zh_9x16.jpg`, optional `en_*`), all JPEG; missing stills are skipped | no | `scripts/covers.sh youtube=Cover2-EN` |
| `finalize.sh` | Font check (`zh_font_subset.py --check`), render a composition, two-pass loudnorm to -14 LUFS / -1.5 dBTP, AAC 320k 48 kHz, optional cover still | no | `scripts/finalize.sh VIDEO-EN <slug>_en` |
| `finalize_vertical.sh` | Same for a 1080x1920 cut, plus vertical cover stills | no | `scripts/finalize_vertical.sh VIDEO-V-ZH <slug>_zh_vertical` |
| `verify.py` | Check a finished file: streams, duration vs timeline, loudness, full-mix ASR vs script + key terms (local whisper by default), full-frame motion runs (zoom/drift/jitter) -> `notes/verify.<name>.json` | no (optional) | `python3 scripts/verify.py out/<slug>_en.mp4 --cut en` |
| `export_handoff.py` | For editing apps: silent picture (+ per-scene clips), voice/music/sfx stems, SRT, scene CSV, CMX3600 EDL | no | `python3 scripts/export_handoff.py VIDEO-EN --lang en --per-scene` |
| `new_video.sh` | Workspace mode: create `<NNN>_<ShortName>/` (NNN counts down from 999, so the newest video sorts first) from the template + scripts, linked to the workspace's shared `node_modules` and `.env` (copy this script to the workspace root, next to the shared `package.json`) | no | `./new_video.sh LoRA` |
| `common.py` | Shared helpers (root, keys, loudness, timeline maths, uv runner) | - | imported |

## scenes.json fields used here

```jsonc
{
  "fps": 30,
  "defaults": { "leadInMs": -200, "tailMs": 600 },   // negative leadInMs = J-cut (voice starts before the picture changes)
  "voices": {                                         // one entry per cut
    "en": { "backend": "elevenlabs", "voice": "<voice id>", "model": "eleven_v4",
            "stability": 0.5, "seeds": [11, 23, 37], "tempo": 1.0, "pauseScale": 1.0, "f0Max": 420,
            "keyTerms": ["Qwen", "DAPO"] },                // takes whose transcript loses a key term lose the pick
    "zh": { "backend": "edge", "voice": "zh-CN-YunxiNeural", "rate": "+0%", "pitch": "+0Hz" },
    "zh_rec": { "backend": "recorded", "lang": "zh", "whisperModel": "small", "tighten": false },
    "en_draft": { "backend": "none", "lang": "en", "cps": 15, "cpsCjk": 5 }
  },                                                  // "lang": which text blocks a variant cut reads (default: the cut id)
  "music": { "positive": [], "negative": [], "cutStyles": { "zh": [] }, "seed": 7 },
  "scenes": [
    { "id": "s_intro", "chapter": "intro", "musicSection": "opening", "musicStyles": ["sparse and curious"],
      "en": { "minSeconds": 10, "leadInMs": 400, "tailMs": 500, "pick": "steady",
              "lines": [ { "id": "a", "text": "Caption text (shown).", "tts": "[curious] Spoken text (tags, respellings).",
                           "anchors": { "beat": "word" }, "pauseAfterMs": 400 } ] },
      "zh": { "lines": [ ... ] } }
  ]
}
```

- `text` is what the captions show; `tts` (optional, defaults to `text`) is what is spoken. Timings
  are aligned from `tts` onto `text`, so respellings (`twenty` for `20`) keep captions exact.
- `anchors`: name -> word (latin: first matching word) or substring (CJK); the template turns them
  into frames so animations land on the spoken word.
- Audio tags (`[curious]`, `[excited]`, `[chuckles]` ...) only reach ElevenLabs v3; other backends strip them.
- `recorded`: put narration at `recordings/<cut>/<scene_id>.wav|mp3|m4a|flac`.
- `"language"` on a voice: the spoken language code (TTS `language_code`, ASR, scoring) when the cut's text-block key is
  not a language — e.g. a short cut `"short": {"lang": "short", "language": "en", ...}` reading its own `"short"` blocks.
  Defaults to the text-block key.
- `notes/vo_picks.<cut>.json` (`{"s_intro": 23}`) pins an ElevenLabs take by seed.
- `keyTerms` (voice or scene block): accepted spellings joined by `|` (`"熵|商"` when `tts` respells a rare
  character); compared by count between the spoken text and the ASR transcript.
- `chapter` names the video chapter (caption pill, YouTube/Bilibili chapters); `musicSection` groups scenes
  into music sections for `music.py` (defaults to `chapter`), so the music can change less often than chapters.

## Limitations

- ASR error counts spelled-out numbers vs digits as mismatches; compare takes relatively.
- `edge` uses an unofficial Microsoft endpoint (free, may change or rate-limit); one take per scene.
- `export_handoff.py` needs the template's `mute` prop; stem renders take roughly as long as a video render.
- `music.py --file` does not loop a track shorter than the video.
