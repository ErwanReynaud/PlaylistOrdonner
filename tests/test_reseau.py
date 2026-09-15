"""Tests de la couche HTTP, en particulier le repli sur les certificats macOS."""

import ssl
import unittest
import urllib.error

from playlistordonner import certificats, webclient


class FausseReponse:
    status = 200
    headers = {}

    def read(self):
        return b'{"ok": true}'

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def erreur_de_certificat():
    return urllib.error.URLError(
        ssl.SSLCertVerificationError(1, "certificate verify failed: unable to get local issuer certificate")
    )


class TestRepliCertificats(unittest.TestCase):
    def setUp(self):
        self._urlopen = webclient.urllib.request.urlopen
        self._secours = certificats.activer_secours
        self._contexte = certificats.contexte_ssl
        certificats.contexte_ssl = lambda: None

    def tearDown(self):
        webclient.urllib.request.urlopen = self._urlopen
        certificats.activer_secours = self._secours
        certificats.contexte_ssl = self._contexte

    def test_reessaie_avec_le_trousseau_et_reussit(self):
        appels = []
        certificats.activer_secours = lambda: True

        def urlopen(req, timeout=None, context=None):
            appels.append(1)
            if len(appels) == 1:
                raise erreur_de_certificat()
            return FausseReponse()

        webclient.urllib.request.urlopen = urlopen
        resultat = webclient.request("https://exemple.test/", retries=0)
        self.assertTrue(resultat.ok)
        self.assertEqual(resultat.data, {"ok": True})
        self.assertEqual(len(appels), 2, "le repli doit déclencher un second essai")

    def test_un_seul_repli_puis_message_explicite(self):
        secours = []

        def activer():
            if secours:
                return False
            secours.append(1)
            return True

        certificats.activer_secours = activer

        def urlopen(req, timeout=None, context=None):
            raise erreur_de_certificat()

        webclient.urllib.request.urlopen = urlopen
        with self.assertRaises(webclient.HttpError) as piege:
            webclient.request("https://exemple.test/", retries=0)
        self.assertIn("Install Certificates", str(piege.exception))

    def test_une_panne_reseau_ordinaire_ne_declenche_pas_le_repli(self):
        certificats.activer_secours = lambda: self.fail("repli déclenché à tort")

        def urlopen(req, timeout=None, context=None):
            raise urllib.error.URLError("réseau coupé")

        webclient.urllib.request.urlopen = urlopen
        with self.assertRaises(webclient.HttpError) as piege:
            webclient.request("https://exemple.test/", retries=0)
        self.assertIn("Connexion impossible", str(piege.exception))


class TestDetection(unittest.TestCase):
    def test_reconnait_lerreur_de_certificat(self):
        self.assertTrue(webclient._echec_de_certificat(erreur_de_certificat()))
        self.assertTrue(
            webclient._echec_de_certificat(ssl.SSLCertVerificationError(1, "boum")))

    def test_ignore_les_autres_erreurs(self):
        self.assertFalse(webclient._echec_de_certificat(urllib.error.URLError("timeout")))
        self.assertFalse(webclient._echec_de_certificat(OSError("disque plein")))
        self.assertFalse(webclient._echec_de_certificat(None))


class TestMagasin(unittest.TestCase):
    def test_un_magasin_vide_est_detecte(self):
        class Vide:
            def cert_store_stats(self):
                return {"x509_ca": 0, "x509": 0, "crl": 0}

        class Garni:
            def cert_store_stats(self):
                return {"x509_ca": 150}

        self.assertFalse(certificats._a_des_autorites(Vide()))
        self.assertTrue(certificats._a_des_autorites(Garni()))


if __name__ == "__main__":
    unittest.main()


