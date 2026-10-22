# paper2video template

A Remotion 4 (React 19, TypeScript) starter for 3Blue1Brown-style research explainers: dark backdrop, equation-driven,
fixed semantic colours, stroke-drawn reveals, word-timed voice-over with captions, a vertical cut and covers.
It renders out of the box with placeholder timings and no audio.

## Install into a fresh project

```bash
npx create-video@latest --blank my-video && cd my-video
rm -f src/Composition.tsx                         # the blank sample; the template's Root replaces it
cp -R <skill>/template/src <skill>/template/public <skill>/template/tsconfig.json <skill>/template/remotion.config.ts .
cp <skill>/template/scenes.example.json scenes.json
# merge package.additions.json (all remotion/@remotion/* at ONE exact version), then:
npm install
npx tsc --noEmit -p .
npx remotion still VIDEO-EN out/check.png --frame=30
```

Rename the composition prefix once in `src/Root.tsx` (`PREFIX = "VIDEO"`) and the output stem in `src/Video.tsx`
(`OUT_STEM`).

## Layout

```
src/
  index.ts, Root.tsx          compositions: <PREFIX>-EN, <PREFIX>-ZH, <PREFIX>-Vertical, Covers/*, Scenes-EN/*, Scenes-ZH/*
  Video.tsx                   MainVideo (props below), SceneShell, SceneFade, VoiceTrack, Bgm, Sfx, ScenePreview
  Vertical.tsx                draft 1080×1920 cut (16:9 film in a band); all text in VERTICAL
  vertical/                   the native phone cut: layout.ts, VKit.tsx, VCaptions.tsx, VerticalFilm.tsx, scenes/
  Cover.tsx                   Cover (16:9) / CoverV (3:4, 9:16); text in COVER, hero visual slot
  theme/index.ts              color / font / type / layout / ease / clamp tokens
  theme/fonts-zh.json         optional local CJK font subset (placeholder: no files -> system fallback)
  theme/katex-colors.css      colour classes used by the \A \B \H \D KaTeX macros
  components/core.tsx         prog, appear, useFontsReady, Tex, WipeReveal, Backdrop, ChapterTag, Headline,
                              SourceNote, Pill, MonoLabel, Card, StreamText
  components/Chart.tsx        LineChart, HBar, VBar
  components/TitleCard.tsx    full-screen title card after the hook (title, authors, affiliation, claim; 16:9 and 9:16;
                              optional `shot`: the paper's first page as a sheet of paper, see below)
  components/Hand.tsx         HandLoop, HandCheck, HandNote (hand-drawn annotations)
  components/Captions.tsx     global word-highlighted captions
  typography/                 line breaking for all on-screen text: breaks.ts (pure rules + layout), captions.ts
                              (caption pages, shared with scripts/caption_layout.mjs), ZhText.tsx (Words, typo, useNearFit)
  timeline/timeline.ts        vo JSON types, voFiles map, buildTimeline
  timeline/SceneContext.tsx   useAnchor, useAnchors, useLine, useLang, useCut, useSceneDuration, useChapter
  timeline/sfx.ts             sound-effect cues, whooshes, music drop-outs (empty by default)
  scenes/registry.ts          scene id -> component
  scenes/SExample.tsx         the reference scene (and vertical/scenes/VExample.tsx): unregister and delete both once your own scenes are registered
public/data/vo.en.json, vo.zh.json   placeholder timings (one scene, no audio)
scenes.example.json          script schema (copy to scenes.json)
```

## Data flow

`scenes.json` (script) → voice-over pipeline → `public/audio/<cut>/<scene>.mp3` + `public/data/vo.<cut>.json` →
`buildTimeline(cut)` → frame-accurate scenes, lines, words, anchors → scene components + captions + audio.
The film's scene order and every duration come from the vo JSON; the registry only maps ids to components.

### `public/data/vo.<cut>.json` (version 2) — the contract the pipeline must write

