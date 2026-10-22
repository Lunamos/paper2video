# Visual style

Reference point: 3Blue1Brown — dark background, few colours with fixed meaning, strokes that draw themselves, calm easing, the camera serving the mathematical object. Motion exists to explain. Make it impressive by making the idea visible, not by adding effects.

## Design system (in `template/src/theme`)
- Near-black background, greys for structure, **two or three semantic colours** with one meaning each for the whole film (e.g. "our method", "the thing being changed", "readable/active"). Categorical palettes only inside data charts.
- Type: a serif for headlines, a clean sans for UI, a mono for sources/data labels, KaTeX for formulas (copy the paper's notation exactly). CJK: local subset of Noto Sans SC (`scripts/zh_font_subset.py`; `finalize.sh` / `covers.sh` rebuild it when the text changed and stop on any glyph it lacks). Text layout: see Typography.
- Every data shot has a small source line bottom-left (PAPER Fig. 3 · model · metric · n); illustrations say SCHEMATIC; selected examples say so.
- Keep content above the caption band; captions are global.

## Typography (captions, cards, headlines; required)
Viewers notice bad line breaks at once (a last character alone on a line, a word torn in two, a line starting with
「，」). The template enforces these rules — `src/typography/` for captions (both cuts) and for text blocks via `<Words>` +
`typo.block` (built into `Headline`, `TitleCard`, `VHead`, `VSub`; use them for any other wrapping text) — and
`scripts/text_check.py` reports what is still broken; fix every ERROR before rendering.
- **Break at punctuation / clause boundaries first**, else between words, **never inside a word**: Chinese words come
  from jieba (`scripts/zh_breaks.py`, re-run after every Chinese voice build and after changing Chinese text in `src/`)
  intersected with the browser's segmenter; names, numbers with units (「1000 步」「第 3」「一千到一万」「7B」), Latin words and
  model names (「Llama 3」「GPT-4o」) stay whole. Words jieba gets wrong go into `notes/zh_words.txt` or `keyTerms`.
- **Kinsoku**: no line starts with closing punctuation (，。、；：！？）》」』”’…—), none ends with opening punctuation
  (（《「『“‘).
- **No orphans**: the last line has ≥ 3 CJK characters and ≥ ~35 % of the line above; **balanced lines** (as even as
  possible, top line equal or slightly longer) — like `text-wrap: balance`, but word- and punctuation-aware. A short
  phrase in a wide box is balanced by narrowing it, not left ragged.
- **Near fit**: a line over the measure by 1–2 characters may run up to 10 % long (font −6 % at most, then the box
  widens) instead of wrapping onto a near-empty line.
- **Captions**: ≤ 1 line per page at 16:9 (≤ 18 Chinese / ≈ 58 Latin characters), ≤ 2 lines × 9 at 9:16; what does not
  fit becomes the next timed caption, split at a clause — never crammed or shrunk to fit. If a line cannot obey the
  rules (`forced` / `overflow` in the check), shorten or split it in `scenes.json`.
- **No hanging punctuation**: Chinese captions show no trailing ，。 (inner ones become a gap — the usual Chinese
  subtitle convention, also in the SRT); centred text drops a trailing ，。、；： too (Chrome cannot hang it, and it
  shifts the optical centre). Write headlines without a final 。.
- **Mixed scripts**: a thin space between CJK and Latin / digits (`text-autospace`, set by `typo`); don't type
  spaces by hand around English inside Chinese on-screen text.
- **Fonts**: every displayed character must be in the font. The subset covers everything the Latin fonts don't (CJK,
  full-width punctuation, Greek, arrows, maths) from `scenes.json`, `public/data/*.json` and `src/`; a character the
  font lacks fails the check with its code point and file — replace it (e.g. 10⁶ → KaTeX `10^{6}`) instead of letting it
  fall back to a system font.

## Motion rules
- Only `useCurrentFrame()` + `interpolate`/`spring` (no CSS transitions); seeded randomness only.
- Key every beat to a voice-over anchor, with a fallback frame. A fallback must make sense inside the scene: after splitting or rewriting a scene, an anchor that no longer exists falls back to its default frame and the element pops up there (e.g. a title card suddenly inside the hook) — delete such uses or move them. Word order differs between languages (a Chinese sentence may name the affiliations before the venue): when a reveal belongs to a whole sentence, start it at that line's first word (`useLine(id).from`; SFX cue `at: "line:<id>"`) instead of an anchor word that sits early in one language and late in the other. When two anchors can come in either order, start the beat at whichever comes first.
- Reveal with stroke-draw, wipe, fade-and-rise; one new thing at a time.
- Numbers appear at their final value (no count-ups: intermediate frames would show numbers that are not in the paper). Bars grow from zero; log axes are labelled.
- Emphasis goes on the element (outline, glow, a hand-drawn loop, a short pulse), **never on the whole frame** — no full-frame punch-ins, shakes or zooms. Gentle camera moves inside a single diagram (a pan across a heatmap, an orbit around a 3D plot) are fine when they serve the explanation.
- Scene transitions: content fades over a persistent backdrop; no flashes.
- Everything settles before a scene ends.

## Density: real data fills the frame
The films people liked most are dense data visualisation: every scene has one main visual made of real data that fills the frame (many real examples, per-token / per-layer / per-step traces, hundreds of points), animated on its anchors. Warning signs to fix before rendering: a chart in a corner of an empty dark frame, a scene that is mostly a headline, more than a second or two of near-empty frame, one example where the paper has many.
- When the paper ships only tables (no code or data) but its models are open-weight, a small demo run is the default way to get per-example data: run the model on the paper's benchmark questions (`reference/third-party.md` §7), save per-step / per-option traces, check the aggregate numbers against the paper's tables, label it "run for this video, paper's settings".
- Few, large words on screen: one headline and the data's own labels; no scattered chips, small notes and badges competing with the picture (one short source line is enough).
- The paper's own figures count too (`reference/third-party.md`): a large, animated, annotated original figure beats a small redrawn bar chart.
- Efficiency rules never cut this: save on rework and repeated reads, not on visual ambition.

## Ideas that worked well
- The hero visual of the paper, **with real data**, in the first seconds, then explained properly later and called back at the end.
- A primer scene that makes the task tangible for someone with zero context (e.g. the actual input, the pointer/arrow structure, what "correct" means).
- Heatmaps / grids that fill as a cursor sweeps through layers or time; contours that grow with the cursor; dimming everything except the part the narration is about.
- Before/after pairs with identical axes; small multiples for "same pattern in every model". Two dense matrices side by side leave ~15 px per cell at 1080p: show values only in the cells the narration is about and let colour carry the rest.
- Real model outputs typed out with the relevant phrases highlighted (labelled as selected examples, with model/setting).
- 2.5D perspective via CSS 3D transforms or a small projection helper is usually enough; reach for WebGL (`@remotion/three`) only for genuinely 3D or very dense scenes (text in WebGL is worse, renders are slower).

## Review loop
- Render stills in every language at anchor-based frames (a few per scene), tile them into contact sheets (`scripts/review.py`), and actually look. Check: overlaps, clipping, text too small, empty or half-built frames at the moments the voice talks about them, captions colliding with source lines, layout breaking with longer translations, line breaks (orphans, split words, a line starting with punctuation; `review.py` runs `text_check.py` first).
- When the user reports a problem at a timestamp, map it to the scene and anchor (`scripts/timeline_info.py`), extract the real frames from the rendered MP4 (not just stills) and compare consecutive frames if it is about motion or jitter.
