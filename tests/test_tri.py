"""Tests du classement : genres croissants en énergie, puis BPM croissants."""

import unittest

from playlistordonner import engine as engine_mod
from playlistordonner import genres, sorter
from playlistordonner.cli import _strip_uri
from playlistordonner.engine import Engine, Report


def make_item(track_id, title, artist_id, artist_name):
    return {
        "is_local": False,
        "track": {
            "id": track_id,
            "uri": "spotify:track:%s" % track_id,
            "name": title,
            "type": "track",
            "artists": [{"id": artist_id, "name": artist_name}],
            "external_ids": {"isrc": "FR%s" % track_id},
            "duration_ms": 200000,
        },
    }


class TestGenres(unittest.TestCase):
    def test_ordre_des_familles(self):
        calme = genres.classify("ambient")[1]
        moyen = genres.classify("pop")[1]
        fort = genres.classify("death metal")[1]
        self.assertLess(calme, moyen)
        self.assertLess(moyen, fort)

    def test_mot_cle_le_plus_a_droite(self):
        self.assertEqual(genres.classify("chill house")[0], "House / Deep")
        self.assertEqual(genres.classify("pop punk")[0], "Punk")
        self.assertEqual(genres.classify("melodic death metal")[0], "Métal")

    def test_les_nuances_ajustent_lenergie(self):
        self.assertGreater(genres.classify("hard techno")[1], genres.classify("techno")[1])
        self.assertLess(genres.classify("chill house")[1], genres.classify("house")[1])

    def test_frontieres_de_mots(self):
        # "rap" ne doit pas matcher l'intérieur d'un autre mot
        self.assertEqual(genres.classify("trapped soul")[0], "Soul / R&B")

    def test_genre_absent_place_en_dernier(self):
        self.assertEqual(genres.classify("")[1], genres.UNKNOWN_ENERGY)

    def test_table_perso_prioritaire(self):
        family, energy, known = genres.classify("pop", {"pop": 5.0})
        self.assertEqual(energy, 5.0)
        self.assertTrue(known)


class TestTri(unittest.TestCase):
    def setUp(self):
        self.items = [
            make_item("t1", "Metal rapide", "a_metal", "Metal Band"),
            make_item("t2", "Ambient lent", "a_amb", "Ambient Artist"),
            make_item("t3", "Metal lent", "a_metal", "Metal Band"),
            make_item("t4", "Pop moyenne", "a_pop", "Pop Star"),
            make_item("t5", "Pop sans bpm", "a_pop", "Pop Star"),
            make_item("t6", "Pop rapide", "a_pop", "Pop Star"),
        ]
        self.artists = {
            "a_metal": {"id": "a_metal", "genres": ["death metal"]},
            "a_amb": {"id": "a_amb", "genres": ["ambient"]},
            "a_pop": {"id": "a_pop", "genres": ["dance pop"]},
        }
        self.bpms = {"t1": 190.0, "t2": 60.0, "t3": 110.0,
                     "t4": 120.0, "t5": None, "t6": 140.0}

    def _ordonne(self):
        tracks, _ = sorter.build_tracks(self.items)
        sorter.assign_genres(tracks, self.artists)
        for track in tracks:
            track.bpm = self.bpms[track.track_id]
        return sorter.order_tracks(tracks, refine_with_audio=False)

    def test_genres_du_plus_calme_au_plus_energique(self):
        _, groups = self._ordonne()
        self.assertEqual([g.label for g in groups], ["Ambient / Drone", "Pop", "Métal"])
        self.assertEqual(sorted(g.energy for g in groups), [g.energy for g in groups])

    def test_bpm_croissant_dans_chaque_genre(self):
        ordered, groups = self._ordonne()
        for group in groups:
            bpms = [t.bpm for t in group.tracks if t.bpm]
            self.assertEqual(bpms, sorted(bpms), group.label)

    def test_le_bpm_ne_casse_jamais_lordre_des_genres(self):
        """Un titre très rapide dans un genre calme reste avant un genre plus dur."""
        ordered, _ = self._ordonne()
        labels = [t.group_label for t in ordered]
        # chaque genre forme un bloc contigu
        self.assertEqual(len(labels), len(self.items))
        blocs = [label for index, label in enumerate(labels)
                 if index == 0 or label != labels[index - 1]]
        self.assertEqual(len(blocs), len(set(blocs)))
        self.assertEqual(blocs, ["Ambient / Drone", "Pop", "Métal"])

    def test_titres_sans_bpm_en_fin_de_groupe(self):
        ordered, groups = self._ordonne()
        pop = [g for g in groups if g.label == "Pop"][0]
        self.assertIsNone(pop.tracks[-1].bpm)
        self.assertEqual(pop.tracks[-1].title, "Pop sans bpm")

    def test_groupe_inconnu_en_dernier(self):
        self.items.append(make_item("t7", "Mystère", "a_x", "Inconnu"))
        self.artists["a_x"] = {"id": "a_x", "genres": []}
        self.bpms["t7"] = 100.0
        _, groups = self._ordonne()
        self.assertEqual(groups[-1].label, genres.UNKNOWN_FAMILY)

    def test_mode_genre_precis(self):
        tracks, _ = sorter.build_tracks(self.items)
        sorter.assign_genres(tracks, self.artists, mode=sorter.GROUP_BY_GENRE)
        labels = {t.group_label for t in tracks}
        self.assertIn("Death Metal", labels)
        self.assertIn("Dance Pop", labels)


