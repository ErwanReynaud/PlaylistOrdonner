"""Client minimal de l'API Web Spotify."""

import urllib.parse

from .auth import AuthError
from .webclient import request

API = "https://api.spotify.com/v1"


class SpotifyError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class FeaturesUnavailable(SpotifyError):
    """L'endpoint /audio-features est fermé à cette application Spotify.

    Depuis fin 2024, Spotify ne l'ouvre plus aux applications nouvellement
    créées : on bascule alors sur une autre source de BPM.
    """


class SpotifyClient:
    def __init__(self, authenticator):
        self.auth = authenticator
        self._features_blocked = False

    # -- socle ---------------------------------------------------------------
    def _call(self, method, path, params=None, json_body=None, retry_auth=True):
        url = path if path.startswith("http") else API + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        token = self.auth.access_token()
        result = request(
            url,
            method=method,
            headers={"Authorization": "Bearer " + token},
            json_body=json_body,
        )
        if result.status == 401 and retry_auth:
            self.auth.refresh()
            return self._call(method, path, params, json_body, retry_auth=False)
        if not result.ok:
            raise SpotifyError(_message(result), result.status)
        return result.data

    def get(self, path, params=None):
        return self._call("GET", path, params=params)

    def post(self, path, json_body=None):
        return self._call("POST", path, json_body=json_body)

    def put(self, path, json_body=None):
        return self._call("PUT", path, json_body=json_body)

    def _paginate(self, path, params=None, limit_total=None, progress=None):
        params = dict(params or {})
        items = []
        page = self.get(path, params)
        while True:
            items.extend(page.get("items") or [])
            if progress:
                progress(len(items), page.get("total") or len(items))
            if limit_total and len(items) >= limit_total:
                return items[:limit_total]
            nxt = page.get("next")
            if not nxt:
                return items
            page = self.get(nxt)

    # -- lectures -------------------------------------------------------------
    def me(self):
        return self.get("/me")

    def my_playlists(self, progress=None):
        return self._paginate("/me/playlists", {"limit": 50}, progress=progress)

    def playlist(self, playlist_id):
        return self.get(
            "/playlists/" + playlist_id,
            {"fields": "id,name,owner(id,display_name),snapshot_id,tracks(total),public,collaborative"},
        )

    def playlist_tracks(self, playlist_id, progress=None):
        fields = (
            "next,total,items(is_local,added_at,track(id,uri,name,duration_ms,"
            "is_playable,external_ids(isrc),type,artists(id,name),album(name,release_date)))"
        )
        return self._paginate(
            "/playlists/%s/tracks" % playlist_id,
            {"limit": 100, "fields": fields, "additional_types": "track"},
            progress=progress,
        )

    def saved_tracks(self, progress=None):
        return self._paginate("/me/tracks", {"limit": 50}, progress=progress)

    def artists(self, artist_ids):
        """Genres des artistes, par paquets de 50."""
        out = {}
        ids = [a for a in dict.fromkeys(artist_ids) if a]
        for chunk in _chunks(ids, 50):
            data = self.get("/artists", {"ids": ",".join(chunk)})
            for artist in data.get("artists") or []:
                if artist and artist.get("id"):
                    out[artist["id"]] = artist
        return out

    def audio_features(self, track_ids):
        """Caractéristiques audio (tempo, energy), par paquets de 100.

        Lève FeaturesUnavailable si Spotify refuse l'accès à l'endpoint.
        """
        if self._features_blocked:
            raise FeaturesUnavailable("Endpoint /audio-features indisponible.")
        out = {}
        ids = [t for t in dict.fromkeys(track_ids) if t]
        for chunk in _chunks(ids, 100):
            try:
                data = self.get("/audio-features", {"ids": ",".join(chunk)})
            except SpotifyError as exc:
                if exc.status in (401, 403, 404):
                    self._features_blocked = True
                    raise FeaturesUnavailable(str(exc))
                raise
            for feat in data.get("audio_features") or []:
                if feat and feat.get("id"):
                    out[feat["id"]] = feat
        return out

    # -- écritures --------------------------------------------------------------
    def create_playlist(self, user_id, name, description="", public=False):
        return self.post(
            "/users/%s/playlists" % user_id,
            {"name": name, "description": description, "public": bool(public)},
        )

    def add_tracks(self, playlist_id, uris, progress=None):
        done = 0
        for chunk in _chunks(list(uris), 100):
            self.post("/playlists/%s/tracks" % playlist_id, {"uris": chunk})
            done += len(chunk)
            if progress:
                progress(done, len(uris))

    def replace_tracks(self, playlist_id, uris, progress=None):
        """Réécrit intégralement le contenu d'une playlist, dans l'ordre donné."""
        uris = list(uris)
        first, rest = uris[:100], uris[100:]
        self.put("/playlists/%s/tracks" % playlist_id, {"uris": first})
        done = len(first)
        if progress:
            progress(done, len(uris))
        for chunk in _chunks(rest, 100):
            self.post("/playlists/%s/tracks" % playlist_id, {"uris": chunk})
            done += len(chunk)
            if progress:
                progress(done, len(uris))


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _message(result):
    error = (result.data or {}).get("error")
    if isinstance(error, dict):
        detail = error.get("message") or ""
    elif isinstance(error, str):
        detail = (result.data or {}).get("error_description") or error
    else:
        detail = ""
    hints = {
        401: "Session expirée ou autorisation manquante.",
        403: "Spotify refuse cette action (droits insuffisants sur la playlist "
             "ou API non accessible à ton application).",
        404: "Introuvable.",
        429: "Trop de requêtes, Spotify demande de patienter.",
    }
    hint = hints.get(result.status, "")
    parts = [p for p in (detail, hint) if p]
    return "Erreur Spotify %s : %s" % (result.status, " ".join(parts) or "échec inconnu")


__all__ = ["SpotifyClient", "SpotifyError", "FeaturesUnavailable", "AuthError"]
