"""Stockage des réglages et du cache de jetons dans le dossier utilisateur."""

import json
import os
import stat
import sys

from . import APP_NAME


def config_dir() -> str:
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def _path(name: str) -> str:
    return os.path.join(config_dir(), name)


SETTINGS_FILE = "reglages.json"
TOKENS_FILE = "jetons.json"
GENRES_FILE = "genres_perso.json"


def _read(name: str) -> dict:
    try:
        with open(_path(name), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(name: str, data: dict) -> None:
    target = _path(name)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, target)
    try:
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def load_settings() -> dict:
    return _read(SETTINGS_FILE)


def save_settings(data: dict) -> None:
    _write(SETTINGS_FILE, data)


def load_tokens() -> dict:
    return _read(TOKENS_FILE)


def save_tokens(data: dict) -> None:
    _write(TOKENS_FILE, data)


def clear_tokens() -> None:
    try:
        os.remove(_path(TOKENS_FILE))
    except OSError:
        pass


def load_genre_overrides() -> dict:
    """Table perso genre -> score d'énergie (0-100), éditable à la main."""
    data = _read(GENRES_FILE)
    out = {}
    for key, value in data.items():
        try:
            out[str(key).strip().lower()] = max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            continue
    return out


def genre_overrides_path() -> str:
    return _path(GENRES_FILE)