class TestConstruction(unittest.TestCase):
    def test_ignore_locaux_et_podcasts(self):
        items = [
            make_item("t1", "Normal", "a", "A"),
            {"is_local": True, "track": {"id": None, "name": "Fichier local", "type": "track"}},
            {"track": {"id": "e1", "name": "Épisode", "type": "episode"}},
            {"track": None},
        ]
        tracks, skipped = sorter.build_tracks(items)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(len(skipped), 3)

    def test_isrc_et_artistes(self):
        tracks, _ = sorter.build_tracks([make_item("t1", "Titre", "a1", "Artiste")])
        self.assertEqual(tracks[0].isrc, "FRt1")
        self.assertEqual(tracks[0].main_artist, "Artiste")
        self.assertEqual(tracks[0].cache_key, "spotify:t1")


class FauxClient:
    """Client Spotify de substitution pour tester le moteur hors ligne."""

    def __init__(self, items, artists, features=None):
        self.items = items
        self.artists_data = artists
        self.features_data = features or {}
        self.created = None
        self.added = []
        self.replaced = None

    def me(self):
        return {"id": "chef", "display_name": "Chef", "country": "FR"}

    def my_playlists(self, progress=None):
        return [{"id": "p1", "name": "Ma playlist", "owner": {"id": "chef"},
                 "tracks": {"total": len(self.items)}}]

    def playlist(self, playlist_id):
        return {"id": playlist_id, "name": "Ma playlist", "owner": {"id": "chef"},
                "tracks": {"total": len(self.items)}}

    def playlist_tracks(self, playlist_id, progress=None, note=None, market=None):
        self.market = market
        return self.items

    def artists(self, artist_ids):
        return {aid: self.artists_data[aid] for aid in set(artist_ids) if aid in self.artists_data}

    def audio_features(self, track_ids):
        return {tid: self.features_data[tid] for tid in track_ids if tid in self.features_data}

    def create_playlist(self, user_id, name, description="", public=False):
        self.created = {"id": "new1", "name": name, "public": public,
                        "external_urls": {"spotify": "https://open.spotify.com/playlist/new1"}}
        return self.created

    def add_tracks(self, playlist_id, uris, progress=None):
        self.added = list(uris)

    def replace_tracks(self, playlist_id, uris, progress=None):
        self.replaced = list(uris)


