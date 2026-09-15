#!/bin/bash
# Double-clique sur ce fichier pour lancer PlaylistOrdonner sans construire
# l'application. (Si le double-clic ne marche pas, ouvre le Terminal dans ce
# dossier et lance :  chmod +x Lancer-PlaylistOrdonner.command )
HERE="$(cd "$(dirname "$0")" && pwd)"
exec "$HERE/tools/lancer.sh" "$HERE"
