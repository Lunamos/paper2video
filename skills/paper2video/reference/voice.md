# Narration

`scripts/vo.py` turns the lines in `scenes.json` into per-scene audio plus word timings (`public/data/vo.<lang>.json`). The picture is keyed to anchor words, so every backend must end up with timings.

## Choosing a backend (per language, `voices.<lang>.backend`)

| Backend | Needs | Quality | Notes |
|---|---|---|---|
| `elevenlabs` | `ELEVENLABS_API_KEY` in env or `.env` | best expressiveness; v3 audio tags (`[curious]`, `[sighs]`, `[chuckles]`) | character-level timestamps; paid — check quota before every batch |
| `edge` | nothing (internet) | clear, a bit announcer-like; no tags | free neural voices via the `edge-tts` package; word timings from its word-boundary events |
| `gpt-sovits` | a GPT-SoVITS `api_v2` server (a GPU machine; reachable directly or through an ssh tunnel vo.py opens) | as good as the reference clip and the fine-tune; weak on languages the voice was not trained on | open-source voice cloning; free per take, so several seeds per scene; word timings from local faster-whisper — see "Open-source TTS" below |
| `fish` | a Fish Audio API key (`FISH_API_KEY`, or the variable named in `keyEnv`) with **API** credits | strong Chinese voices from a large voice library | Fish Audio's HTTP API (fishaudio.org); paid per character, so quota check + estimate before every batch; no seed, so each take is a fresh random read; word timings from local faster-whisper — see "Fish Audio" below |
| `recorded` | the user's own narration per scene in `recordings/<lang>/<scene>.wav` | the most human | timings from local faster-whisper, aligned to the script |
| `none` | nothing | — | silent timeline from reading speed; captions + music only |

Default: ElevenLabs if a key is present, else edge; tell the user which and why, and offer the others. Other good options exist (open-source TTS such as CosyVoice / IndexTTS / F5-TTS / Kokoro, or commercial ones) — add a backend only if the user wants it (the `gpt-sovits` backend is the pattern to copy: HTTP request per scene, cache by request, whisper for timings); anything that yields audio + word timings plugs in, and forced alignment (faster-whisper) can supply timings for any audio.

