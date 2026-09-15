"""Classement des genres musicaux par niveau d'énergie.

Spotify expose des genres très granulaires ("french indie pop", "melodic
death metal", ...). Ce module fait deux choses :

1. il rattache un genre brut à une *famille* lisible (Pop, Métal, Techno...) ;
2. il lui attribue un *score d'énergie* de 0 (le plus calme) à 100 (le plus
   énergique), qui sert à ordonner les groupes de titres.

La règle de correspondance est simple et prévisible : on cherche le mot-clé
le plus long contenu dans le nom du genre. Ainsi "melodic death metal" tombe
sur "death metal" (11 caractères) plutôt que sur "metal" (5).
"""

import re
import unicodedata

UNKNOWN_FAMILY = "Genre inconnu"
UNKNOWN_ENERGY = 101.0  # toujours rejeté en fin de classement
DEFAULT_ENERGY = 50.0
DEFAULT_FAMILY = "Autres"

# (mot-clé, famille, énergie 0-100)
GENRE_RULES = [
    # --- Ambient / drone -------------------------------------------------
    ("ambient", "Ambient / Drone", 6),
    ("dark ambient", "Ambient / Drone", 14),
    ("drone", "Ambient / Drone", 7),
    ("new age", "Ambient / Drone", 8),
    ("meditation", "Ambient / Drone", 4),
    ("sleep", "Ambient / Drone", 3),
    ("field recording", "Ambient / Drone", 3),
    ("nature sounds", "Ambient / Drone", 2),
    ("binaural", "Ambient / Drone", 3),
    ("space music", "Ambient / Drone", 10),
    ("drift", "Ambient / Drone", 9),
    # --- Classique -------------------------------------------------------
    ("classical", "Classique", 20),
    ("neoclassical", "Classique", 16),
    ("neo-classical", "Classique", 16),
    ("baroque", "Classique", 26),
    ("opera", "Classique", 30),
    ("chamber", "Classique", 20),
    ("orchestra", "Classique", 30),
    ("orchestral", "Classique", 30),
    ("symphony", "Classique", 30),
    ("choral", "Classique", 18),
    ("early music", "Classique", 18),
    ("romanticism", "Classique", 24),
    ("minimalism", "Classique", 14),
    ("solo piano", "Classique", 12),
    ("piano", "Classique", 16),
    ("violin", "Classique", 20),
    ("cello", "Classique", 18),
    ("harp", "Classique", 12),
    ("compositional", "Classique", 20),
    # --- Bandes originales ----------------------------------------------
    ("soundtrack", "Bandes originales", 32),
    ("score", "Bandes originales", 28),
    ("video game music", "Bandes originales", 40),
    ("anime", "Bandes originales", 55),
    ("show tunes", "Bandes originales", 45),
    ("hollywood", "Bandes originales", 30),
    ("epicore", "Bandes originales", 60),
    # --- Chill / downtempo ----------------------------------------------
    ("chillout", "Chill / Downtempo", 24),
    ("chill", "Chill / Downtempo", 26),
    ("downtempo", "Chill / Downtempo", 26),
    ("trip hop", "Chill / Downtempo", 30),
    ("lo-fi", "Chill / Downtempo", 22),
    ("lofi", "Chill / Downtempo", 22),
    ("chillhop", "Chill / Downtempo", 24),
    ("lounge", "Chill / Downtempo", 24),
    ("easy listening", "Chill / Downtempo", 22),
    ("bossa nova", "Chill / Downtempo", 28),
    ("smooth jazz", "Chill / Downtempo", 26),
    ("study", "Chill / Downtempo", 18),
    ("spa", "Chill / Downtempo", 8),
    # --- Acoustique / folk ------------------------------------------------
    ("folk", "Acoustique / Folk", 30),
    ("indie folk", "Acoustique / Folk", 32),
    ("freak folk", "Acoustique / Folk", 34),
    ("folk rock", "Rock", 52),
    ("singer-songwriter", "Acoustique / Folk", 30),
    ("songwriter", "Acoustique / Folk", 30),
    ("acoustic", "Acoustique / Folk", 26),
    ("americana", "Acoustique / Folk", 38),
    ("bluegrass", "Acoustique / Folk", 48),
    ("slowcore", "Acoustique / Folk", 18),
    ("sadcore", "Acoustique / Folk", 18),
    ("ballad", "Acoustique / Folk", 24),
    ("ukulele", "Acoustique / Folk", 32),
    # --- Jazz / blues ------------------------------------------------------
    ("jazz", "Jazz / Blues", 36),
    ("bebop", "Jazz / Blues", 52),
    ("swing", "Jazz / Blues", 50),
    ("big band", "Jazz / Blues", 52),
    ("free jazz", "Jazz / Blues", 55),
    ("jazz fusion", "Jazz / Blues", 50),
    ("nu jazz", "Jazz / Blues", 42),
    ("blues", "Jazz / Blues", 40),
    ("delta blues", "Jazz / Blues", 34),
    ("blues rock", "Rock", 62),
    ("ragtime", "Jazz / Blues", 44),
    ("dixieland", "Jazz / Blues", 48),
    # --- Soul / R&B --------------------------------------------------------
    ("soul", "Soul / R&B", 42),
    ("neo soul", "Soul / R&B", 38),
    ("motown", "Soul / R&B", 48),
    ("r&b", "Soul / R&B", 44),
    ("rnb", "Soul / R&B", 44),
    ("contemporary r&b", "Soul / R&B", 46),
    ("gospel", "Soul / R&B", 44),
    ("doo-wop", "Soul / R&B", 40),
    ("quiet storm", "Soul / R&B", 30),
    ("alternative r&b", "Soul / R&B", 40),
    # --- Reggae / dub ------------------------------------------------------
    ("reggae", "Reggae / Dub", 45),
    ("roots reggae", "Reggae / Dub", 42),
    ("dub", "Reggae / Dub", 40),
    ("ska", "Reggae / Dub", 70),
    ("rocksteady", "Reggae / Dub", 42),
    ("dancehall", "Reggae / Dub", 62),
    ("ragga", "Reggae / Dub", 62),
    # --- Country -----------------------------------------------------------
    ("country", "Country", 46),
    ("outlaw country", "Country", 48),
    ("country rock", "Rock", 60),
    ("honky tonk", "Country", 50),
    # --- Variété / chanson --------------------------------------------------
    ("chanson", "Variété / Chanson", 36),
    ("variete francaise", "Variété / Chanson", 42),
    ("nouvelle chanson", "Variété / Chanson", 38),
    ("french pop", "Variété / Chanson", 48),
    ("schlager", "Variété / Chanson", 46),
    ("canzone", "Variété / Chanson", 40),
    ("fado", "Variété / Chanson", 28),
    ("musette", "Variété / Chanson", 44),
    # --- Pop ----------------------------------------------------------------
    ("pop", "Pop", 55),
    ("art pop", "Pop", 48),
    ("dream pop", "Indie / Alternatif", 40),
    ("synthpop", "Pop", 58),
    ("synth-pop", "Pop", 58),
    ("electropop", "Pop", 62),
    ("indie pop", "Indie / Alternatif", 54),
    ("bedroom pop", "Indie / Alternatif", 40),
    ("k-pop", "Pop", 68),
    ("j-pop", "Pop", 64),
    ("city pop", "Pop", 50),
    ("dance pop", "Pop", 68),
    ("teen pop", "Pop", 62),
    ("power pop", "Rock", 68),
    ("pop rock", "Rock", 64),
    ("baroque pop", "Pop", 46),
    ("sophisti-pop", "Pop", 46),
    ("europop", "Pop", 64),
    ("hyperpop", "Électro / Dance", 82),
    ("pop punk", "Punk", 82),
    ("boy band", "Pop", 58),
    ("girl group", "Pop", 58),
    # --- Latino / monde ------------------------------------------------------
    ("latin", "Latino", 60),
    ("latin pop", "Latino", 58),
    ("reggaeton", "Latino", 64),
    ("salsa", "Latino", 66),
    ("bachata", "Latino", 52),
    ("cumbia", "Latino", 58),
    ("samba", "Latino", 62),
    ("mpb", "Latino", 40),
    ("tango", "Latino", 46),
    ("flamenco", "Latino", 52),
    ("merengue", "Latino", 68),
    ("mariachi", "Latino", 52),
    ("bolero", "Latino", 34),
    ("afrobeat", "Musiques du monde", 58),
    ("afrobeats", "Musiques du monde", 60),
    ("amapiano", "Musiques du monde", 56),
    ("highlife", "Musiques du monde", 56),
    ("world", "Musiques du monde", 48),
    ("celtic", "Musiques du monde", 46),
    ("klezmer", "Musiques du monde", 54),
    ("balkan", "Musiques du monde", 62),
    ("bhangra", "Musiques du monde", 66),
    ("bollywood", "Musiques du monde", 58),
    ("rai", "Musiques du monde", 54),
    ("zouk", "Musiques du monde", 52),
    ("kizomba", "Musiques du monde", 48),
    ("coupe-decale", "Musiques du monde", 64),
    ("sertanejo", "Musiques du monde", 54),
    ("gnawa", "Musiques du monde", 50),
    # --- Disco / funk ---------------------------------------------------------
    ("disco", "Disco / Funk", 64),
    ("nu-disco", "Disco / Funk", 64),
    ("funk", "Disco / Funk", 62),
    ("p funk", "Disco / Funk", 62),
    ("boogie", "Disco / Funk", 62),
    ("groove", "Disco / Funk", 58),
    # --- Hip-hop / rap ---------------------------------------------------------
    ("hip hop", "Hip-Hop / Rap", 58),
    ("hip-hop", "Hip-Hop / Rap", 58),
    ("rap", "Hip-Hop / Rap", 60),
    ("trap", "Hip-Hop / Rap", 64),
    ("drill", "Hip-Hop / Rap", 66),
    ("boom bap", "Hip-Hop / Rap", 52),
    ("cloud rap", "Hip-Hop / Rap", 48),
    ("conscious hip hop", "Hip-Hop / Rap", 52),
    ("gangster rap", "Hip-Hop / Rap", 62),
    ("grime", "Hip-Hop / Rap", 72),
    ("phonk", "Hip-Hop / Rap", 74),
    ("pop urbaine", "Hip-Hop / Rap", 58),
    ("turntablism", "Hip-Hop / Rap", 60),
    ("crunk", "Hip-Hop / Rap", 70),
    # --- Indie / alternatif ------------------------------------------------------
    ("indie", "Indie / Alternatif", 54),
    ("indietronica", "Indie / Alternatif", 56),
    ("shoegaze", "Indie / Alternatif", 50),
    ("post-punk", "Indie / Alternatif", 66),
    ("new wave", "Indie / Alternatif", 62),
    ("coldwave", "Indie / Alternatif", 52),
    ("darkwave", "Indie / Alternatif", 52),
    ("goth", "Indie / Alternatif", 58),
    ("math rock", "Indie / Alternatif", 68),
    ("post-rock", "Indie / Alternatif", 48),
    ("art rock", "Indie / Alternatif", 56),
    ("psychedelic", "Indie / Alternatif", 52),
    ("experimental", "Indie / Alternatif", 48),
    ("avant-garde", "Indie / Alternatif", 46),
    ("emo", "Indie / Alternatif", 70),
    ("grunge", "Rock", 76),
    # --- Rock ---------------------------------------------------------------------
    ("rock", "Rock", 66),
    ("classic rock", "Rock", 64),
    ("soft rock", "Rock", 44),
    ("alternative rock", "Rock", 66),
    ("garage rock", "Rock", 72),
    ("hard rock", "Rock", 78),
    ("glam rock", "Rock", 72),
    ("progressive rock", "Rock", 58),
    ("stoner rock", "Rock", 70),
    ("surf rock", "Rock", 64),
    ("rockabilly", "Rock", 70),
    ("rock and roll", "Rock", 70),
    ("rock'n'roll", "Rock", 70),
    ("southern rock", "Rock", 66),
    ("noise rock", "Rock", 76),
    # --- House ----------------------------------------------------------------------
    ("house", "House / Deep", 66),
    ("deep house", "House / Deep", 58),
    ("tech house", "House / Deep", 72),
    ("progressive house", "House / Deep", 70),
    ("tropical house", "House / Deep", 56),
    ("future house", "House / Deep", 74),
    ("bass house", "House / Deep", 80),
    ("acid house", "House / Deep", 74),
    ("garage", "House / Deep", 68),
    ("uk garage", "House / Deep", 70),
    ("afro house", "House / Deep", 66),
    ("disco house", "House / Deep", 68),
    ("french house", "House / Deep", 68),
    ("melodic house", "House / Deep", 64),
    ("organic house", "House / Deep", 52),
    ("2-step", "House / Deep", 68),
    # --- Électro / dance ---------------------------------------------------------------
    ("electro", "Électro / Dance", 72),
    ("electronica", "Électro / Dance", 56),
    ("edm", "Électro / Dance", 78),
    ("dance", "Électro / Dance", 70),
    ("eurodance", "Électro / Dance", 78),
    ("big room", "Électro / Dance", 82),
    ("future bass", "Électro / Dance", 74),
    ("synthwave", "Électro / Dance", 60),
    ("vaporwave", "Chill / Downtempo", 26),
    ("idm", "Électro / Dance", 56),
    ("glitch", "Électro / Dance", 62),
    ("breakbeat", "Électro / Dance", 76),
    ("nu rave", "Électro / Dance", 80),
    ("moombahton", "Électro / Dance", 74),
    ("tropical", "Électro / Dance", 58),
    ("club", "Électro / Dance", 74),
    ("jersey club", "Électro / Dance", 78),
    ("baile funk", "Électro / Dance", 76),
    # --- Techno / trance ------------------------------------------------------------------
    ("techno", "Techno / Trance", 80),
    ("minimal techno", "Techno / Trance", 70),
    ("detroit techno", "Techno / Trance", 76),
    ("acid techno", "Techno / Trance", 84),
    ("industrial techno", "Techno / Trance", 88),
    ("hard techno", "Techno / Trance", 90),
    ("trance", "Techno / Trance", 80),
    ("psytrance", "Techno / Trance", 86),
    ("goa trance", "Techno / Trance", 84),
    ("uplifting trance", "Techno / Trance", 82),
    ("hard trance", "Techno / Trance", 88),
    ("industrial", "Techno / Trance", 82),
    ("ebm", "Techno / Trance", 78),
    # --- Bass / dubstep / drum'n'bass ------------------------------------------------------
    ("dubstep", "Bass / Dubstep / DnB", 84),
    ("brostep", "Bass / Dubstep / DnB", 88),
    ("riddim", "Bass / Dubstep / DnB", 86),
    ("drum and bass", "Bass / Dubstep / DnB", 88),
    ("drum'n'bass", "Bass / Dubstep / DnB", 88),
    ("dnb", "Bass / Dubstep / DnB", 88),
    ("jungle", "Bass / Dubstep / DnB", 86),
    ("liquid funk", "Bass / Dubstep / DnB", 80),
    ("neurofunk", "Bass / Dubstep / DnB", 92),
    ("bass music", "Bass / Dubstep / DnB", 80),
    ("trapstep", "Bass / Dubstep / DnB", 82),
    # --- Punk ----------------------------------------------------------------------------
    ("punk", "Punk", 84),
    ("hardcore punk", "Punk", 92),
    ("skate punk", "Punk", 86),
    ("ska punk", "Punk", 84),
    ("oi", "Punk", 84),
    ("garage punk", "Punk", 84),
    ("screamo", "Punk", 90),
    ("post-hardcore", "Punk", 86),
    # --- Métal ------------------------------------------------------------------------------
    ("metal", "Métal", 88),
    ("heavy metal", "Métal", 86),
    ("thrash metal", "Métal", 92),
    ("death metal", "Métal", 94),
    ("black metal", "Métal", 93),
    ("doom metal", "Métal", 74),
    ("sludge", "Métal", 76),
    ("nu metal", "Métal", 84),
    ("metalcore", "Métal", 92),
    ("deathcore", "Métal", 95),
    ("djent", "Métal", 88),
    ("power metal", "Métal", 88),
    ("symphonic metal", "Métal", 84),
    ("folk metal", "Métal", 86),
    ("grindcore", "Métal", 97),
    ("groove metal", "Métal", 88),
    ("progressive metal", "Métal", 84),
    # --- Hardcore / hardstyle ------------------------------------------------------------------
    ("hardcore", "Hardcore / Hardstyle", 94),
    ("hardstyle", "Hardcore / Hardstyle", 93),
    ("hard dance", "Hardcore / Hardstyle", 90),
    ("gabber", "Hardcore / Hardstyle", 97),
    ("frenchcore", "Hardcore / Hardstyle", 96),
    ("uptempo", "Hardcore / Hardstyle", 98),
    ("speedcore", "Hardcore / Hardstyle", 99),
    ("terrorcore", "Hardcore / Hardstyle", 99),
    ("breakcore", "Hardcore / Hardstyle", 95),
    ("rawstyle", "Hardcore / Hardstyle", 95),
    ("jumpstyle", "Hardcore / Hardstyle", 88),
    ("happy hardcore", "Hardcore / Hardstyle", 90),
    ("nightcore", "Hardcore / Hardstyle", 86),
    ("hardcore techno", "Hardcore / Hardstyle", 94),
    ("hardcore hip hop", "Hip-Hop / Rap", 70),
    # --- Composés qui échapperaient à la règle du mot-clé le plus à droite ---
    ("punk rock", "Punk", 86),
    ("rap rock", "Rock", 76),
    ("rap metal", "Métal", 86),
    ("funk rock", "Rock", 70),
    ("indie rock", "Indie / Alternatif", 62),
    ("dance rock", "Rock", 72),
    ("gothic rock", "Rock", 64),
    ("industrial rock", "Rock", 80),
    ("industrial metal", "Métal", 88),
    ("psychedelic rock", "Rock", 62),
    ("electro swing", "Électro / Dance", 72),
    ("jazz rap", "Hip-Hop / Rap", 50),
    ("mellow gold", "Rock", 42),
    ("permanent wave", "Rock", 64),
    ("adult standards", "Variété / Chanson", 34),
    ("worship", "Soul / R&B", 40),
    ("britpop", "Rock", 62),
]

