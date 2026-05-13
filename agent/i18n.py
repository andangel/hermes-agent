"""Lightweight internationalization (i18n) for Hermes static user-facing messages.

Scope (thin slice, by design): only the highest-impact static strings shown
to the user by Hermes itself -- approval prompts, a handful of gateway slash
command replies, restart-drain notices.  Agent-generated output, log lines,
error tracebacks, tool outputs, and slash-command descriptions all stay in
English.

Catalog files live under ``locales/<lang>.yaml`` at the repo root.  Each
catalog is a flat dict keyed by dotted paths (e.g. ``approval.choose`` or
``gateway.approval_expired``).  Missing keys fall back to English; if English
is missing too, the key path itself is returned so a broken catalog never
crashes the agent.

Usage::

    from agent.i18n import t
    print(t("approval.choose_long"))                       # current lang
    print(t("gateway.draining", count=3))                  # {count} formatted
    print(t("approval.choose_long", lang="zh"))            # explicit override

Language resolution order:
    1. Explicit ``lang=`` argument passed to :func:`t`
    2. ``HERMES_LANGUAGE`` environment variable (for tests / quick override)
    3. System locale (LANG, LC_ALL, LANGUAGE) - auto-detect from OS
    4. ``display.language`` from config.yaml
    5. ``"en"`` (baseline)

Supported languages: en, zh.  Unknown values fall back to en.
"""

from __future__ import annotations

import logging
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "zh")
DEFAULT_LANGUAGE = "en"

# Accept a few natural aliases so users who type "chinese" / "zh-CN" / "jp"
# get the right catalog instead of silently falling back to English.
_LANGUAGE_ALIASES: dict[str, str] = {
    "english": "en", "en-us": "en", "en-gb": "en",
    # Simplified Chinese — explicit codes route here; bare "chinese" / "mandarin"
    # also default to Simplified since that's the larger user base.
    "chinese": "zh", "mandarin": "zh", "zh-cn": "zh", "zh-hans": "zh", "zh-sg": "zh",
}

_catalog_cache: dict[str, dict[str, str]] = {}
_catalog_lock = threading.Lock()


def _locales_dir() -> Path:
    """Return the directory containing locale YAML files.

    Lives next to the repo root so both the bundled install and editable
    checkouts find it without PYTHONPATH gymnastics.
    """
    # agent/i18n.py -> agent/ -> repo root
    return Path(__file__).resolve().parent.parent / "locales"


def _normalize_lang(value: Any) -> str:
    """Normalize a user-supplied language value to a supported code.

    Accepts supported codes directly, common aliases (``chinese`` -> ``zh``),
    and case-insensitive regional tags (``zh-CN`` -> ``zh``).  Returns the
    default language for unknown values.
    """
    if not isinstance(value, str):
        return DEFAULT_LANGUAGE
    key = value.strip().lower()
    if not key:
        return DEFAULT_LANGUAGE
    if key in SUPPORTED_LANGUAGES:
        return key
    if key in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[key]
    # Try stripping a region suffix (e.g. "pt-br" -> "pt" won't be supported,
    # but "zh-CN" -> "zh" will).
    base = key.split("-", 1)[0]
    if base in SUPPORTED_LANGUAGES:
        return base
    return DEFAULT_LANGUAGE


def _load_catalog(lang: str) -> dict[str, str]:
    """Load and flatten one locale YAML file into a dotted-key dict.

    YAML files can be nested for human readability; this produces the flat
    key space :func:`t` expects.  Cached per-language for the process.
    """
    with _catalog_lock:
        cached = _catalog_cache.get(lang)
        if cached is not None:
            return cached

    path = _locales_dir() / f"{lang}.yaml"
    if not path.is_file():
        logger.debug("i18n catalog missing for %s at %s", lang, path)
        with _catalog_lock:
            _catalog_cache[lang] = {}
        return {}

    try:
        import yaml  # PyYAML is already a hermes dependency
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("Failed to load i18n catalog %s: %s", path, exc)
        with _catalog_lock:
            _catalog_cache[lang] = {}
        return {}

    flat: dict[str, str] = {}
    _flatten_into(raw, "", flat)
    with _catalog_lock:
        _catalog_cache[lang] = flat
    return flat


