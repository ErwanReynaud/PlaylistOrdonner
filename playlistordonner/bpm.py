"""Récupération du BPM (tempo) des titres.

Deux sources, dans cet ordre :

1. l'API Spotify `/audio-features` (la plus fiable), quand l'application y a
   encore accès — Spotify l'a fermée aux applications créées après novembre
   2024 ;
2. l'API publique de Deezer, qui expose un champ `bpm` et ne demande aucune
   authentification. La correspondance se fait d'abord par code ISRC (exact),
   sinon par recherche titre + artiste.

Les BPM trouvés sont mis en cache sur le disque pour que les tris suivants
soient quasi instantanés.
"""

import json
import os
import re
import time
import unicodedata
import urllib.parse

from . import config
from .webclient import HttpError, request

DEEZER_API = "https://api.deezer.com"
CACHE_FILE = "cache_bpm.json"
NEGATIVE_TTL = 30 * 24 * 3600  # on retente un titre introuvable au bout d'un mois

# Deezer tolère 50 requêtes par tranche de 5 s : on reste large sous la limite.
_MIN_INTERVAL = 0.14
_last_call = [0.0]

# Au-delà de ce nombre d'échecs réseau d'affilée, on considère Deezer
# injoignable (coupure, pare-feu) et on termine le tri sans lui.
MAX_ECHECS = 6
_echecs = [0]


class DeezerUnavailable(Exception):
    """Deezer ne répond plus : le tri continue sans les BPM manquants."""


def _throttle():
    wait = _MIN_INTERVAL - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()


class BpmCache:
    def __init__(self):
        self.path = os.path.join(config.config_dir(), CACHE_FILE)
        self.data = {}
        self._dirty = False
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                self.data = loaded
        except (OSError, ValueError):
            self.data = {}

    def get(self, key):
        entry = self.data.get(key)
        if not isinstance(entry, dict):
            return None
        if entry.get("bpm") is None:
            if time.time() - float(entry.get("at") or 0) > NEGATIVE_TTL:
                return None
        return entry

    def put(self, key, bpm, source):
        self.data[key] = {"bpm": bpm, "source": source, "at": time.time()}
        self._dirty = True

    def save(self):
        if not self._dirty:
            return
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh)
            os.replace(tmp, self.path)
            self._dirty = False
        except OSError:
            pass


_PARENS = re.compile(r"[\(\[][^\)\]]*[\)\]]")
_SUFFIX = re.compile(
    r"\s-\s.*\b(remaster(ed)?|version|edit|mix|mono|stereo|live|radio|single|"
    r"deluxe|bonus|anniversary|remix)\b.*$",
    re.IGNORECASE,
)


def clean_title(title):
    text = _SUFFIX.sub("", str(title or ""))
    text = _PARENS.sub("", text)
    return " ".join(text.split()).strip(" -–—")


def _fold(text):
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _similar(a, b):
    """Score de ressemblance grossier entre deux titres (0 à 1)."""
    wa, wb = set(_fold(a).split()), set(_fold(b).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / float(len(wa | wb))


def _deezer_get(url):
    _throttle()
    try:
        result = request(url, retries=2, timeout=20)
    except HttpError as exc:
        _echecs[0] += 1
        if _echecs[0] >= MAX_ECHECS:
            raise DeezerUnavailable(str(exc))
        return None
    _echecs[0] = 0
    if not result.ok or not isinstance(result.data, dict):
        return None
    if result.data.get("error"):
        return None
    return result.data


def _bpm_of(payload):
    try:
        value = float(payload.get("bpm"))
    except (TypeError, ValueError, AttributeError):
        return None
    return value if value > 0 else None


def deezer_bpm(title, artist, isrc=None):
    """Renvoie (bpm, source) pour un titre, ou (None, None)."""
    if isrc:
        data = _deezer_get("%s/track/isrc:%s" % (DEEZER_API, urllib.parse.quote(isrc)))
        bpm = _bpm_of(data) if data else None
        if bpm:
            return bpm, "deezer-isrc"

    query = 'artist:"%s" track:"%s"' % (artist or "", clean_title(title))
    data = _deezer_get(
        "%s/search?%s" % (DEEZER_API, urllib.parse.urlencode({"q": query, "limit": 5}))
    )
    candidates = (data or {}).get("data") or []
    if not candidates:
        data = _deezer_get(
            "%s/search?%s"
            % (
                DEEZER_API,
                urllib.parse.urlencode(
                    {"q": "%s %s" % (artist or "", clean_title(title)), "limit": 5}
                ),
            )
        )
        candidates = (data or {}).get("data") or []

    best, best_score = None, 0.0
    for item in candidates:
        score = _similar(title, item.get("title"))
        score += _similar(artist, (item.get("artist") or {}).get("name"))
        if score > best_score:
            best, best_score = item, score
    if not best or best_score < 0.6:
        return None, None

    detail = _deezer_get("%s/track/%s" % (DEEZER_API, best.get("id")))
    bpm = _bpm_of(detail) if detail else None
    if bpm:
        return bpm, "deezer-recherche"
    return None, None


def fill_bpm(tracks, spotify_features=None, use_deezer=True, progress=None,
             stop=None, note=None):
    """Complète l'attribut `bpm` de chaque titre.

    `tracks` est une liste d'objets Track (voir sorter.py). Les valeurs déjà
    connues via Spotify sont conservées ; les autres sont cherchées sur Deezer
    puis mises en cache.
    """
    features = spotify_features or {}
    note = note or (lambda message: None)
    cache = BpmCache()
    _echecs[0] = 0
    todo = []

    for track in tracks:
        feat = features.get(track.track_id) if track.track_id else None
        tempo = None
        if feat:
            try:
                tempo = float(feat.get("tempo") or 0) or None
            except (TypeError, ValueError):
                tempo = None
        if tempo:
            track.bpm = tempo
            track.bpm_source = "spotify"
            continue
        cached = cache.get(track.cache_key)
        if cached is not None:
            track.bpm = cached.get("bpm")
            track.bpm_source = cached.get("source")
            continue
        todo.append(track)

    if not use_deezer:
        cache.save()
        if progress:
            progress(len(tracks), len(tracks))
        return

    done = len(tracks) - len(todo)
    if progress:
        progress(done, len(tracks))
    for index, track in enumerate(todo):
        if stop and stop():
            break
        try:
            bpm, source = deezer_bpm(track.title, track.main_artist, track.isrc)
        except DeezerUnavailable:
            note(
                "Deezer est injoignable (connexion réseau) : les %d titre(s) "
                "restants sont classés sans BPM, en fin de leur genre."
                % (len(todo) - index)
            )
            break
        track.bpm = bpm
        track.bpm_source = source
        cache.put(track.cache_key, bpm, source)
        done += 1
        if progress:
            progress(done, len(tracks))
    cache.save()
    if progress:
        progress(len(tracks), len(tracks))
