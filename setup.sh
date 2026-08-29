#!/bin/bash
VENV_DIR="$(pwd)/venv"
cd "$(dirname "$0")"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip3 install raylib==5.5.0.3 --break-system-packages