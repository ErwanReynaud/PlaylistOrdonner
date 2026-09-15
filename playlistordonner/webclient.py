"""Petit client HTTP JSON basé uniquement sur urllib."""

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from . import APP_NAME, __version__
from . import certificats

USER_AGENT = "%s/%s (+https://github.com/ErwanReynaud/PlaylistOrdonner)" % (
    APP_NAME,
    __version__,
)


class HttpResult:
    __slots__ = ("status", "data", "raw", "headers")

    def __init__(self, status, data, raw, headers):
        self.status = status
        self.data = data
        self.raw = raw
        self.headers = headers

    @property
    def ok(self):
        return 200 <= self.status < 300


class HttpError(Exception):
    def __init__(self, message, status=0, data=None):
        super().__init__(message)
        self.status = status
        self.data = data or {}


def encode_form(params):
    return urllib.parse.urlencode(params).encode("utf-8")


def request(
    url,
    method="GET",
    headers=None,
    body=None,
    json_body=None,
    timeout=30,
    retries=3,
):
    """Effectue une requête et décode le JSON de la réponse.

    Les erreurs HTTP ne lèvent pas d'exception : elles sont renvoyées dans le
    résultat, car l'appelant a souvent besoin du code (401 -> rafraîchir le
    jeton, 429 -> attendre, 403 -> API indisponible).
    """
    all_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        all_headers.update(headers)

    payload = body
    if json_body is not None:
        payload = json.dumps(json_body).encode("utf-8")
        all_headers.setdefault("Content-Type", "application/json")

    last_error = None
    attempt = 0
    while attempt <= retries:
        req = urllib.request.Request(
            url, data=payload, headers=all_headers, method=method
        )
        try:
            with urllib.request.urlopen(
                req, timeout=timeout, context=certificats.contexte_ssl()
            ) as resp:
                raw = resp.read()
                return HttpResult(
                    resp.status, _decode(raw), raw, dict(resp.headers.items())
                )
        except urllib.error.HTTPError as exc:  # réponse reçue, mais code >= 400
            raw = exc.read()
            result = HttpResult(
                exc.code, _decode(raw), raw, dict(exc.headers.items() if exc.headers else [])
            )
            if exc.code == 429 and attempt < retries:
                time.sleep(_retry_after(result.headers))
                attempt += 1
                continue
            if exc.code >= 500 and attempt < retries:
                time.sleep(2 ** attempt)
                attempt += 1
                continue
            return result
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            # Python installé depuis python.org sans « Install Certificates » :
            # on refait l'essai avec les certificats du trousseau macOS.
            if _echec_de_certificat(exc) and certificats.activer_secours():
                continue
            if attempt < retries:
                time.sleep(2 ** attempt)
                attempt += 1
                continue
            attempt += 1
    if _echec_de_certificat(last_error):
        raise HttpError(
            "Connexion sécurisée impossible vers %s : ce Python n'a pas de "
            "certificats racine utilisables et le trousseau de macOS n'a rien "
            "donné. Ouvre le dossier Applications, puis « Python 3.x », et "
            "double-clique sur « Install Certificates.command »." % url
        )
    raise HttpError("Connexion impossible (%s) : %s" % (url, last_error))


def _echec_de_certificat(exc):
    raison = getattr(exc, "reason", exc)
    return isinstance(raison, ssl.SSLCertVerificationError) or isinstance(
        exc, ssl.SSLCertVerificationError
    )


def _decode(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _retry_after(headers):
    for key, value in (headers or {}).items():
        if key.lower() == "retry-after":
            try:
                return min(60.0, max(1.0, float(value) + 0.5))
            except (TypeError, ValueError):
                break
    return 2.0
