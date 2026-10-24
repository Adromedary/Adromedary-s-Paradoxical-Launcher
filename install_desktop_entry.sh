#!/usr/bin/env bash
# Adds the launcher to your applications menu (for you only). Usage:
#   ./install_desktop_entry.sh dist/ParadoxicalLauncher     (the built program)
#   ./install_desktop_entry.sh                              (from source: uses run_linux.sh)
set -e
cd "$(dirname "$0")"
TARGET=$(realpath "${1:-run_linux.sh}")
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$ICON_DIR" "$APP_DIR"
PY=${PYTHON:-python3}
if "$PY" -c "import PIL" 2>/dev/null; then
  "$PY" -c "from PIL import Image; im=Image.open('icon.ico'); im.size=max(im.info.get('sizes',[im.size])); im.save('$ICON_DIR/paradoxical-launcher.png')"
else
  cp icon.ico "$ICON_DIR/paradoxical-launcher.ico"
fi
cat > "$APP_DIR/paradoxical-launcher.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Adromedary's Paradoxical Launcher
Comment=Mod manager and launcher for Paradox games
Exec="$TARGET"
Path=$(dirname "$TARGET")
Icon=paradoxical-launcher
Terminal=false
Categories=Game;Utility;
StartupWMClass=Paradoxicallauncher
DESK
echo "Added to your applications menu: Adromedary's Paradoxical Launcher"