# Nuances appliquées après coup (uniquement si le mot ne fait pas déjà partie
# du mot-clé reconnu), pour départager "chill house" et "hard house".
MODIFIERS = [
    ("sleep", -25),
    ("meditation", -22),
    ("slowed", -20),
    ("ambient", -18),
    ("chill", -15),
    ("acoustic", -14),
    ("mellow", -14),
    ("lo-fi", -12),
    ("lofi", -12),
    ("soft", -12),
    ("quiet", -12),
    ("ballad", -12),
    ("smooth", -10),
    ("romantic", -8),
    ("dream", -8),
    ("melodic", -5),
    ("instrumental", -4),
    ("melancholy", -10),
    ("deep", -6),
    ("minimal", -8),
    ("brutal", 15),
    ("extreme", 12),
    ("speed", 12),
    ("uptempo", 12),
    ("hard", 10),
    ("thrash", 10),
    ("death", 10),
    ("aggressive", 10),
    ("rave", 8),
    ("power", 6),
    ("black", 6),
    ("core", 5),
    ("dark", 4),
]

_WORD_RE = re.compile(r"[^a-z0-9&'+ -]+")


def normalize(name):
    """Minuscules, sans accents, espaces compactés."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("_", " ").replace("/", " ")
    text = _WORD_RE.sub(" ", text)
    return " ".join(text.split())


def _find(haystack, needle):
    """Position de fin du mot-clé dans la chaîne, ou -1.

    La comparaison est alignée sur des frontières de mots pour que "rap" ne
    matche pas "trapped", et on retient l'occurrence la plus à droite.
    """
    best = -1
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            return best
        end = idx + len(needle)
        before_ok = idx == 0 or not haystack[idx - 1].isalnum()
        after_ok = end == len(haystack) or not haystack[end].isalnum()
        if before_ok and after_ok:
            best = end
        start = idx + 1


def _contains(haystack, needle):
    return _find(haystack, needle) >= 0


def classify(genre, overrides=None):
    """Renvoie (famille, énergie, reconnu) pour un genre brut Spotify."""
    text = normalize(genre)
    if not text:
        return UNKNOWN_FAMILY, UNKNOWN_ENERGY, False

    overrides = overrides or {}
    if text in overrides:
        family, energy, _ = _match(text)
        return family, overrides[text], True

    family, energy, matched = _match(text)
    if matched is None:
        return DEFAULT_FAMILY, DEFAULT_ENERGY, False

    for word, delta in MODIFIERS:
        if word in matched:
            continue
        if _contains(text, word):
            energy += delta
    return family, max(0.0, min(100.0, float(energy))), True


def _match(text):
    """Meilleure règle pour ce genre.

    En anglais le mot qui porte le sens est en fin de nom ("chill house" est
    de la house, "pop punk" du punk) : on retient donc le mot-clé qui se
    termine le plus à droite, et à égalité le plus long ("melodic death
    metal" -> "death metal" plutôt que "metal").
    """
    best = None
    best_key = (-1, -1)
    for keyword, family, energy in GENRE_RULES:
        end = _find(text, keyword)
        if end < 0:
            continue
        rank = (end, len(keyword))
        if rank > best_key:
            best_key = rank
            best = (family, float(energy), keyword)
    if best is None:
        return DEFAULT_FAMILY, DEFAULT_ENERGY, None
    return best


def pick_genre(genres, overrides=None):
    """Choisit le genre le plus représentatif d'une liste de genres Spotify.

    On privilégie le premier genre que l'on sait classer ; Spotify renvoie les
    genres par ordre de pertinence décroissante.
    """
    for genre in genres or []:
        _, _, known = classify(genre, overrides)
        if known:
            return genre
    for genre in genres or []:
        if normalize(genre):
            return genre
    return None
