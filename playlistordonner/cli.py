"""Interface en ligne de commande (utile sans interface graphique)."""

import argparse
import sys

from . import APP_NAME, __version__, config, sorter
from .auth import REDIRECT_URI, AuthError, Authenticator
from .engine import DEST_IN_PLACE, DEST_NEW, LIKED, Cancelled, Engine
from .spotify import SpotifyError


def _log(message):
    print(message, flush=True)


def _progress(done, total, label=""):
    if not label or not total:
        return
    sys.stdout.write("\r  %s : %d/%d   " % (label, done, total))
    if done >= total:
        sys.stdout.write("\n")
    sys.stdout.flush()


def _auth(args):
    auth = Authenticator()
    if getattr(args, "client_id", None):
        auth.set_client_id(args.client_id)
    if not auth.has_client_id:
        raise AuthError(
            "Aucun Client ID enregistré. Crée une application sur "
            "https://developer.spotify.com/dashboard avec l'adresse de "
            "redirection %s, puis lance :\n"
            "  playlistordonner config --client-id TON_CLIENT_ID" % REDIRECT_URI
        )
    if not auth.is_logged_in:
        _log("Ouverture du navigateur pour autoriser l'accès à Spotify…")
        auth.login(on_open_url=lambda url: _log("Adresse : " + url))
    return auth


def cmd_config(args):
    auth = Authenticator()
    if args.client_id:
        auth.set_client_id(args.client_id)
        _log("Client ID enregistré.")
    _log("Dossier de configuration : %s" % config.config_dir())
    _log("Table de genres personnalisable : %s" % config.genre_overrides_path())
    _log("Adresse de redirection à déclarer : %s" % REDIRECT_URI)
    _log("Client ID : %s" % (auth.client_id or "(aucun)"))
    _log("Connecté : %s" % ("oui" if auth.is_logged_in else "non"))
    return 0


def cmd_login(args):
    auth = Authenticator()
    if args.client_id:
        auth.set_client_id(args.client_id)
    auth.logout()
    _auth(args)
    _log("Connexion réussie.")
    return 0


def cmd_playlists(args):
    engine = Engine(_auth(args), log=_log, progress=_progress)
    for playlist in engine.list_playlists():
        total = "" if playlist["total"] is None else "%4d titres" % playlist["total"]
        _log("%-24s %-12s %s" % (playlist["id"], total, playlist["name"]))
    return 0


def cmd_trier(args):
    engine = Engine(_auth(args), log=_log, progress=_progress)
    playlist_id = args.playlist
    if playlist_id.lower() in ("likes", "likés", "liked", "aimés"):
        playlist_id = LIKED
    playlist_id = _strip_uri(playlist_id)

    report = engine.analyse(
        playlist_id,
        group_mode=sorter.GROUP_BY_GENRE if args.genres_precis else sorter.GROUP_BY_FAMILY,
        use_deezer=not args.sans_deezer,
        refine_with_audio=not args.sans_affinage,
    )
    _log("")
    _log(report.text())
    _log("")
    _log(report.tracklist())

    if args.apercu:
        _log("\nAperçu seulement : rien n'a été modifié sur Spotify.")
        return 0

    engine.write(
        report,
        playlist_id,
        destination=DEST_IN_PLACE if args.en_place else DEST_NEW,
        new_name=args.nom,
        public=args.publique,
    )
    _log("\nTerminé : %s" % (report.target_url or report.target_name))
    return 0


def _strip_uri(value):
    value = value.strip()
    if value.startswith("spotify:playlist:"):
        return value.split(":")[-1]
    if "open.spotify.com/playlist/" in value:
        return value.split("/playlist/")[-1].split("?")[0]
    return value


def build_parser():
    parser = argparse.ArgumentParser(
        prog="playlistordonner",
        description="Trie une playlist Spotify par genre (du plus calme au plus "
                    "énergique) puis par BPM croissant.",
    )
    parser.add_argument("--version", action="version", version="%s %s" % (APP_NAME, __version__))
    sub = parser.add_subparsers(dest="commande")

    conf = sub.add_parser("config", help="affiche ou change la configuration")
    conf.add_argument("--client-id", help="Client ID de ton application Spotify")
    conf.set_defaults(func=cmd_config)

    login = sub.add_parser("login", help="(re)connexion à Spotify")
    login.add_argument("--client-id")
    login.set_defaults(func=cmd_login)

    listing = sub.add_parser("playlists", help="liste tes playlists et leurs identifiants")
    listing.add_argument("--client-id")
    listing.set_defaults(func=cmd_playlists)

    trier = sub.add_parser("trier", help="trie une playlist")
    trier.add_argument("playlist", help="identifiant, URL, ou « likes » pour les titres likés")
    trier.add_argument("--client-id")
    trier.add_argument("--apercu", action="store_true", help="n'écrit rien sur Spotify")
    trier.add_argument("--en-place", action="store_true",
                       help="réordonne la playlist d'origine au lieu d'en créer une")
    trier.add_argument("--nom", help="nom de la nouvelle playlist")
    trier.add_argument("--publique", action="store_true")
    trier.add_argument("--genres-precis", action="store_true",
                       help="regroupe par genre Spotify exact plutôt que par famille")
    trier.add_argument("--sans-deezer", action="store_true",
                       help="n'interroge pas Deezer pour compléter les BPM")
    trier.add_argument("--sans-affinage", action="store_true",
                       help="garde le score d'énergie théorique de chaque genre")
    trier.set_defaults(func=cmd_trier)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except Cancelled:
        _log("Annulé.")
        return 130
    except (AuthError, SpotifyError) as exc:
        _log("Erreur : %s" % exc)
        return 1
    except KeyboardInterrupt:
        _log("\nInterrompu.")
        return 130
