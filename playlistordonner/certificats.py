"""Choix du magasin de certificats pour les connexions HTTPS.

Les Python installés depuis python.org arrivent **sans certificats racine** :
il faut normalement lancer « Install Certificates.command » à la main, sans
quoi toute connexion HTTPS échoue sur

    CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate

Plutôt que d'imposer cette manipulation, on détecte le magasin vide et on
reconstruit un contexte à partir des certificats du trousseau de macOS, lus
avec l'outil système `security`. Aucune dépendance, et la vérification des
certificats reste active — elle n'est jamais désactivée.
"""

import ssl
import subprocess
import sys

TROUSSEAUX = (
    "/System/Library/Keychains/SystemRootCertificates.keychain",
    "/Library/Keychains/System.keychain",
)

_contexte = []       # contexte retenu (cache)
_secours_actif = []  # marque qu'on est déjà passé au magasin système


def _certifi():
    """Magasin fourni par certifi, si le paquet est installé."""
    try:
        import certifi
    except ImportError:
        return None
    try:
        contexte = ssl.create_default_context(cafile=certifi.where())
    except (OSError, ssl.SSLError):
        return None
    return contexte if _a_des_autorites(contexte) else None


def _pem_du_trousseau():
    if sys.platform != "darwin":
        return []
    blocs = []
    for trousseau in TROUSSEAUX:
        try:
            resultat = subprocess.run(
                ["/usr/bin/security", "find-certificate", "-a", "-p", trousseau],
                capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if resultat.returncode == 0 and resultat.stdout:
            blocs.append(resultat.stdout)
    return blocs


def _trousseau_macos():
    """Contexte bâti sur les autorités de certification du trousseau macOS."""
    blocs = _pem_du_trousseau()
    if not blocs:
        return None
    contexte = ssl.create_default_context()
    donnees = "\n".join(blocs)
    try:
        contexte.load_verify_locations(cadata=donnees)
    except (ssl.SSLError, ValueError):
        # Un certificat illisible suffit à faire échouer le lot : on charge
        # alors les certificats un par un, en ignorant les fautifs.
        contexte = ssl.create_default_context()
        charges = 0
        for morceau in donnees.split("-----END CERTIFICATE-----"):
            pem = morceau.strip()
            if not pem:
                continue
            pem += "\n-----END CERTIFICATE-----\n"
            try:
                contexte.load_verify_locations(cadata=pem)
                charges += 1
            except (ssl.SSLError, ValueError):
                continue
        if not charges:
            return None
    return contexte if _a_des_autorites(contexte) else None


def _a_des_autorites(contexte):
    try:
        return bool(contexte.cert_store_stats().get("x509_ca"))
    except (AttributeError, ValueError):
        return True  # dans le doute, on fait confiance au contexte


def contexte_ssl():
    """Contexte HTTPS à utiliser, construit une seule fois."""
    if _contexte:
        return _contexte[0]
    choisi = ssl.create_default_context()
    if not _a_des_autorites(choisi):
        choisi = _certifi() or _trousseau_macos() or choisi
        if _a_des_autorites(choisi):
            _secours_actif.append(True)
    _contexte.append(choisi)
    return choisi


def activer_secours():
    """Bascule sur le trousseau macOS après un échec de vérification.

    Renvoie True si un nouveau magasin a pu être chargé, donc s'il vaut la
    peine de refaire la requête.
    """
    if _secours_actif:
        return False
    remplacant = _certifi() or _trousseau_macos()
    if remplacant is None:
        _secours_actif.append(True)  # inutile de réessayer indéfiniment
        return False
    _secours_actif.append(True)
    del _contexte[:]
    _contexte.append(remplacant)
    return True


def description():
    """Résumé lisible du magasin utilisé, pour le diagnostic."""
    contexte = contexte_ssl()
    try:
        nombre = contexte.cert_store_stats().get("x509_ca", 0)
    except (AttributeError, ValueError):
        nombre = -1
    origine = "trousseau macOS (secours)" if _secours_actif else "magasin par défaut de Python"
    return "%s — %s autorité(s) de certification" % (origine, nombre)
