#!/usr/bin/env bash
set -euo pipefail

read -rp "Path to SimpleScreenRecorder file (default: recording.mkv): " SRC
SRC=${SRC:-recording.mkv}

if [[ ! -f "$SRC" ]]; then
  echo "File '$SRC' not found." >&2
  exit 1
fi

read -rp "Output base name (default: README-demo): " BASE
BASE=${BASE:-README-demo}

read -rp "Create GIF (g) or MP4 (m) [g/m]? (default: g): " MODE
MODE=${MODE:-g}

if [[ "$MODE" =~ ^[Gg]$ ]]; then
  OUT="${BASE}.gif"
  echo "Creating GIF -> $OUT"
  ffmpeg -y -i "$SRC" \
    -vf "fps=15,scale=960:-1:flags=lanczos" \
    -c:v gif -loop 0 "$OUT"

  printf 'GIF ready. Add with: ![Demo](%s)\n' "$OUT"

else
  OUT="${BASE}.mp4"
  echo "Creating MP4 -> $OUT"
  ffmpeg -y -i "$SRC" \
    -vf "scale=960:-1" \
    -c:v libx264 -preset veryfast -crf 23 \
    -pix_fmt yuv420p \
    "$OUT"

  THUMB="${BASE}.png"
  echo "Capturing thumbnail -> $THUMB"
  ffmpeg -y -i "$OUT" -ss 00:00:03 -vframes 1 "$THUMB"

  cat <<EOF

MP4 and thumbnail ready.
Use markdown like:
[![Demo]($THUMB)]($OUT)

EOF
fi
