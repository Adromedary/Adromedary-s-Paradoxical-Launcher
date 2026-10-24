#!/usr/bin/env bash
# Run Adromedary's Paradoxical Launcher from source on Linux (first run sets up a private Python environment).
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
if ! "$PY" -c "import tkinter" 2>/dev/null; then
  echo "Python's Tk support is missing. Debian/Ubuntu: sudo apt install python3-tk  ·  Fedora: sudo dnf install python3-tkinter  ·  Arch: sudo pacman -S tk"; exit 1
fi
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python -m pip install pywebview || echo "NOTE: pywebview not installed: sites with a human check are skipped."
fi
exec .venv/bin/python paradoxical_launcher.py "$@"
