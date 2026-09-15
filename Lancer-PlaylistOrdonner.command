#!/bin/bash
# Double-clique sur ce fichier pour lancer PlaylistOrdonner sans construire
# l'application. (Si le double-clic ne marche pas, ouvre le Terminal dans ce
# dossier et lance :  chmod +x Lancer-PlaylistOrdonner.command )
cd "$(dirname "$0")" || exit 1

PYTHON=""
for candidate in /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 2>/dev/null)"; do
  [ -n "$candidate" ] && [ -x "$candidate" ] || continue
  if "$candidate" -c 'import tkinter' >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "Python 3 avec Tkinter est introuvable."
  echo "Ouvre le Terminal et lance : xcode-select --install"
  read -r -p "Appuie sur Entrée pour fermer." _
  exit 1
fi

exec "$PYTHON" -m playlistordonner