```jsonc
{
  "version": 2,
  "meta": { "lang": "en", "backend": "elevenlabs", ... },        // free-form
  "scenes": [{
    "id": "s_example",            // = scenes/registry.ts id
    "audio": "audio/en/s_example.mp3",  // under public/; "" = no audio. A missing file is skipped too.
    "durationMs": 13031,          // clip length (or estimated read length when there is no audio)
    "minSeconds": 12,             // the scene lasts at least this long
    "leadInMs": 500,              // picture before the voice; NEGATIVE = J-cut (voice starts before the cut)
    "tailMs": 900,                // picture held after the voice
    "chapter": "The formula",     // optional; vertical pill / chapter bar
    "lines": [{
      "id": "a", "text": "caption text",
      "startMs": 0, "endMs": 4200,                 // relative to the scene clip
      "words": [{ "w": "A", "startMs": 0, "endMs": 180, "sp": 0 }, ...],  // sp=1: space before the word
      "anchors": { "pendulum": 300 }               // ms, relative to the scene clip
    }]
  }]
}
```

Scene length = `max(minSeconds*1000, leadInMs + durationMs + tailMs)`, rounded to frames at 30 fps. All
`startMs/endMs/anchors` are shifted by `leadInMs` when converted to frames relative to the scene start.

### Cuts (`voFiles`)

A *cut* is one voice track + timing file; `lang` is the on-screen text. They default to the same value but are
independent (`<MainVideo lang="zh" cut="zh-short"/>`). To add a cut: write `public/data/vo.<cut>.json`, then in
`src/timeline/timeline.ts` add `import voX from "../../public/data/vo.<cut>.json"` and `"<cut>": voX` to `voFiles`.
Unknown or empty cuts fall back to the first entry. Music for a cut is `public/audio/bgm_<cut>.mp3` (skipped if absent).

## `MainVideo` props (`VideoProps`)

| prop | type | default | meaning |
|---|---|---|---|
| `lang` | `"en" \| "zh"` | — | on-screen text language (`useLang()` in scenes) |
| `cut` | `string` | `lang` | voice/timing file `vo.<cut>.json`, music `bgm_<cut>.mp3` |
| `captions` | `boolean` | `true` | burned-in captions (the vertical cut passes `false` and draws its own) |
| `mute` | `("voice"\|"music"\|"sfx"\|"captions")[]` | `[]` | layers to leave out of this render |

`mute` exists for handing the film to an editor as stems. Timing and picture are identical in every combination;
only the listed layers are dropped (`"captions"` removes burned-in captions even if `captions` is true):

```bash
P='{"lang":"en","mute":["voice","music","sfx","captions"]}'          # clean picture, silent
npx remotion render VIDEO-EN out/picture.mp4 --props="$P"
npx remotion render VIDEO-EN out/voice.wav  --props='{"lang":"en","mute":["music","sfx","captions"]}' --codec=wav
npx remotion render VIDEO-EN out/music.wav  --props='{"lang":"en","mute":["voice","sfx","captions"]}' --codec=wav
npx remotion render VIDEO-EN out/sfx.wav    --props='{"lang":"en","mute":["voice","music","captions"]}' --codec=wav
```

(If every audio layer is muted or absent, the MP4 has no audio stream at all.)

## Adding a scene

1. Add the scene to `scenes.json` (both languages; same line ids; name anchors on the words that should trigger beats).
2. Create `src/scenes/SMyScene.tsx`; register `{ id: "s_my_scene", comp: SMyScene, name: "SMyScene" }` in `registry.ts`.
3. Regenerate the vo JSON (or hand-add a placeholder entry with estimated timings). Until the id is registered the film
   shows a "scene not registered" placeholder.
4. Preview with the `EN-SMyScene` / `ZH-SMyScene` compositions; check key frames with `npx remotion still`.

### Conventions (see `SExample.tsx`)

- **Anchors drive beats.** `const T = useAnchor("result", 90)` returns the frame (relative to the scene start) where
  the anchor word begins, or the fallback. Animate with `prog(frame, T, dur)` / `interpolate(..., clamp)`; never with
  CSS transitions or hard-coded seconds. `useLine("b")` gives a line's span; `useSceneDuration()` the scene length.
- **Only `useCurrentFrame()` + `interpolate`/`spring`.** Everything is a pure function of the frame.
- **Text per language:** a `TXT = { en: {...}, zh: {...} }` object per scene, `TXT[useLang()]`.
- **Colour is meaning:** `accent` = the method / ours, `accent2` = the key input or concept, `highlight` = the one thing
  to look at now. The same symbol keeps the same colour in equations (`\A{}`, `\B{}`, `\H{}`, `\D{}` in `Tex`) and
  drawings. Greys for everything else; `color.series` only for multi-group data charts.