## Casting
Audition 3–4 candidate voices per language with two or three representative sentences (`vo.py audition`), cheap/fast model for drafts, best model for finals. Use the newest TTS model the account offers (`GET /v1/models`; in October 2026 that is `eleven_v4`, the template default). When a new model appears, audition one real scene in the old and the new model with the same voice before switching: in one test, v4 was more expressive in English and, in Chinese, read a model name correctly where v3 misread it (千问 → 千万). Audio tags and timestamps work with v4 as with v3. Prefer a library voice with native pronunciation for each language. Don't imitate or clone any real person's voice without their consent (e.g. a character's voice actor); the user's own voice is fine.

## Generation strategy that sounds alive
- **One request per scene**, not per sentence — sentence-by-sentence synthesis sounds stiff and starts every sentence cold.
- **Several seeds per scene** (e.g. 3); pick automatically by ASR accuracy first, then prosody (pitch variation) with a small penalty for length. Manual picks go in `notes/vo_picks.<lang>.json`. For a scene that must stay calm, set `"pick": "steady"` (closest to the film's typical expressiveness).
- **Key terms**: list the words whose misreading changes the meaning — model and method names, the paper's core term — as `"keyTerms"` on a voice (all scenes) or a scene block, with accepted spellings separated by `|` (`["Qwen|千问", "熵|商"]`). A take whose transcript loses one loses the pick, whatever its overall error rate: a single wrong syllable (千问 → 千万) barely moves the error rate but is exactly what a viewer hears. Lost terms are printed as `LOST-TERMS` in the build log.
- **Sparse audio tags** (≈4 per language per film). A tag at the very start of a scene can slur the first word — put the tag later or drop it.
- **Tighten pauses by context** (clause < line break < sentence end < ellipsis) and enforce minimum gaps after lines that need air (`pauseAfterMs`). Normalise loudness per clip; the master is normalised again at the end.
- **J-cuts**: a negative `leadInMs` lets the next scene's voice start slightly before its picture.

## Objective QA (you cannot listen — measure)
`vo.py` runs `voice_qa.py` on every take: ASR round-trip (ElevenLabs Scribe if a key is present, else faster-whisper) with a diff against the script, pitch statistics, pause statistics. Read the diffs: many are just formatting (numbers written as digits, respelled names); real problems are misread words. Test fixes on short snippets before regenerating whole scenes.

**Anchors are words of the caption `text`, not of `tts`**: with digits in the caption ("85%") and characters in `tts` ("百分之八十五"), the anchor is "85%". `vo.py build` checks this before generating anything.

Pronunciation tricks (only change `tts`, never the caption `text`):
- respell names and acronyms phonetically, test variants with ASR, keep the one that round-trips;
- spell numbers as words the way you want them read ("twenty-twenty-six", "zero point six"; in Chinese write the characters);
- **polyphones** (e.g. Chinese 行 háng/xíng, 调 diào/tiáo, 长 cháng/zhǎng): rewrite with an unambiguous homophone in `tts` or rephrase;
- **rare characters**: a TTS voice may not know a rare technical character (e.g. 熵 shāng, "entropy") and guess another reading; write a common character with the same sound in `tts` only (熵 → 商) and confirm with ASR that the transcript shows the intended word again (ASR picks the character from context, so a correct read comes back as 熵). Respell it in every scene, not only where it failed: a scene that happened to read it right can misread it the next time it is regenerated;
- a word misheard in all takes is usually mispronounced — rephrase with a synonym;
- an error that appears in only one take is that take's problem: pick another seed rather than rewriting the line.

## Cost, caching, keys
Every paid batch: query remaining quota, estimate the batch, print both, abort if it would exceed. Audio is cached by a hash of text + voice + model + settings + seed, so re-runs only pay for what changed. Keys live only in env/`.env` (git-ignored); never print them.

## Fish Audio (hosted API)
`backend: "fish"` calls Fish Audio's HTTP API (`POST https://fishaudio.org/api/open/v3/speech/tts`, Bearer key). Note: this is fishaudio.org, not fish.audio.

```json
"zh": {"backend": "fish", "voice": "<voiceId>", "model": "fishaudio-s21pro", "language": "zh",
       "seeds": [11, 23], "whisperModel": "medium", "cpsCjk": 5.5, "keyTerms": ["<core term>"]}
```
Optional: `url` (API base, default `https://fishaudio.org/api/open`), `keyEnv` (default `FISH_API_KEY`), `format` (`wav` default, or `mp3`), `instruction` (a natural-language style note), `params` (merged into the request body as is, e.g. `{"speed": 0.95, "stability": 1.1}`; the request contract is strict, so an unknown field is a 400, not silently dropped), `creditsPerChar` (for models billed at a multiple). `synthCmd` (a command list, run from the project folder) replaces the HTTP call with an external helper — `<cmd> quota` prints `{"remaining": n}`, `<cmd> tts <out>` reads the request JSON on stdin, writes the audio and prints `{"creditsUsed": n}` — for example a helper that goes through the user's own logged-in browser session when their plan is billed on the website rather than the API (check the service's terms first; keep requests sequential and slow; never extract or print the session cookies).

- **Billing.** The API spends the account's *API credits*, a balance separate from the website's membership credits (a website subscription does not fund the API). `GET /api/open/v1/profile` → `api_quota_remaining` is what `vo.py` checks; the estimate counts a CJK character as 1 credit and every other character (punctuation, Latin, spaces) as 0.5, rounded up per request, which matched the `X-OpenAPI-Credits-Used` response header exactly. Each fresh take's actual credits are summed and logged to `notes/tts_log.md`. Validation and auth failures are not charged.
- **Takes.** The API has no seed. Each entry in `seeds` is only a take label in the cache key, so 2 seeds = 2 independent paid reads, and a take can be reproduced only from the cache (keep `audio_cache/`). Takes do differ (of two reads of one sentence, one scored ASR error 0.17 and the other 0), so 2 takes per scene and the ASR pick are still worth it for the final; use `--takes 1` for drafts.
- **Capabilities.** Read `GET /api/open/v3/speech/tts/capabilities` (public) for the controls each model supports. Controls a model does not support are ignored and named in the `X-OpenAPI-Ignored-Parameters` header; `vo.py` prints a NOTE when that happens. The Fish models list speed, volume, stability, similarity, language and textNormalization, but not `instruction` (in a test it was ignored), so use a calmer voice or `speed` for a calmer read instead.
- **Retries.** 429 and 5xx are retried twice with back-off; 402 (out of credits) stops the build; other 4xx errors stop with the API's message.
- The API also offers `POST /v3/speech/tts/aligned` (SSE with word timestamps). `vo.py` uses local whisper instead, because the same transcript also serves the ASR check that picks the take.

## Recorded narration (collaboration)
Give the user the final script per scene (`scripts/srt.py` or a printed table), ask for one file per scene (any common format, quiet room, 30 cm from the mic), put them in `recordings/<lang>/`, and build with `backend: "recorded"`. Their performance sets the timing; the picture follows via anchors.

## Open-source TTS (GPT-SoVITS and similar)
Self-hosted voice cloning is free per take and can give a voice no catalogue has, but nothing is tuned for you. What mattered in practice:

**Deploy on the GPU machine, not the laptop.**
- Clone the upstream repo at a release tag and check out the tag the voice was trained with (a fine-tuned checkpoint records its base model and version — `torch.load(ckpt)["config"]`; GPT-SoVITS also has `process_ckpt.get_sovits_version_from_path_fast`).
- Make a uv venv (`uv venv --python 3.11`) and pin torch/torchaudio to the generation the repo was written for: a much newer torchaudio needs `torchcodec` just to read a wav.
- Download the pretrained bundles the install script fetches: base models, the G2P model, NLTK data, the open_jtalk dictionary. You don't need the Windows "integrated packages"; they are the same code plus a bundled Python.
- No system ffmpeg on the server? A static ffmpeg build on `PATH` is enough.
- Keep everything (venv, models, caches) inside one directory you own, so cleaning up means deleting one folder.

**Serve it on demand.**
- Run the project's HTTP API (`api_v2.py`) bound to `127.0.0.1` with your own YAML config, and reach it through an ssh tunnel.
- Use a start script that is idempotent (prints "already running"), picks the least-loaded GPU and waits until `/docs` answers. Don't probe `/tts` with no parameters: that raises a server error.
- Pair it with an idle watchdog that stops the server after ~20 min without requests. Then several users can share it without one of them stopping it under the others, and the GPU is not held overnight.
- `vo.py` with `ssh` + `startCmd` runs the start script when the server does not answer and opens and closes its own tunnel on a free local port (`url` then only names the remote port, or set `remotePort`). It never borrows another process's tunnel: several builds can share one server, and a borrowed tunnel vanished mid-response whenever its owner finished.

**Batch synthesis without the server** (quick experiments): import the inference class (`TTS_infer_pack.TTS`), load once, loop over a JSON job list, write wavs. It is about 3× faster than real time on one A100 for a v2 model, using ~2 GB of VRAM.

**What moves quality, in order:**
1. **Text splitting.** The default "cut at every punctuation mark" synthesises each clause separately and restarts the intonation every few words: choppy and over-excited. Splitting every few sentences (`cut1`; `cut2` by length) roughly halved the ASR error and evened out loudness.
2. **Sampling.** `temperature` 0.7, `top_k` 5, `top_p` 0.8 is steadier than the defaults (1.0 / 15 / 1.0). Very low temperatures did not help further.
3. **Reference clip and its exact transcript.** 3–10 s, clean, in the target language. A transcript that doesn't match word for word degrades the clone silently. The clip sets the mood; a calmer clip of the same voice is the first thing to try for a calmer read. (Synthesising a calm sentence with the voice and reusing it as reference did *not* change the measured prosody.) Empty `prompt_text` (reference-free mode) is supported, but it is usually worse.
4. **Which checkpoint does what.** The GPT/T2S model decides content tokens and prosody. The SoVITS model decides timbre and articulation. A SoVITS fine-tuned on one language articulates other languages poorly. Swapping in the base GPT does not fix English inside Chinese, and a base/newer SoVITS improves articulation at the cost of timbre similarity. Let the user listen before choosing.
5. **Seeds.** Takes differ noticeably; generate 2–3 and let the ASR pick.

**Failure modes to watch for:**
- **Runaway generation.** The model keeps talking, repeats a sentence or invents speech (a 50 s clip for a 15 s text). `vo.py` warns when the audio is much longer than the text and the ASR error exposes it. Change the seed or shorten the chunk.
- **Hyphens and spelled-out forms** (`R-L-V-R`, `A-I-M-E`) can derail the model completely. Write acronyms plainly.
- **Skipped clauses.** A short clause after a comma can be silently dropped ("预训练靠预测文字，把它们定下来" came out without the second half, in every seed), and the pick-time ASR may not notice. Re-check the picked takes with a stronger model (faster-whisper `large-v3`, decoding the audio with ffmpeg to a numpy array) and compare with the script; fix by rewriting the sentence as one connected clause, not by adding seeds. A short clause at the *end* of a line is the most at risk ("…推理，却很少带来新的推理" lost its key half in both seeds): give a key claim its own sentence.
- **English inside a non-English voice** is the weak spot of most single-language fine-tunes. Don't respell English words in the other script: viewers find it strange. Keep English to the terms the audience really says in English, and accept a slight accent. In practice, say it in the voice's language wherever you can and keep the English name on screen: "two researchers at MIT" instead of two English names, "three common post-training methods" instead of PPO/GRPO/ES, a description ("a 100-million-parameter model") instead of a model name.
- **Rare characters and polyphones** as with any TTS (`熵 → 商` in `tts`), plus key terms in `keyTerms`.

**Long builds and shared servers.** Synthesis queues when several projects share one server: a full build (10 scenes × 2 seeds) can take well over 30 minutes, longer than an agent's default background-task limit. Run it in the background with a long timeout (e.g. 2 h) or in per-scene batches; cached takes survive a kill. `public/data/vo.<cut>.json` is written only at the end of a build, so after any interruption (killed task, dropped disk) re-run the same build — free from the cache — before rendering. For the length estimate set the voice's own reading rate: `"cpsCjk"` in `voices.<cut>` (a measured self-hosted Chinese voice read ≈ 5.7 CJK chars/s incl. pauses; the default 5 overshot a 3:05 film as 4:04).

**QA without ears.** Whisper is a rough judge of a stylised voice. `small` misses a lot, so use `medium` or better for picking takes. Whisper forced to Chinese also mangles English words that may sound fine, so listen to (or have the user listen to) the English-heavy lines. Pitch statistics show stability but not "how excited it sounds", so ask the user.

**Consent.** Clone only voices you have the right to use. A model trained on a character's or a real person's recordings carries the rights questions of those recordings; tell the user before publishing with it.
