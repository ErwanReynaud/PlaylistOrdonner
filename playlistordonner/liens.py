"""Extraction d'identifiants de titres Spotify depuis du texte collé.

Dans l'application Spotify, sélectionner des titres puis « Copier le lien »
met dans le presse-papiers une liste d'adresses. Ce module en tire les
identifiants, quel que soit le format rencontré :

    https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp?si=abc
    https://open.spotify.com/intl-fr/track/3n3Ppam7vgaVa1iaRUc9Lp
    spotify:track:3n3Ppam7vgaVa1iaRUc9Lp
    3n3Ppam7vgaVa1iaRUc9Lp
"""

import re

# Un identifiant Spotify est une suite de 22 caractères alphanumériques.
MOTIFS = (
    re.compile(r"spotify:track:([A-Za-z0-9]{22})"),
    re.compile(r"open\.spotify\.com/(?:intl-[a-z]{2}/)?track/([A-Za-z0-9]{22})"),
)
SEUL = re.compile(r"^([A-Za-z0-9]{22})$")


def identifiants_de_titres(texte):
    """Identifiants trouvés dans le texte, sans doublon et dans l'ordre."""
    trouves = []
    vus = set()

    def ajouter(identifiant):
        if identifiant not in vus:
            vus.add(identifiant)
            trouves.append(identifiant)

    for ligne in str(texte or "").splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        reconnu = False
        for motif in MOTIFS:
            for identifiant in motif.findall(ligne):
                ajouter(identifiant)
                reconnu = True
        if not reconnu:
            seul = SEUL.match(ligne)
            if seul:
                ajouter(seul.group(1))
    return trouves


def lire_fichier(chemin):
    with open(chemin, "r", encoding="utf-8", errors="replace") as fh:
        return identifiants_de_titres(fh.read())