- **Provenance:** every data shot has a `SourceNote` (label `source` / `data` / `paper`); illustrations are labelled
  `SCHEMATIC`; cherry-picked outputs say `selected example`.
- **Numbers:** never count up (in-between frames show numbers that are not in the source). Bars grow from 0 on a
  zero-based axis; the value label appears only at the final length (`HBar`, `VBar` do this).
- **Layout:** content above `layout.contentBottom` (y≈860); footnotes at `layout.footnoteBottom` (166 px from the
  bottom); captions below that. Margins `layout.marginX` (120).
- **Reveals:** equations write on with `WipeReveal`; lines and schematics draw on via `strokeDasharray` /
  `strokeDashoffset`; text appears with `appear(p)` (fade + small rise).
- **No full-frame camera moves.** `SceneFade` only fades content at scene boundaries. Full-frame push-ins / zooms made
  text and hairlines jitter visibly; to emphasise something, animate that object (`<Card emphasis={p}>`, a glow, a
  `HandLoop`).

## Title card (`components/TitleCard.tsx`)

The scene after the hook: `kicker` (arXiv id / venue), `title`, `subtitle`, `authors`, `affiliation`, `claim`, `note`,
`beats` (frames relative to the scene; key them to anchors), size props (`titleSize`, `subtitleSize`, `authorsSize`,
`claimSize`, `top`) and an optional blurred `bg`. The same component lays itself out for 16:9 and 9:16.

**The paper's first page as a sheet of paper.** `node scripts/paper_shot.mjs <arXiv id | paper.pdf | URL>` writes
`public/shots/paper.png`: page 1 of the PDF (an arXiv id downloads it to `data/`), or the first screen of a web article
that has no PDF. Then:

```tsx
<TitleCard {...T} shot="shots/paper.png" beats={{ title: tTitle, authors: tInst, claim: tClaim, shot: tTitle }} />
```

The page appears as a clear sheet of paper while the title is read — solid white, never dimmed or blurred, thin edge,
rounded corners, soft shadow, a slight tilt — so the viewer sees at a glance "this is the paper they are reading". It
backs the explainer up; it does not have to be readable, and it never covers the text. Only its upper part shows
(title, authors, abstract) and its lower edge fades out above the captions. It eases in on `beats.shot` (fade + small
slide), then drifts very slowly upwards; only the sheet moves, the frame never zooms. With a shot the text block is
measured once its fonts are in and scaled down if it would run into the captions, so `shot` and the beats are normally
all a card needs.

| prop | default | |
|---|---|---|
| `shot` | — | staticFile path of the page; without it the card looks exactly as before |
| `beats.shot` | `beats.title` | when the sheet eases in |
| `beats.shotMove` | `beats.authors` (≥ 90 frames after `beats.shot`) | 9:16 only: when the sheet slides down under the captions; the authors and claim wait for it |
| `shotWidth` / `shotLeft` | 700 / 1160 (16:9); 900 / centred (9:16) | size and left edge of the sheet |
| `shotTop` | 110 (16:9); 9:16: just under the measured title block | top edge |
| `shotTilt` | 1.5° (16:9), −1.5° (9:16) | 0 = straight |
| `shotCrop` | `{ x: 0.08, top: 0.05 }` | page margins cropped away (fractions of the page); `{ x: 0 }` for a page with narrow margins |
| `shotDrift` | 3 | upward drift in px per second (0 = still) |

- **16:9**: text column x 150–1070, its type capped at title 96 / subtitle 40 / authors 38 / claim 38 (larger size props
  are ignored, smaller ones kept); the sheet centre-right (x ≈ 1160–1860, y ≈ 110 down to ≈ 880, above the captions),
  there for the whole scene.
- **9:16**: while the title is read the sheet sits large right under the title block (placed from the measured text,
  down to the captions); on `beats.shotMove` it slides down into the band under the captions (its header still
  showing) and the authors, institutions and claim appear where it was — so they come in at the latest ~3.5 s after
  `beats.shot`.
- Not used on the covers. Render stills of both cuts around the beats to check.

## Captions and typography

