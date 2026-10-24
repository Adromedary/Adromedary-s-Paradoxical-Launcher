#!/usr/bin/env bash
# Adromedary's Paradoxical Launcher 2.0.1: build a single Linux program (dist/ParadoxicalLauncher).
# Needs Python 3.10+ with Tk (Debian/Ubuntu: sudo apt install python3 python3-venv python3-tk;
# Fedora: sudo dnf install python3 python3-tkinter; Arch: sudo pacman -S python tk).
set -e
cd "$(dirname "$0")"
echo "=== Adromedary's Paradoxical Launcher 2.0.1: building for Linux ==="
PY=${PYTHON:-python3}
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3 was not found. Install python3, python3-venv and python3-tk from your distribution."; exit 1
fi
if ! "$PY" -c "import tkinter" 2>/dev/null; then
  echo "Python's Tk support is missing. Debian/Ubuntu: sudo apt install python3-tk  ·  Fedora: sudo dnf install python3-tkinter  ·  Arch: sudo pacman -S tk"; exit 1
fi
if [ ! -f icon.ico ]; then echo "icon.ico is missing: it must sit next to build_linux.sh."; exit 1; fi
"$PY" -m venv .build-venv
. .build-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --upgrade -r requirements.txt pyinstaller
# The 'verify you are human' check window (optional; needs GTK WebKit or Qt WebEngine on the system).
python -m pip install --upgrade pywebview || echo "NOTE: pywebview could not be installed. Building without the check window."
python -m PyInstaller --noconfirm --clean --onefile --windowed --name ParadoxicalLauncher \
  --add-data "icon.ico:." --collect-all customtkinter --collect-all curl_cffi --collect-all webview \
  --collect-data certifi --hidden-import PIL._tkinter_finder paradoxical_launcher.py
deactivate
chmod +x dist/ParadoxicalLauncher
echo
echo "Done. Your app: $(pwd)/dist/ParadoxicalLauncher"
echo "Put it in a folder of its own: it keeps its settings and downloads next to itself."
echo "Optional: ./install_desktop_entry.sh dist/ParadoxicalLauncher adds it to your applications menu."
