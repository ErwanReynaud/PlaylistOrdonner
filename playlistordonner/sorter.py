"""Modèle de titre et algorithme de tri.

Le classement final se fait en deux niveaux, dans cet ordre :

1. **par genre**, du moins énergique au plus énergique ;
2. **à l'intérieur de chaque genre**, par BPM croissant (du plus lent au plus
   rapide).

Le second critère ne peut donc jamais casser le premier : on trie les titres
à l'intérieur de leur groupe de genre, puis on concatène les groupes.
"""

from . import genres as genres_mod

GROUP_BY_FAMILY = "famille"
GROUP_BY_GENRE = "precis"


class Track:
    __slots__ = (
        "track_id", "uri", "title", "artists", "isrc", "duration_ms",
        "is_local", "position", "bpm", "bpm_source", "genre_raw",
        "group_label", "energy", "audio_energy",
    )

    def __init__(self, **kwargs):
        for name in self.__slots__:
            setattr(self, name, kwargs.get(name))
        self.artists = self.artists or []
        self.is_local = bool(self.is_local)

    @property
    def main_artist(self):
        return self.artists[0][1] if self.artists else ""

    @property
    def artist_names(self):
        return ", ".join(name for _, name in self.artists)

    @property
    def artist_ids(self):
        return [aid for aid, _ in self.artists if aid]

    @property
    def cache_key(self):
        if self.track_id:
            return "spotify:" + self.track_id
        return "nom:%s|%s" % (
            (self.title or "").lower().strip(),
            (self.main_artist or "").lower().strip(),
        )

    def __repr__(self):
        return "<Track %s — %s (%s BPM, %s)>" % (
            self.title, self.artist_names, self.bpm, self.group_label,
        )


def build_tracks(items):
    """Transforme les éléments d'une playlist Spotify en objets Track.

    Renvoie (titres, ignorés) ; `ignorés` contient les épisodes de podcast,
    les fichiers locaux et les entrées vides, que l'API ne sait pas réordonner.
    """
    tracks, skipped = [], []
    for position, item in enumerate(items or []):
        raw = (item or {}).get("track") or {}
        name = raw.get("name") or "(sans titre)"
        if not raw:
            skipped.append(("entrée vide", name))
            continue
        if raw.get("type") and raw.get("type") != "track":
            skipped.append(("épisode de podcast", name))
            continue
        if item.get("is_local") or not raw.get("id"):
            skipped.append(("fichier local", name))
            continue
        tracks.append(
            Track(
                track_id=raw.get("id"),
                uri=raw.get("uri") or ("spotify:track:" + raw["id"]),
                title=name,
                artists=[
                    (a.get("id"), a.get("name") or "")
                    for a in (raw.get("artists") or [])
                ],
                isrc=((raw.get("external_ids") or {}).get("isrc") or "").strip() or None,
                duration_ms=raw.get("duration_ms") or 0,
                is_local=bool(item.get("is_local")),
                position=position,
            )
        )
    return tracks, skipped


def assign_genres(tracks, artists_by_id, overrides=None, mode=GROUP_BY_FAMILY):
    """Attribue à chaque titre un genre, une famille et un score d'énergie."""
    overrides = overrides or {}
    for track in tracks:
        candidate_genres = []
        for artist_id in track.artist_ids:
            artist = artists_by_id.get(artist_id) or {}
            for genre in artist.get("genres") or []:
                if genre not in candidate_genres:
                    candidate_genres.append(genre)

        chosen = genres_mod.pick_genre(candidate_genres, overrides)
        track.genre_raw = chosen
        if not chosen:
            track.group_label = genres_mod.UNKNOWN_FAMILY
            track.energy = genres_mod.UNKNOWN_ENERGY
            continue
        family, energy, _ = genres_mod.classify(chosen, overrides)
        track.energy = energy
        track.group_label = family if mode == GROUP_BY_FAMILY else _pretty(chosen)


def _pretty(genre):
    small = {"et", "de", "du", "and", "of", "the", "n"}
    words = []
    for index, word in enumerate(str(genre).split()):
        words.append(word if (index and word.lower() in small) else word.capitalize())
    return " ".join(words)


class Group:
    __slots__ = ("label", "energy", "tracks")

    def __init__(self, label, energy):
        self.label = label
        self.energy = energy
        self.tracks = []

    @property
    def bpm_known(self):
        return sum(1 for t in self.tracks if t.bpm)

    def __repr__(self):
        return "<Group %s energy=%.1f n=%d>" % (self.label, self.energy, len(self.tracks))


def order_tracks(tracks, refine_with_audio=True):
    """Trie les titres : genres du plus calme au plus énergique, puis BPM.

    `refine_with_audio` mélange le score théorique du genre avec l'énergie
    réellement mesurée par Spotify sur les titres du groupe, quand elle est
    disponible pour au moins la moitié d'entre eux.
    """
    groups = {}
    for track in tracks:
        label = track.group_label or genres_mod.UNKNOWN_FAMILY
        group = groups.get(label)
        if group is None:
            group = groups[label] = Group(label, float(track.energy or genres_mod.DEFAULT_ENERGY))
        group.tracks.append(track)

    for group in groups.values():
        if group.label == genres_mod.UNKNOWN_FAMILY:
            group.energy = genres_mod.UNKNOWN_ENERGY
            continue
        measured = [t.audio_energy for t in group.tracks if t.audio_energy is not None]
        if refine_with_audio and len(measured) * 2 >= len(group.tracks) and measured:
            mean = sum(measured) / len(measured) * 100.0
            group.energy = 0.6 * group.energy + 0.4 * mean

    ordered_groups = sorted(groups.values(), key=lambda g: (g.energy, _fold(g.label)))

    ordered = []
    for group in ordered_groups:
        group.tracks.sort(key=_track_key)
        ordered.extend(group.tracks)
    return ordered, ordered_groups


def _track_key(track):
    """BPM croissant ; les titres sans BPM connu ferment leur groupe."""
    if track.bpm:
        return (0, float(track.bpm), _fold(track.title))
    return (1, 0.0, _fold(track.title))


def _fold(text):
    return str(text or "").casefold()


def summary(groups):
    lines = []
    for index, group in enumerate(groups, 1):
        bpms = [t.bpm for t in group.tracks if t.bpm]
        if bpms:
            span = "%d–%d BPM" % (round(min(bpms)), round(max(bpms)))
        else:
            span = "BPM inconnu"
        lines.append(
            "%2d. %-24s %3d titre%s  énergie %5.1f  %s"
            % (
                index,
                group.label,
                len(group.tracks),
                "s" if len(group.tracks) > 1 else " ",
                group.energy,
                span,
            )
        )
    return "\n".join(lines)
