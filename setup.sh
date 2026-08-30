#!/bin/bash
# SUI setup: create a venv, install raylib (+ a portable ffmpeg), generate the
# demo artwork, and launch the demo layout.
set -e
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
  python3 -m venv venv
fi
# Use `python -m pip` (the venv's `pip` shim can point at a stale interpreter).
source venv/bin/activate
python -m pip install --upgrade pip -q
python -m pip install -q raylib==6.0.1.0 imageio-ffmpeg

# ffmpeg is required for video decoding; prefer the system binary, else the one
# bundled with imageio-ffmpeg (installed above).
if ! command -v ffmpeg >/dev/null 2>&1 && ! python -c "import imageio_ffmpeg" >/dev/null 2>&1; then
  echo "warning: no ffmpeg found; video playback will be disabled (install ffmpeg or imageio-ffmpeg)."
fi

# Generate the procedural artwork (logo, animation, video frames + .mp4) once.
python make_assets.py

# Launch the demo UI (pass a layout path as $1 to use a different one).
python box.py "${1:-examples/demo.sui}"