def _flatten_into(node: Any, prefix: str, out: dict[str, str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child_key = f"{prefix}.{key}" if prefix else str(key)
            _flatten_into(value, child_key, out)
    elif isinstance(node, str):
        out[prefix] = node
    # Non-string, non-dict leaves are ignored -- catalogs are text-only.


@lru_cache(maxsize=1)
def _config_language_cached() -> str | None:
    """Read ``display.language`` from config.yaml once per process.

    Cached because ``t()`` is called in hot paths (every approval prompt,
    every gateway reply) and re-reading YAML each call would be wasteful.
    ``reset_language_cache()`` clears this when config changes at runtime
    (e.g. after the setup wizard).
    """
    try:
        from hermes_cli.config import load_config
        cfg = load_config()
        lang = (cfg.get("display") or {}).get("language")
        if lang:
            return _normalize_lang(lang)
    except Exception as exc:
        logger.debug("Could not read display.language from config: %s", exc)
    return None


def _detect_system_locale() -> str | None:
    """Auto-detect language from system locale.
    
    Cross-platform detection:
      - Unix/Linux/macOS: LANG, LC_ALL, LANGUAGE environment variables
      - Windows: ctypes call to GetLocaleInfo API or USER_LANGUAGE env var
    
    Converts common locale codes to supported Hermes languages:
      - zh_CN.UTF-8, zh_CN, zh -> zh (Simplified Chinese)
      - zh_TW.UTF-8, zh_TW -> zh-hant (Traditional Chinese)
      - ja_JP.UTF-8, ja_JP, ja -> ja (Japanese)
      - de_DE.UTF-8, de_DE, de -> de (German)
      - etc.
    
    Returns normalized language code or None if not detectable.
    """
    import platform
    
    # Platform-specific detection
    if platform.system() == "Windows":
        return _detect_windows_locale()
    else:
        # Unix/Linux/macOS: use standard locale env vars
        return _detect_unix_locale()


def _detect_unix_locale() -> str | None:
    """Detect locale on Unix/Linux/macOS systems."""
    # Check standard locale env vars in priority order
    for env_var in ["LC_ALL", "LANG", "LANGUAGE"]:
        locale_str = os.environ.get(env_var)
        if not locale_str:
            continue
        
        # Extract base language code from locale string
        # Examples: "zh_CN.UTF-8" -> "zh", "en_US.UTF-8" -> "en"
        locale_str = locale_str.strip()
        if not locale_str or locale_str == "C" or locale_str == "POSIX":
            continue
        
        # Remove encoding suffix (e.g., .UTF-8)
        base_locale = locale_str.split(".")[0]
        
        # Try exact match first (e.g., "zh_CN" -> check if supported)
        normalized = _normalize_lang(base_locale)
        if normalized != DEFAULT_LANGUAGE:
            logger.debug("Detected system locale: %s -> %s", env_var, normalized)
            return normalized
        
        # Try just the language part (e.g., "zh_CN" -> "zh")
        lang_only = base_locale.split("_")[0]
        normalized = _normalize_lang(lang_only)
        if normalized != DEFAULT_LANGUAGE:
            logger.debug("Detected system locale: %s (%s) -> %s", env_var, base_locale, normalized)
            return normalized
    
    return None


def _detect_windows_locale() -> str | None:
    """Detect locale on Windows systems.
    
    Tries multiple methods:
    1. USER_LANGUAGE or LANG environment variable (if set by user/WSL)
    2. ctypes call to Windows GetLocaleInfo API
    3. locale.getdefaultlocale() as fallback
    """
    # Method 1: Check if user manually set LANG/USER_LANGUAGE (common in WSL/Git Bash)
    for env_var in ["USER_LANGUAGE", "LANG", "LC_ALL"]:
        locale_str = os.environ.get(env_var)
        if locale_str:
            normalized = _normalize_lang(locale_str)
            if normalized != DEFAULT_LANGUAGE:
                logger.debug("Detected Windows locale from %s: %s", env_var, normalized)
                return normalized
    
    # Method 2: Use ctypes to call Windows API
    try:
        import ctypes
        import ctypes.wintypes
        
        # Get user default locale name (e.g., "en-US", "zh-CN")
        LOCALE_NAME_USER_DEFAULT = None  # NULL means current user default
        locale_name_buffer = ctypes.create_unicode_buffer(85)  # LOCALE_NAME_MAX_LENGTH
        
        kernel32 = ctypes.windll.kernel32
        result = kernel32.GetUserDefaultLocaleName(
            locale_name_buffer,
            ctypes.sizeof(locale_name_buffer)
        )
        
        if result > 0:
            locale_name = locale_name_buffer.value  # e.g., "zh-CN", "en-US"
            # Convert Windows format to our format
            # "zh-CN" -> "zh", "en-US" -> "en"
            normalized = _normalize_lang(locale_name)
            if normalized != DEFAULT_LANGUAGE:
                logger.debug("Detected Windows locale via API: %s -> %s", locale_name, normalized)
                return normalized
    except Exception as exc:
        logger.debug("Windows locale API detection failed: %s", exc)
    
    # Method 3: Fallback to locale module
    try:
        import locale
        default_locale = locale.getdefaultlocale()[0]  # e.g., "zh_CN", "en_US"
        if default_locale:
            normalized = _normalize_lang(default_locale)
            if normalized != DEFAULT_LANGUAGE:
                logger.debug("Detected Windows locale via locale module: %s -> %s", default_locale, normalized)
                return normalized
    except Exception as exc:
        logger.debug("locale.getdefaultlocale() failed: %s", exc)
    
    return None


def reset_language_cache() -> None:
    """Invalidate cached language resolution and catalogs.

    Call after :func:`hermes_cli.config.save_config` if a running process
    needs to pick up a changed ``display.language`` without restart.
    """
    _config_language_cached.cache_clear()
    with _catalog_lock:
        _catalog_cache.clear()


def get_language() -> str:
    """Resolve the active language using env > system locale > config > default order.
    
    Language resolution priority:
        1. HERMES_LANGUAGE environment variable (explicit override)
        2. System locale (LANG, LC_ALL, LANGUAGE) - auto-detect from OS
        3. display.language from config.yaml
        4. "en" (baseline default)
    """
    # Priority 1: Explicit HERMES_LANGUAGE env var
    env_lang = os.environ.get("HERMES_LANGUAGE")
    if env_lang:
        return _normalize_lang(env_lang)
    
    # Priority 2: Auto-detect from system locale
    sys_lang = _detect_system_locale()
    if sys_lang:
        return sys_lang
    
    # Priority 3: Config file setting
    cfg_lang = _config_language_cached()
    if cfg_lang:
        return cfg_lang
    
    # Priority 4: Default to English
    return DEFAULT_LANGUAGE


def t(key: str, lang: str | None = None, **format_kwargs: Any) -> str:
    """Translate a dotted key to the active language.

    Parameters
    ----------
    key
        Dotted path into the catalog, e.g. ``"approval.choose_long"``.
    lang
        Explicit language override.  Takes precedence over env + config.
    **format_kwargs
        ``str.format`` substitution arguments (``t("gateway.drain", count=3)``
        expects a catalog entry with a ``{count}`` placeholder).

    Returns
    -------
    The translated string, or the English fallback if the key is missing in
    the target language, or the bare key if English is also missing.
    """
    target = _normalize_lang(lang) if lang else get_language()
    catalog = _load_catalog(target)
    value = catalog.get(key)

    if value is None and target != DEFAULT_LANGUAGE:
        # Fall through to English rather than showing a key path to the user.
        value = _load_catalog(DEFAULT_LANGUAGE).get(key)

    if value is None:
        # Last-ditch: return the key itself.  A broken catalog should not
        # crash anything; it just looks ugly until someone fixes it.
        logger.debug("i18n miss: key=%r lang=%r", key, target)
        value = key

    if format_kwargs:
        try:
            return value.format(**format_kwargs)
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning(
                "i18n format failed for key=%r lang=%r kwargs=%r: %s",
                key, target, format_kwargs, exc,
            )
            return value
    return value


__all__ = [
    "SUPPORTED_LANGUAGES",
    "DEFAULT_LANGUAGE",
    "t",
    "get_language",
    "reset_language_cache",
]
