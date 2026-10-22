#!/usr/bin/env bash
# Render the standard cover set into out/covers/ under the standard names (all JPEG):
#   bilibili.jpg                3840×2160 master (Bilibili shows ONE cover: 4:3 home feed, 16:9 video page)
#   bilibili_preview_4x3.jpg    centred 4:3 crop, as the home feed shows it
#   bilibili_preview_16x9.jpg   1920×1080, as the video page shows it
#   youtube.jpg                 1920×1080, < 2 MB
#   zh_3x4.jpg  zh_9x16.jpg     vertical covers (3:4 for 小红书-style feeds, 9:16 for Shorts / vertical feeds)
#   en_3x4.jpg  en_9x16.jpg     (optional)
#
# Usage: scripts/covers.sh [name=StillId ...]
#   defaults: bilibili=Cover-Bili youtube=Cover-EN zh_3x4=Cover-ZH-3x4 zh_9x16=Cover-ZH-9x16 en_3x4=Cover-EN-3x4 en_9x16=Cover-EN-9x16
#   e.g. scripts/covers.sh youtube=Cover2-EN          (override one id; name= with no id skips that cover)
# A still id that does not exist is reported and skipped. Runs the font check first (as finalize.sh; FONT_CHECK=0 skips).
set -euo pipefail
cd "${PAPER_VIDEO_ROOT:-$(dirname "$0")/..}"
# name=id pairs; later pairs (the arguments) win. Plain variables only: macOS ships bash 3.2 (no associative arrays).
PAIRS="bilibili=Cover-Bili youtube=Cover-EN zh_3x4=Cover-ZH-3x4 zh_9x16=Cover-ZH-9x16 en_3x4=Cover-EN-3x4 en_9x16=Cover-EN-9x16 $*"
still_id() { local id="" kv; for kv in $PAIRS; do [[ ${kv%%=*} == "$1" ]] && id=${kv#*=}; done; echo "$id"; }
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
mkdir -p out/covers
TMP=$(mktemp -d "${PAPER_VIDEO_TMPDIR:-${TMPDIR:-/tmp}}/covers.XXXXXX")  # the workspace drive when PAPER_VIDEO_TMPDIR is set
trap 'rm -rf "$TMP"' EXIT
IDS=$(npx remotion compositions --quiet 2>/dev/null | tr ' ' '\n')
for name in bilibili youtube zh_3x4 zh_9x16 en_3x4 en_9x16; do
  id=$(still_id "$name")
  [[ -z "$id" ]] && continue
  if ! grep -qx -- "$id" <<<"$IDS"; then echo "skip $name: no still '$id'"; continue; fi
  scale=1; [[ $name == bilibili ]] && scale=2
  npx remotion still "$id" "$TMP/$name.png" --scale=$scale --log=error
  ffmpeg -v error -y -i "$TMP/$name.png" -q:v 2 "out/covers/$name.jpg"
  if [[ $name == bilibili ]]; then
    ffmpeg -v error -y -i "$TMP/$name.png" -vf "crop=iw*0.75:ih,scale=1440:1080" -q:v 2 out/covers/bilibili_preview_4x3.jpg
    ffmpeg -v error -y -i "$TMP/$name.png" -vf "scale=1920:1080" -q:v 2 out/covers/bilibili_preview_16x9.jpg
  fi
  echo "$name.jpg  <- $id  ($(du -h "out/covers/$name.jpg" | cut -f1))"
done
size=$(stat -f %z out/covers/youtube.jpg 2>/dev/null || stat -c %s out/covers/youtube.jpg 2>/dev/null || echo 0)
(( size > 2000000 )) && echo "WARNING: youtube.jpg is over 2 MB — re-encode with a higher -q:v"
exit 0
