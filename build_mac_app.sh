#!/bin/bash
#
# Fabrique PlaylistOrdonner.app, une application macOS double-cliquable.
#
#   ./build_mac_app.sh              construit et installe dans ~/Applications
#   ./build_mac_app.sh --no-install construit seulement dans ./dist
#
# Aucune dépendance : le bundle embarque le code Python et s'appuie sur le
# Python 3 déjà présent sur le Mac.

set -euo pipefail

APP_NAME="PlaylistOrdonner"
BUNDLE_ID="fr.erwanreynaud.playlistordonner"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="$HERE/dist"
APP="$DIST/$APP_NAME.app"
INSTALL_DIR="$HOME/Applications"
DO_INSTALL=1

for arg in "$@"; do
  case "$arg" in
    --no-install) DO_INSTALL=0 ;;
    --install-dir=*) INSTALL_DIR="${arg#*=}" ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Option inconnue : $arg" >&2; exit 2 ;;
  esac
done

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$HERE/playlistordonner/__init__.py")"
VERSION="${VERSION:-1.0.0}"

find_python() {
  local candidate
  for candidate in /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    [ -x "$candidate" ] && { echo "$candidate"; return 0; }
  done
  command -v python3 2>/dev/null || return 1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
  echo "Erreur : aucun Python 3 trouvé. Lance « xcode-select --install » puis réessaie." >&2
  exit 1
fi

echo "==> Construction de $APP_NAME $VERSION"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# --- code de l'application --------------------------------------------------
mkdir -p "$APP/Contents/Resources/playlistordonner"
cp "$HERE"/playlistordonner/*.py "$APP/Contents/Resources/playlistordonner/"

# --- icône ------------------------------------------------------------------
if command -v iconutil >/dev/null 2>&1; then
  echo "==> Génération de l'icône"
  ICONSET="$DIST/$APP_NAME.iconset"
  rm -rf "$ICONSET"
  "$PYTHON" "$HERE/tools/make_icon.py" "$ICONSET" >/dev/null
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/$APP_NAME.icns"
  rm -rf "$ICONSET"
else
  echo "==> iconutil introuvable : l'application gardera l'icône générique."
fi

# --- lanceur ----------------------------------------------------------------
cat > "$APP/Contents/MacOS/$APP_NAME" <<'LAUNCHER'
#!/bin/bash
# Lanceur du bundle : trouve un Python 3 muni de Tkinter, puis démarre l'app.
BUNDLE="$(cd "$(dirname "$0")/.." && pwd)"
RESOURCES="$BUNDLE/Resources"
LOG_DIR="$HOME/Library/Logs"
LOG="$LOG_DIR/PlaylistOrdonner.log"
mkdir -p "$LOG_DIR"

alert() {
  /usr/bin/osascript -e "display alert \"PlaylistOrdonner\" message \"$1\" as critical" >/dev/null 2>&1
}

PYTHON=""
for candidate in /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 2>/dev/null)"; do
  [ -n "$candidate" ] && [ -x "$candidate" ] || continue
  if "$candidate" -c 'import tkinter' >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  alert "Python 3 avec Tkinter est introuvable sur ce Mac. Ouvre le Terminal, lance « xcode-select --install », puis relance PlaylistOrdonner."
  exit 1
fi

cd "$RESOURCES" || exit 1
{
  echo "--- $(date) : démarrage avec $PYTHON"
} >> "$LOG"
exec "$PYTHON" -m playlistordonner >> "$LOG" 2>&1
LAUNCHER
chmod +x "$APP/Contents/MacOS/$APP_NAME"

# --- Info.plist -------------------------------------------------------------
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleExecutable</key><string>$APP_NAME</string>
  <key>CFBundleIconFile</key><string>$APP_NAME</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>Erwan Reynaud</string>
</dict>
</plist>
PLIST

# macOS met en cache les icônes : on force la relecture du bundle.
touch "$APP"

echo "==> Bundle prêt : $APP"

if [ "$DO_INSTALL" -eq 1 ]; then
  mkdir -p "$INSTALL_DIR"
  rm -rf "$INSTALL_DIR/$APP_NAME.app"
  cp -R "$APP" "$INSTALL_DIR/"
  touch "$INSTALL_DIR/$APP_NAME.app"
  echo "==> Installé dans $INSTALL_DIR/$APP_NAME.app"
  echo
  echo "C'est bon, chef ! Ouvre le Finder sur $INSTALL_DIR et double-clique"
  echo "sur $APP_NAME. Tu peux aussi le glisser dans le Dock."
  command -v open >/dev/null 2>&1 && open -R "$INSTALL_DIR/$APP_NAME.app" || true
else
  echo "==> Non installé (--no-install). Double-clique sur le bundle ci-dessus."
fi
