"""Orchestration : lire une playlist, la trier, puis l'écrire sur Spotify."""

import datetime

from . import bpm as bpm_mod
from . import config, sorter
from .spotify import FeaturesUnavailable, SpotifyClient, SpotifyError

LIKED = "__titres_likes__"

DEST_NEW = "nouvelle"
DEST_IN_PLACE = "en_place"


class Cancelled(Exception):
    pass


class Report:
    def __init__(self):
        self.tracks = []
        self.groups = []
        self.skipped = []
        self.bpm_sources = {}
        self.playlist_name = ""
        self.target_name = ""
        self.target_url = ""
        self.written = False
        self.features_available = False

    @property
    def bpm_found(self):
        return sum(1 for t in self.tracks if t.bpm)

    def text(self):
        lines = [sorter.summary(self.groups), ""]
        lines.append(
            "%d titres classés, %d avec un BPM connu."
            % (len(self.tracks), self.bpm_found)
        )
        if self.bpm_sources:
            detail = ", ".join(
                "%s : %d" % (src, count) for src, count in sorted(self.bpm_sources.items())
            )
            lines.append("Sources de BPM — " + detail)
        if self.skipped:
            lines.append(
                "%d élément(s) ignoré(s) : %s"
                % (
                    len(self.skipped),
                    ", ".join("%s (%s)" % (name, why) for why, name in self.skipped[:5]),
                )
            )
        return "\n".join(lines)

    def tracklist(self):
        lines = []
        current = None
        for index, track in enumerate(self.tracks, 1):
            if track.group_label != current:
                current = track.group_label
                lines.append("")
                lines.append("=== %s ===" % current)
            lines.append(
                "%4d. %6s  %s — %s"
                % (
                    index,
                    ("%d" % round(track.bpm)) if track.bpm else "  ?  ",
                    track.title,
                    track.artist_names,
                )
            )
        return "\n".join(lines).strip()