class TestMoteur(unittest.TestCase):
    def setUp(self):
        self.items = [
            make_item("t1", "Metal rapide", "a_metal", "Metal Band"),
            make_item("t2", "Ambient lent", "a_amb", "Ambient Artist"),
            make_item("t3", "Metal lent", "a_metal", "Metal Band"),
        ]
        artists = {
            "a_metal": {"id": "a_metal", "genres": ["death metal"]},
            "a_amb": {"id": "a_amb", "genres": ["ambient"]},
        }
        features = {
            "t1": {"id": "t1", "tempo": 190.0, "energy": 0.98},
            "t2": {"id": "t2", "tempo": 60.0, "energy": 0.05},
            "t3": {"id": "t3", "tempo": 110.0, "energy": 0.9},
        }
        self.faux = FauxClient(self.items, artists, features)
        self._original = engine_mod.SpotifyClient
        engine_mod.SpotifyClient = lambda auth: self.faux
        self.engine = Engine(authenticator=None)

    def tearDown(self):
        engine_mod.SpotifyClient = self._original

    def test_analyse_complete(self):
        report = self.engine.analyse("p1", use_deezer=False)
        self.assertEqual([t.title for t in report.tracks],
                         ["Ambient lent", "Metal lent", "Metal rapide"])
        self.assertEqual(report.bpm_found, 3)
        self.assertEqual(report.bpm_sources, {"spotify": 3})
        self.assertIn("Ambient / Drone", report.text())

    def test_ecriture_nouvelle_playlist(self):
        report = self.engine.analyse("p1", use_deezer=False)
        self.engine.write(report, "p1", destination=engine_mod.DEST_NEW)
        self.assertEqual(self.faux.created["name"], "Ma playlist (ordonnée)")
        self.assertEqual(self.faux.added,
                         ["spotify:track:t2", "spotify:track:t3", "spotify:track:t1"])
        self.assertTrue(report.written)

    def test_ecriture_en_place(self):
        report = self.engine.analyse("p1", use_deezer=False)
        self.engine.write(report, "p1", destination=engine_mod.DEST_IN_PLACE)
        self.assertEqual(self.faux.replaced,
                         ["spotify:track:t2", "spotify:track:t3", "spotify:track:t1"])

    def test_le_pays_du_compte_est_transmis(self):
        """Spotify a besoin du marché pour lister les titres d'une playlist."""
        self.engine.analyse("p1", use_deezer=False)
        self.assertEqual(self.faux.market, "FR")

    def test_playlists_de_spotify_signalees(self):
        self.faux.my_playlists = lambda progress=None: [
            {"id": "p1", "name": "La mienne", "owner": {"id": "chef"},
             "tracks": {"total": 3}},
            {"id": "p2", "name": "Découvertes de la semaine",
             "owner": {"id": "spotify"}, "tracks": {"total": 30}},
        ]
        listing = self.engine.list_playlists()
        par_id = {p["id"]: p for p in listing}
        self.assertTrue(par_id["p1"]["accessible"])
        self.assertFalse(par_id["p2"]["accessible"])
        self.assertIn("créée par Spotify", par_id["p2"]["name"])
        self.assertTrue(par_id[engine_mod.LIKED]["accessible"])

    def test_titres_likes_non_reordonnables(self):
        report = Report()
        report.tracks = []
        with self.assertRaises(Exception):
            self.engine.write(report, engine_mod.LIKED,
                              destination=engine_mod.DEST_IN_PLACE)


class TestDivers(unittest.TestCase):
    def test_extraction_identifiant(self):
        self.assertEqual(_strip_uri("spotify:playlist:abc123"), "abc123")
        self.assertEqual(
            _strip_uri("https://open.spotify.com/playlist/abc123?si=xyz"), "abc123")
        self.assertEqual(_strip_uri("  abc123 "), "abc123")

    def test_nom_par_defaut_tronque_a_100(self):
        nom = engine_mod._default_name("x" * 120)
        self.assertLessEqual(len(nom), 100)
        self.assertTrue(nom.endswith("(ordonnée)"))


if __name__ == "__main__":
    unittest.main()


