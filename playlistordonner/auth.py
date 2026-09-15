"""Authentification Spotify en OAuth 2.0 avec PKCE.

PKCE évite d'avoir à stocker un « client secret » sur la machine : seul
l'identifiant public de l'application Spotify (Client ID) est nécessaire.
"""

import base64
import hashlib
import http.server
import os
import secrets
import socket
import threading
import time
import urllib.parse
import webbrowser

from . import config
from .webclient import encode_form, request

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

REDIRECT_HOST = "127.0.0.1"
REDIRECT_PORT = 8888
REDIRECT_PATH = "/callback"
REDIRECT_URI = "http://%s:%d%s" % (REDIRECT_HOST, REDIRECT_PORT, REDIRECT_PATH)

SCOPES = [
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-library-read",
]

_PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>PlaylistOrdonner</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;
background:#121212;color:#fff;display:flex;align-items:center;
justify-content:center;height:100vh;margin:0}}
.card{{text-align:center;max-width:26rem;padding:2rem}}
h1{{font-size:1.4rem;margin:0 0 .6rem}}p{{color:#b3b3b3;line-height:1.5}}
.dot{{width:3rem;height:3rem;border-radius:50%;background:{color};
margin:0 auto 1.2rem}}</style></head><body><div class="card">
<div class="dot"></div><h1>{title}</h1><p>{message}</p></div></body></html>"""


class AuthError(Exception):
    pass


def _challenge(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _new_verifier():
    return base64.urlsafe_b64encode(os.urandom(64)).decode("ascii").rstrip("=")


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result = None
    expected_state = None

    def do_GET(self):  # noqa: N802 (nom imposé par BaseHTTPRequestHandler)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != REDIRECT_PATH:
            self._reply(404, "Page inconnue", "Cette adresse n'est pas gérée.", "#e22134")
            return
        params = dict(urllib.parse.parse_qsl(parsed.query))
        if params.get("state") != _CallbackHandler.expected_state:
            _CallbackHandler.result = {"error": "state_mismatch"}
            self._reply(
                400,
                "Échec de la connexion",
                "La réponse de Spotify ne correspond pas à la demande.",
                "#e22134",
            )
            return
        _CallbackHandler.result = params
        if "error" in params:
            self._reply(
                400,
                "Autorisation refusée",
                "Spotify a renvoyé : %s" % params["error"],
                "#e22134",
            )
        else:
            self._reply(
                200,
                "C'est bon, chef !",
                "Connexion réussie. Tu peux fermer cet onglet et revenir "
                "dans PlaylistOrdonner.",
                "#1db954",
            )

    def _reply(self, status, title, message, color):
        page = _PAGE.format(title=title, message=message, color=color)
        body = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence le log sur stderr
        pass


class Authenticator:
    """Détient le Client ID, le jeton d'accès et sait le renouveler."""

    def __init__(self, client_id=None):
        settings = config.load_settings()
        self.client_id = (client_id or settings.get("client_id") or "").strip()
        self._tokens = config.load_tokens()

    # -- état ---------------------------------------------------------------
    @property
    def has_client_id(self):
        return bool(self.client_id)

    @property
    def is_logged_in(self):
        return bool(self._tokens.get("refresh_token") or self._tokens.get("access_token"))

    @property
    def granted_scopes(self):
        """Autorisations réellement accordées par Spotify lors de la connexion."""
        return set((self._tokens.get("scope") or "").split())

    def missing_scopes(self):
        """Autorisations demandées mais absentes du jeton.

        Un jeton dépourvu de champ « scope » (cas ancien) ne déclenche aucune
        alerte : on ne peut rien en conclure.
        """
        accordees = self.granted_scopes
        if not accordees:
            return set()
        return set(SCOPES) - accordees

    def set_client_id(self, client_id):
        client_id = (client_id or "").strip()
        if client_id != self.client_id:
            self.logout()
        self.client_id = client_id
        settings = config.load_settings()
        settings["client_id"] = client_id
        config.save_settings(settings)

    def logout(self):
        self._tokens = {}
        config.clear_tokens()

    # -- jetons -------------------------------------------------------------
    def access_token(self):
        if not self.client_id:
            raise AuthError("Aucun identifiant d'application Spotify (Client ID).")
        token = self._tokens.get("access_token")
        expires_at = float(self._tokens.get("expires_at") or 0)
        if token and time.time() < expires_at - 60:
            return token
        if self._tokens.get("refresh_token"):
            return self.refresh()
        raise AuthError("Non connecté à Spotify.")

    def refresh(self):
        refresh_token = self._tokens.get("refresh_token")
        if not refresh_token:
            raise AuthError("Non connecté à Spotify.")
        result = request(
            TOKEN_URL,
            method="POST",
            body=encode_form(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self.client_id,
                }
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if not result.ok:
            self.logout()
            raise AuthError(
                "Session Spotify expirée, il faut se reconnecter (%s)."
                % (result.data.get("error_description") or result.status)
            )
        self._store(result.data, fallback_refresh=refresh_token)
        return self._tokens["access_token"]

    def _store(self, payload, fallback_refresh=None):
        self._tokens = {
            "access_token": payload.get("access_token", ""),
            "refresh_token": payload.get("refresh_token") or fallback_refresh or "",
            "expires_at": time.time() + float(payload.get("expires_in") or 3600),
            "scope": payload.get("scope", ""),
        }
        config.save_tokens(self._tokens)

    # -- connexion ----------------------------------------------------------
    def login(self, on_open_url=None, timeout=300):
        """Ouvre le navigateur, attend le retour de Spotify, stocke le jeton."""
        if not self.client_id:
            raise AuthError("Renseigne d'abord le Client ID de ton application Spotify.")

        verifier = _new_verifier()
        state = secrets.token_urlsafe(24)
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "code_challenge_method": "S256",
            "code_challenge": _challenge(verifier),
            "state": state,
            "scope": " ".join(SCOPES),
        }
        url = AUTH_URL + "?" + urllib.parse.urlencode(params)

        _CallbackHandler.result = None
        _CallbackHandler.expected_state = state
        try:
            server = http.server.HTTPServer((REDIRECT_HOST, REDIRECT_PORT), _CallbackHandler)
        except OSError as exc:
            raise AuthError(
                "Le port %d est déjà utilisé sur ton Mac (%s). Ferme "
                "l'application qui l'occupe puis réessaie." % (REDIRECT_PORT, exc)
            )
        server.timeout = 1
        try:
            thread = threading.Thread(target=self._serve, args=(server, timeout), daemon=True)
            thread.start()
            if on_open_url:
                on_open_url(url)
            webbrowser.open(url)
            thread.join(timeout + 5)
        finally:
            server.server_close()

        params = _CallbackHandler.result
        _CallbackHandler.result = None
        if not params:
            raise AuthError(
                "Pas de réponse de Spotify dans le temps imparti. Réessaie."
            )
        if "error" in params:
            raise AuthError("Spotify a refusé l'autorisation : %s" % params["error"])
        code = params.get("code")
        if not code:
            raise AuthError("Spotify n'a pas renvoyé de code d'autorisation.")

        result = request(
            TOKEN_URL,
            method="POST",
            body=encode_form(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                    "client_id": self.client_id,
                    "code_verifier": verifier,
                }
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if not result.ok:
            detail = result.data.get("error_description") or result.data.get("error")
            raise AuthError(
                "Échec de l'échange du code (%s). Vérifie que l'adresse de "
                "redirection %s est bien enregistrée dans ton application "
                "Spotify." % (detail or result.status, REDIRECT_URI)
            )
        self._store(result.data)
        return self._tokens["access_token"]

    @staticmethod
    def _serve(server, timeout):
        deadline = time.time() + timeout
        while _CallbackHandler.result is None and time.time() < deadline:
            server.handle_request()


def port_is_free(port=REDIRECT_PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((REDIRECT_HOST, port))
            return True
        except OSError:
            return False