class Engine:
    def __init__(self, authenticator, log=None, progress=None, stop=None):
        self.client = SpotifyClient(authenticator)
        self._log = log or (lambda message: None)
        self._progress = progress or (lambda done, total, label="": None)
        self._stop = stop or (lambda: False)
        self._user = None

    # -- utilitaires -----------------------------------------------------------
    def log(self, message):
        self._log(message)

    def check(self):
        if self._stop():
            raise Cancelled("Opération annulée.")

    def user(self):
        if self._user is None:
            self._user = self.client.me()
        return self._user

    # -- lecture -----------------------------------------------------------------
    def list_playlists(self):
        me = self.user()
        self.log("Connecté en tant que %s." % (me.get("display_name") or me.get("id")))
        authentification = getattr(self.client, "auth", None)
        manquantes = getattr(authentification, "missing_scopes", lambda: set())()
        if manquantes:
            self.log(
                "Autorisations manquantes (%s) : reconnecte-toi avec « Se "
                "connecter à Spotify » pour les accorder."
                % ", ".join(sorted(manquantes))
            )
        playlists = self.client.my_playlists()
        out = [
            {
                "id": LIKED,
                "name": "♥ Titres likés",
                "owner": me.get("id"),
                "total": None,
                "editable": False,
                "accessible": True,
            }
        ]
        for playlist in playlists:
            if not playlist or not playlist.get("id"):
                continue
            owner = (playlist.get("owner") or {}).get("id")
            # Depuis fin 2024, Spotify ferme ses propres playlists (éditoriales
            # et algorithmiques) aux applications récemment créées.
            de_spotify = owner == "spotify"
            nom = playlist.get("name") or "(sans nom)"
            out.append(
                {
                    "id": playlist["id"],
                    "name": nom + ("  — créée par Spotify" if de_spotify else ""),
                    "owner": owner,
                    "total": (playlist.get("tracks") or {}).get("total"),
                    "editable": owner == me.get("id") or bool(playlist.get("collaborative")),
                    "accessible": not de_spotify,
                }
            )
        return out

    def _load_items(self, playlist_id):
        def on_page(done, total):
            self._progress(done, total or done, "Lecture des titres")

        if playlist_id == LIKED:
            self.log("Lecture des titres likés…")
            return "Titres likés", self.client.saved_tracks(progress=on_page)
        meta = self.client.playlist(playlist_id)
        name = meta.get("name") or "Playlist"
        self.log("Lecture de « %s »…" % name)
        return name, self.client.playlist_tracks(playlist_id, progress=on_page)

    # -- traitement -----------------------------------------------------------------
    def analyse(self, playlist_id, group_mode=sorter.GROUP_BY_FAMILY,
                use_deezer=True, refine_with_audio=True):
        """Lit la playlist et calcule le nouvel ordre, sans rien écrire."""
        report = Report()
        report.playlist_name, items = self._load_items(playlist_id)
        self.check()

        tracks, skipped = sorter.build_tracks(items)
        report.skipped = skipped
        if not tracks:
            raise SpotifyError("Aucun titre exploitable dans cette playlist.")
        self.log("%d titre(s) à classer." % len(tracks))

        # 1. Genres : ils viennent des artistes, pas des titres.
        artist_ids = [aid for track in tracks for aid in track.artist_ids]
        self._progress(0, 1, "Genres des artistes")
        self.log("Récupération des genres de %d artiste(s)…" % len(set(artist_ids)))
        artists = self.client.artists(artist_ids)
        self.check()
        overrides = config.load_genre_overrides()
        sorter.assign_genres(tracks, artists, overrides, group_mode)
        self._progress(1, 1, "Genres des artistes")

        # 2. BPM : Spotify si l'API est ouverte, Deezer sinon.
        features = {}
        try:
            self.log("Demande des caractéristiques audio à Spotify…")
            features = self.client.audio_features([t.track_id for t in tracks])
            report.features_available = bool(features)
            self.log("Caractéristiques audio reçues pour %d titre(s)." % len(features))
        except FeaturesUnavailable:
            self.log(
                "L'API audio de Spotify n'est pas ouverte à cette application "
                "(restriction Spotify depuis fin 2024) — passage sur Deezer "
                "pour les BPM."
            )
        except SpotifyError as exc:
            self.log("Caractéristiques audio indisponibles (%s)." % exc)

        for track in tracks:
            feat = features.get(track.track_id) or {}
            try:
                track.audio_energy = float(feat["energy"])
            except (KeyError, TypeError, ValueError):
                track.audio_energy = None
        self.check()

        missing = sum(1 for t in tracks if not (features.get(t.track_id) or {}).get("tempo"))
        if missing and use_deezer:
            self.log("Recherche du BPM de %d titre(s) sur Deezer…" % missing)
        bpm_mod.fill_bpm(
            tracks,
            spotify_features=features,
            use_deezer=use_deezer,
            progress=lambda done, total: self._progress(done, total, "BPM"),
            stop=self._stop,
            note=self.log,
        )
        self.check()

        for track in tracks:
            if track.bpm:
                key = track.bpm_source or "inconnue"
                report.bpm_sources[key] = report.bpm_sources.get(key, 0) + 1

        # 3. Tri : genre croissant en énergie, puis BPM croissant.
        ordered, groups = sorter.order_tracks(tracks, refine_with_audio=refine_with_audio)
        report.tracks = ordered
        report.groups = groups
        found = report.bpm_found
        self.log(
            "Classement prêt : %d groupe(s) de genre, BPM connu pour %d/%d titres."
            % (len(groups), found, len(ordered))
        )
        if found < len(ordered):
            self.log(
                "Les %d titre(s) sans BPM sont placés en fin de leur genre."
                % (len(ordered) - found)
            )
        return report

    # -- écriture ---------------------------------------------------------------------
    def write(self, report, playlist_id, destination=DEST_NEW, new_name=None, public=False):
        uris = [t.uri for t in report.tracks]
        if destination == DEST_IN_PLACE:
            if playlist_id == LIKED:
                raise SpotifyError(
                    "Les titres likés ne peuvent pas être réordonnés : "
                    "choisis « nouvelle playlist »."
                )
            self.log("Réécriture de la playlist dans le nouvel ordre…")
            self.client.replace_tracks(
                playlist_id,
                uris,
                progress=lambda done, total: self._progress(done, total, "Écriture"),
            )
            report.target_name = report.playlist_name
            report.target_url = "https://open.spotify.com/playlist/%s" % playlist_id
            report.written = True
            self.log("Playlist « %s » réordonnée." % report.playlist_name)
            return report

        name = (new_name or "").strip() or _default_name(report.playlist_name)
        description = (
            "Trié par PlaylistOrdonner le %s : genres du plus calme au plus "
            "énergique, puis BPM croissant."
            % datetime.date.today().strftime("%d/%m/%Y")
        )
        self.log("Création de la playlist « %s »…" % name)
        created = self.client.create_playlist(self.user()["id"], name, description, public)
        self.client.add_tracks(
            created["id"],
            uris,
            progress=lambda done, total: self._progress(done, total, "Écriture"),
        )
        report.target_name = name
        report.target_url = (created.get("external_urls") or {}).get(
            "spotify", "https://open.spotify.com/playlist/%s" % created["id"]
        )
        report.written = True
        self.log("Playlist créée : %s" % report.target_url)
        return report


def _default_name(source_name):
    base = (source_name or "Playlist").strip()
    suffix = " (ordonnée)"
    if len(base) + len(suffix) > 100:
        base = base[: 100 - len(suffix)].rstrip()
    return base + suffix