`Captions` (16:9: one line per page, EN ≤ 58 chars, ZH ≤ 18 chars) and `VCaptions` (9:16: ≤ 2 lines × 9 / 18) get
their pages from `typography/captions.ts`: clause boundaries first, never inside a word (jieba table
`public/data/zh_breaks.json` from `scripts/zh_breaks.py` ∩ `Intl.Segmenter`), numbers with units and model names whole,
kinsoku, no orphan, balanced lines, ≤ 10 % overrun before a new page. They highlight words as they are spoken and follow
the Chinese subtitle convention: no commas/full stops on screen (inner ones become a gap, final ones are dropped).
Caption text is the `words[].w` from the vo JSON, so fix caption typos in `scenes.json` `text`.

Wrapping text elsewhere: `<div style={{ ...typo.block }}><Words>{text}</Words></div>` (`typography/ZhText.tsx`) keeps
words whole, balances the lines (`text-wrap: balance`), applies strict kinsoku and CJK–Latin spacing
(`text-autospace`) and drops a trailing ，。; `useNearFit` keeps a block that overflows one line by ≤ 10 % on one line.
`Headline`, `TitleCard`, `VHead` and `VSub` already do this. `python3 scripts/text_check.py --cut zh` reports what is
still broken (rules: `reference/visual-style.md` "Typography").

## Audio

- **Voice:** one global `VoiceTrack`, so negative `leadInMs` J-cuts work across scene boundaries.
- **Music (`Bgm`):** `public/audio/bgm_<cut>.mp3`, composed to the cut's timeline from frame 0 (e.g. one section per
  `chapter`, styles from `musicStyles`). Auto-ducked: ≈0.08 under speech (lines < 1.2 s apart merge), 0.2 in pauses,
  0.35 before the first / after the last line; `MUSIC_DROPOUTS` in `timeline/sfx.ts` dips it before a key claim.
- **Sfx:** `CUES` in `timeline/sfx.ts` (scene + anchor or frame + offset → `public/audio/sfx/<name>.wav`).
  Missing files are skipped. Keep them sparse and quiet.

## Vertical cut and covers

- **Vertical cut for phones: `src/vertical/`** (compositions `<PREFIX>-V-ZH` / `-V-EN`, scene previews `V-<Name>`).
  Same audio, own 9:16 scenes: big type, one focus per beat, the picture filling the whole frame, text inside the
  platforms' safe area (`layout.ts`). Add one component per scene to `vertical/scenes/` (pattern: `VExample.tsx`) and
  register it; list scenes to skip in `V_DROP`; run `scripts/zh_breaks.py` for Chinese captions; review with
  `scripts/vreview.py`. See `reference/vertical.md`.
- `Vertical.tsx` (quick draft only — its text is too small on a phone): edit `VERTICAL` (lang, cut, kicker, title, subtitle `[before, accented, after]`, authors, credit,
  `chapters: { sceneId: name }`, falling back to the vo JSON `chapter`). The 16:9 film is re-rendered at 0.6 scale
  (60 px cropped per side) in a band at y=520; progress bar and larger captions below; the bottom ~20% stays free for
  platform UI.
- `Cover.tsx`: edit `COVER[lang]` (kicker, headline lines with one `hot` line, pill `[label, value]`, footnote) and
  pass a real `hero` visual (e.g. the film's main chart) instead of the placeholder `CoverHero`.
  Stills: `Cover-EN`, `Cover-ZH` (1920×1080), `Cover-ZH-3x4` (1080×1440), `Cover-ZH-9x16` (1080×1920), `Cover-EN-3x4`.

## Chinese font subset

`theme/fonts-zh.json` = `{ "family": "...", "files": { "400": "fonts/zh/NotoSansSC-400.woff2", ... },
"hand"?: { "family": "...", "file": "fonts/zh/<hand>.woff2" } }` with paths under `public/`. Generate it with
`scripts/zh_font_subset.py`: every displayed character the Latin fonts lack (scenes.json, `public/data/*.json`, `src/`);
the manifest records them in `text`, so `zh_font_subset.py --check` (run by `finalize.sh` / `covers.sh`) rebuilds a
stale subset and fails, listing each character the font lacks, instead of letting it fall back to a system font. With
`"files": {}` the system CJK font is used (the check builds the subset as soon as there is CJK text).
