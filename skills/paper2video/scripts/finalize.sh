#!/usr/bin/env bash
# Render a finished cut and master its loudness for upload.
#   0. font check: every displayed CJK character is in the local font subset (rebuilt if the text changed)
#   1. npx remotion render <composition>  (H.264, CRF 15)
#   2. two-pass ffmpeg loudnorm to -14 LUFS integrated / -1.5 dBTP (YouTube, Bilibili, most platforms);
#      video stream copied, audio -> AAC 320k 48 kHz, +faststart for streaming
#   3. optional cover still (a Remotion <Still> id)
#   4. prints the measured loudness / true peak of the result
#
# Usage: scripts/finalize.sh <CompositionId> [output-name] [CoverStillId]
#   e.g. scripts/finalize.sh VIDEO-EN video_en Cover-EN   -> out/video_en.mp4, out/video_en_cover.png
# Env: CRF (default 15), CONCURRENCY (default: Remotion's), PROPS (JSON input props), KEEP_RAW=1, FONT_CHECK=0
set -euo pipefail
COMP=${1:?usage: finalize.sh <CompositionId> [output-name] [CoverStillId]}
NAME=${2:-$COMP}
COVER=${3:-}
cd "${PAPER_VIDEO_ROOT:-$(dirname "$0")/..}"
# every displayed CJK character must be in the local font subset (rebuilt here when the text changed), or the render
# would silently fall back to a system font for it. FONT_CHECK=0 skips.
font_check() {
  [[ "${FONT_CHECK:-1}" == 0 ]] && return 0
  local m lang
  for m in src/theme/fonts-*.json; do
    [[ -e "$m" ]] || continue
    lang=$(basename "$m" .json); lang=${lang#fonts-}
    python3 scripts/zh_font_subset.py --check --lang "$lang" || { echo "font check failed: fix the characters above (or FONT_CHECK=0)"; exit 1; }
  done
}
font_check
mkdir -p out
RAW="out/${NAME}_raw.mp4"
ARGS=(--crf="${CRF:-15}" --log=error)
[[ -n "${CONCURRENCY:-}" ]] && ARGS+=(--concurrency="$CONCURRENCY")
[[ -n "${PROPS:-}" ]] && ARGS+=(--props="$PROPS")
npx remotion render "$COMP" "$RAW" "${ARGS[@]}" || { echo "render failed — retrying once (don't run scripts that write public/ during a render)"; npx remotion render "$COMP" "$RAW" "${ARGS[@]}"; }
# pass 1: measure
MEAS=$(ffmpeg -hide_banner -nostats -i "$RAW" -af loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 | awk '/^\{/,/^\}/')
get() { echo "$MEAS" | python3 -c "import sys,json; print(json.load(sys.stdin)['$1'])"; }
# pass 2: apply linearly with the measured values
ffmpeg -y -hide_banner -loglevel error -i "$RAW" -c:v copy \
  -af "loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=$(get input_i):measured_TP=$(get input_tp):measured_LRA=$(get input_lra):measured_thresh=$(get input_thresh):offset=$(get target_offset):linear=true,aresample=48000" \
  -c:a aac -b:a 320k -ar 48000 -movflags +faststart "out/${NAME}.mp4"
[[ -z "${KEEP_RAW:-}" ]] && rm -f "$RAW"
if [[ -n "$COVER" ]]; then
  npx remotion still "$COVER" "out/${NAME}_cover.png" --log=error
fi
ffmpeg -hide_banner -nostats -i "out/${NAME}.mp4" -af ebur128=peak=true -f null - 2>&1 | grep -E "^\s+(I|Peak):" | tail -2
ls -la out/"${NAME}".mp4 ${COVER:+out/"${NAME}"_cover.png}