class TestExplications(unittest.TestCase):
    """Un 403 doit nommer l'appel fautif et sa cause probable."""

    def setUp(self):
        from playlistordonner import spotify

        self.spotify = spotify

    def _message(self, status, path, detail="Forbidden"):
        class Resultat:
            def __init__(self):
                self.status = status
                self.data = {"error": {"message": detail}}

        return self.spotify._message(Resultat(), path)

    def test_le_chemin_apparait_dans_le_message(self):
        self.assertIn("/me/tracks", self._message(403, "/me/tracks"))

    def test_scope_manquant_sur_les_titres_likes(self):
        self.assertIn("user-library-read", self._message(403, "/me/tracks"))

    def test_refus_sur_les_titres_dune_playlist(self):
        """Le message ne doit pas affirmer une cause qu'il ne connaît pas."""
        message = self._message(403, "/playlists/37i9dQ/tracks")
        self.assertIn("tester", message)
        self.assertNotIn("créée par Spotify", message)

    def test_api_audio_fermee(self):
        self.assertIn("novembre 2024", self._message(403, "/audio-features"))

    def test_404_reste_comprehensible(self):
        self.assertIn("introuvable", self._message(404, "/playlists/abc", detail=""))


class TestAutorisations(unittest.TestCase):
    def test_autorisations_manquantes_detectees(self):
        from playlistordonner.auth import SCOPES, Authenticator

        auth = Authenticator.__new__(Authenticator)
        auth._tokens = {"scope": " ".join(SCOPES[:2])}
        self.assertEqual(auth.missing_scopes(), set(SCOPES[2:]))

    def test_aucun_scope_connu_ne_declenche_pas_dalerte(self):
        from playlistordonner.auth import Authenticator

        auth = Authenticator.__new__(Authenticator)
        auth._tokens = {}
        self.assertEqual(auth.missing_scopes(), set())

    def test_toutes_accordees(self):
        from playlistordonner.auth import SCOPES, Authenticator

        auth = Authenticator.__new__(Authenticator)
        auth._tokens = {"scope": " ".join(SCOPES)}
        self.assertEqual(auth.missing_scopes(), set())


class TestRepliParametres(unittest.TestCase):
    """Si Spotify refuse la requête détaillée, on retente en la simplifiant."""

    def _client(self, refuse, statut=403):
        from playlistordonner.spotify import SpotifyClient, SpotifyError

        client = SpotifyClient.__new__(SpotifyClient)
        client._features_blocked = False
        self.appels = []

        def faux_paginate(chemin, params=None, limit_total=None, progress=None):
            params = params or {}
            self.appels.append(params)
            if refuse(params):
                raise SpotifyError("Forbidden", statut, chemin)
            return [{"track": {"id": "t1"}}]

        client._paginate = faux_paginate
        return client

    def test_repli_jusqua_une_requete_acceptee(self):
        client = self._client(lambda p: "fields" in p or "additional_types" in p)
        notes = []
        items = client.playlist_tracks("p1", note=notes.append)
        self.assertEqual(len(items), 1)
        self.assertNotIn("fields", self.appels[-1])
        self.assertNotIn("additional_types", self.appels[-1])
        self.assertTrue(any("acceptée" in note for note in notes))

    def test_la_premiere_requete_reste_la_plus_precise(self):
        client = self._client(lambda p: False)
        client.playlist_tracks("p1")
        self.assertIn("fields", self.appels[0])
        self.assertEqual(len(self.appels), 1, "aucun essai inutile")

    def test_une_erreur_dautorisation_ne_declenche_pas_le_repli(self):
        from playlistordonner.spotify import SpotifyError

        client = self._client(lambda p: True, statut=401)
        with self.assertRaises(SpotifyError):
            client.playlist_tracks("p1")
        self.assertEqual(len(self.appels), 1)

    def test_si_tout_echoue_lerreur_remonte(self):
        from playlistordonner.spotify import SpotifyError

        client = self._client(lambda p: True)
        with self.assertRaises(SpotifyError) as piege:
            client.playlist_tracks("p1")
        self.assertEqual(piege.exception.status, 403)
        self.assertEqual(len(self.appels), len(client.variantes_titres()))
