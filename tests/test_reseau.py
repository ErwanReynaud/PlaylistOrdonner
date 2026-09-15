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
