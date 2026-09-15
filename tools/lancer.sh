#!/bin/bash
#
# Choisit un Python 3 capable d'ouvrir une fenêtre Tk, puis lance l'application.
#
# Pourquoi ce n'est pas trivial : « import tkinter » réussit avec le Python
# fourni par Apple (/usr/bin/python3), mais celui-ci s'appuie sur Tk 8.5.9,
# déprécié, qui fait tomber le processus au moment d'ouvrir une fenêtre sur les
# macOS récents. On essaie donc réellement d'ouvrir une fenêtre dans un
# sous-processus jetable, et on préfère Tk 8.6.
#
# Usage : lancer.sh <dossier-du-code> [arguments de l'application]

set -u

RESOURCES="${1:?dossier du code manquant}"
shift || true

LOG_DIR="$HOME/Library/Logs"
LOG="$LOG_DIR/PlaylistOrdonner.log"
mkdir -p "$LOG_DIR" 2>/dev/null || true

log() {
  printf '%s %s\n' "$(date '+%H:%M:%S')" "$1" >> "$LOG"
}

alert() {
  /usr/bin/osascript -e "display alert \"PlaylistOrdonner\" message \"$1\" as critical" >/dev/null 2>&1
}

# Ouvre puis referme une fenêtre Tk ; n'affiche la version de Tk qu'en cas de
# succès complet. Un interpréteur qui plante (signal) ne produit rien.
probe_tk() {
  local runner=(/usr/bin/perl -e 'alarm 25; exec @ARGV')
  [ -x /usr/bin/perl ] || runner=(env)   # perl fournit simplement un garde-fou
  "${runner[@]}" "$1" -c '
import tkinter
racine = tkinter.Tk()
racine.withdraw()
racine.update_idletasks()
print("TK=%s" % tkinter.TkVersion)
racine.destroy()
' 2>/dev/null | sed -n 's/^TK=//p' | head -1
}

# Du plus sûr au moins sûr. Le Python d'Apple passe en dernier : c'est lui qui
# porte le Tk 8.5.9 problématique.
candidats() {
  local chemin
  for chemin in /Library/Frameworks/Python.framework/Versions/*/bin/python3; do
    [ -x "$chemin" ] && echo "$chemin"
  done
  for chemin in /opt/homebrew/bin/python3.14 /opt/homebrew/bin/python3.13 \
                /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 \
                /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    [ -x "$chemin" ] && echo "$chemin"
  done
  # Anaconda / Miniconda : le Finder ne connaît pas le PATH du shell, il faut
  # donc aller chercher ces installations à leurs emplacements habituels.
  for chemin in "$HOME/anaconda3/bin/python3" "$HOME/opt/anaconda3/bin/python3" \
                "$HOME/miniconda3/bin/python3" "$HOME/opt/miniconda3/bin/python3" \
                "$HOME/miniforge3/bin/python3" "$HOME/mambaforge/bin/python3" \
                /opt/anaconda3/bin/python3 /opt/miniconda3/bin/python3; do
    [ -x "$chemin" ] && echo "$chemin"
  done
  chemin="$(command -v python3 2>/dev/null)"
  [ -n "$chemin" ] && [ -x "$chemin" ] && echo "$chemin"
  [ -x /usr/bin/python3 ] && echo /usr/bin/python3
}

log "--- démarrage ($(sw_vers -productVersion 2>/dev/null || echo macOS) $(uname -m))"

PYTHON=""
VERSION_TK=""
REPLI=""
REPLI_TK=""
VUS=""

while read -r candidat; do
  [ -n "$candidat" ] || continue
  case " $VUS " in *" $candidat "*) continue ;; esac
  VUS="$VUS $candidat"

  tk="$(probe_tk "$candidat")"
  if [ -z "$tk" ]; then
    log "écarté  : $candidat (ne sait pas ouvrir de fenêtre Tk)"
    continue
  fi
  log "candidat: $candidat (Tk $tk)"
  if awk "BEGIN{exit !($tk >= 8.6)}" 2>/dev/null; then
    PYTHON="$candidat"
    VERSION_TK="$tk"
    break
  fi
  if [ -z "$REPLI" ]; then
    REPLI="$candidat"
    REPLI_TK="$tk"
  fi
done <<EOF
$(candidats)
EOF

if [ -z "$PYTHON" ] && [ -n "$REPLI" ]; then
  PYTHON="$REPLI"
  VERSION_TK="$REPLI_TK"
  log "aucun Tk 8.6 trouvé, essai avec $PYTHON (Tk $VERSION_TK) — instable sur les macOS récents"
fi

if [ -z "$PYTHON" ]; then
  log "échec : aucun Python 3 ne sait ouvrir de fenêtre"
  alert "Aucun Python capable d'afficher une fenêtre n'a été trouvé sur ce Mac.\n\nLe plus simple : installe Python depuis python.org (https://www.python.org/downloads/macos/), puis relance PlaylistOrdonner.\n\nAvec Homebrew : brew install python-tk\n\nDétails dans ~/Library/Logs/PlaylistOrdonner.log"
  exit 1
fi

log "retenu  : $PYTHON (Tk $VERSION_TK)"
cd "$RESOURCES" || exit 1
"$PYTHON" -m playlistordonner "$@" >> "$LOG" 2>&1
CODE=$?

# Un code >= 128 signale une mort par signal : le processus a été tué, ce n'est
# pas une erreur applicative.
if [ "$CODE" -ge 128 ]; then
  log "l'interpréteur $PYTHON a été interrompu (code $CODE, Tk $VERSION_TK)"
  alert "PlaylistOrdonner s'est arrêté brutalement.\n\nPython utilisé : $PYTHON (Tk $VERSION_TK)\n\nSi Tk affiche 8.5, c'est la cause : installe Python depuis python.org ou lance « brew install python-tk », puis réessaie.\n\nDétails dans ~/Library/Logs/PlaylistOrdonner.log"
elif [ "$CODE" -ne 0 ]; then
  log "l'application s'est terminée avec le code $CODE"
fi
exit "$CODE"
