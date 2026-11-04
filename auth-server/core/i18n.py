"""Localization support for the CSNZ authentication service.

Translations live in ``auth-server/locales/<language>.json`` as flat
``key -> text`` pairs.  English is the default and the fallback language.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller onefile: locales are extracted next to the bundled modules.
    LOCALE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "locales"
else:
    LOCALE_DIR = Path(__file__).resolve().parent.parent / "locales"
DEFAULT_LANGUAGE = "en"

_ALIASES = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "zh-sg": "zh-CN",
    "pt": "pt-BR",
    "pt-br": "pt-BR",
    "en-us": "en",
    "en-gb": "en",
}

_language = DEFAULT_LANGUAGE
_strings: dict[str, str] = {}
_fallback: dict[str, str] = {}


def _read_locale(language: str) -> dict[str, str]:
    path = LOCALE_DIR / f"{language}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


def normalize_language(language: str | None) -> str:
    value = (language or "").strip().replace("_", "-")
    if not value:
        return DEFAULT_LANGUAGE
    if value in _ALIASES:
        return _ALIASES[value]
    lowered = value.lower()
    if lowered in _ALIASES:
        return _ALIASES[lowered]
    for path in LOCALE_DIR.glob("*.json"):
        if path.stem.lower() == lowered:
            return path.stem
    return DEFAULT_LANGUAGE


def available_languages() -> dict[str, str]:
    """Return ``{code: display name}`` with English first."""
    found: dict[str, str] = {}
    if LOCALE_DIR.exists():
        for path in LOCALE_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            found[path.stem] = str(data.get("_name") or path.stem)
    found.setdefault(DEFAULT_LANGUAGE, "English")
    ordered = {DEFAULT_LANGUAGE: found.pop(DEFAULT_LANGUAGE)}
    ordered.update(dict(sorted(found.items(), key=lambda item: item[1].lower())))
    return ordered


def init(language: str | None = None) -> str:
    global _language, _strings, _fallback
    _language = normalize_language(language)
    _fallback = _read_locale(DEFAULT_LANGUAGE)
    _strings = _fallback if _language == DEFAULT_LANGUAGE else _read_locale(_language)
    if not _strings:
        _strings = _fallback
    return _language


def set_language(language: str) -> str:
    return init(language)


def get_language() -> str:
    return _language


def language_name(language: str | None = None) -> str:
    code = normalize_language(language or _language)
    return available_languages().get(code, code)


def has(key: str) -> bool:
    return key in _strings or key in _fallback


def t(key: str, **kwargs) -> str:
    text = _strings.get(key)
    if text is None:
        text = _fallback.get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError, IndexError):
            pass
    return text


__all__ = [
    "LOCALE_DIR", "DEFAULT_LANGUAGE", "init", "set_language", "get_language",
    "language_name", "available_languages", "normalize_language", "has", "t",
]