class TestPanneDeezer(unittest.TestCase):
    """Une panne réseau côté Deezer ne doit jamais faire échouer le tri."""

    def setUp(self):
        from playlistordonner import bpm as bpm_mod

        self.bpm_mod = bpm_mod
        self._original = bpm_mod.deezer_bpm

        def toujours_en_panne(*_args, **_kwargs):
            raise bpm_mod.DeezerUnavailable("réseau coupé")

        bpm_mod.deezer_bpm = toujours_en_panne
        self._cache = bpm_mod.BpmCache
        bpm_mod.BpmCache = _CacheMemoire

    def tearDown(self):
        self.bpm_mod.deezer_bpm = self._original
        self.bpm_mod.BpmCache = self._cache

    def test_le_tri_aboutit_sans_deezer(self):
        items = [make_item("t%d" % i, "Titre %d" % i, "a1", "Artiste") for i in range(5)]
        tracks, _ = sorter.build_tracks(items)
        sorter.assign_genres(tracks, {"a1": {"id": "a1", "genres": ["dance pop"]}})
        notes = []
        self.bpm_mod.fill_bpm(tracks, spotify_features={}, use_deezer=True, note=notes.append)
        ordered, groups = sorter.order_tracks(tracks, refine_with_audio=False)
        self.assertEqual(len(ordered), 5)
        self.assertEqual([g.label for g in groups], ["Pop"])
        self.assertTrue(notes and "injoignable" in notes[0])


class _CacheMemoire:
    """Cache de BPM en mémoire, pour ne pas écrire sur le disque pendant les tests."""

    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def put(self, key, bpm, source):
        self.data[key] = {"bpm": bpm, "source": source, "at": 0}

    def save(self):
        pass


class TestListeCollee(unittest.TestCase):
    """Voie de secours : classer des titres lus un par un par identifiant."""

    def test_extraction_des_identifiants(self):
        from playlistordonner.liens import identifiants_de_titres

        texte = (
            "https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp?si=x\n"
            "https://open.spotify.com/intl-fr/track/7ouMYWpwJ422jRcDASZB7P\n"
            "spotify:track:0eGsygTp906u18L0Oimnem\n"
            "1301WleyT98MSxVHPZCA6M\n"
            "du texte sans lien\n"
            "https://open.spotify.com/album/4m2880jivSbbyEGAKfITCa\n"
            "https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp\n"
        )
        trouves = identifiants_de_titres(texte)
        self.assertEqual(trouves, [
            "3n3Ppam7vgaVa1iaRUc9Lp", "7ouMYWpwJ422jRcDASZB7P",
            "0eGsygTp906u18L0Oimnem", "1301WleyT98MSxVHPZCA6M",
        ])

    def test_texte_vide(self):
        from playlistordonner.liens import identifiants_de_titres

        self.assertEqual(identifiants_de_titres(""), [])
        self.assertEqual(identifiants_de_titres(None), [])

    def test_classement_depuis_identifiants(self):
        items = [
            make_item("t1", "Metal rapide", "a_metal", "Metal Band"),
            make_item("t2", "Ambient lent", "a_amb", "Ambient Artist"),
        ]
        artists = {
            "a_metal": {"id": "a_metal", "genres": ["death metal"]},
            "a_amb": {"id": "a_amb", "genres": ["ambient"]},
        }
        features = {
            "t1": {"id": "t1", "tempo": 190.0, "energy": 0.98},
            "t2": {"id": "t2", "tempo": 60.0, "energy": 0.05},
        }
        faux = FauxClient(items, artists, features)
        faux.tracks = lambda ids, market=None: [
            i["track"] for i in items if i["track"]["id"] in ids
        ]
        original = engine_mod.SpotifyClient
        engine_mod.SpotifyClient = lambda auth: faux
        try:
            moteur = Engine(authenticator=None)
            report = moteur.analyse_identifiants(["t1", "t2"], use_deezer=False)
        finally:
            engine_mod.SpotifyClient = original
        self.assertEqual([t.title for t in report.tracks],
                         ["Ambient lent", "Metal rapide"])
        self.assertEqual(report.playlist_name, "Sélection")

    def test_liste_vide_refusee(self):
        from playlistordonner.spotify import SpotifyError

        faux = FauxClient([], {}, {})
        original = engine_mod.SpotifyClient
        engine_mod.SpotifyClient = lambda auth: faux
        try:
            moteur = Engine(authenticator=None)
            with self.assertRaises(SpotifyError):
                moteur.analyse_identifiants([])
        finally:
            engine_mod.SpotifyClient = original
