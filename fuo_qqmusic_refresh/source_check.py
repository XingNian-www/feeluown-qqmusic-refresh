"""Preflight QQ Music search results for a playable low-quality source."""

from __future__ import annotations

import functools
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

SEARCH_SOURCE_CHECK_LIMIT = 5
LOWEST_AUDIO_QUALITY = "M500"
SOURCE_CHECK_TTL_SECONDS = 15 * 60
_CACHE_KEY = "qqmusic_source_available"
_cache: dict[tuple[str, str, str], tuple[float, bool]] = {}
_cache_lock = threading.Lock()


def _api_cache_identity(provider: Any) -> tuple[str, str]:
    api = getattr(provider, "api", None)
    uin = str(getattr(api, "_uin", "0") or "0")
    try:
        token = str(api.get_token_from_cookies())
    except Exception:
        token = ""
    return uin, token


def _song_cache_value(song: Any, key: str):
    try:
        value, exists = song.cache_get(key)
    except Exception:
        return None
    return value if exists else None


def _song_identifiers(song: Any) -> tuple[str, str]:
    mid = _song_cache_value(song, "mid")
    media_id = _song_cache_value(song, "media_id")
    return str(mid or ""), str(media_id or "")


def _set_song_source_state(song: Any, available: bool) -> None:
    try:
        song.cache_set(_CACHE_KEY, available, ttl=SOURCE_CHECK_TTL_SECONDS)
    except Exception:
        logger.debug("QQ Music song cache does not support source state", exc_info=True)

    try:
        from feeluown.library import MediaFlags

        song.media_flags = (
            MediaFlags.not_sure if available else MediaFlags.not_exists
        )
    except Exception:
        # Older FeelUOwn versions may not expose MediaFlags on the model.
        logger.debug("Unable to update QQ Music song media flags", exc_info=True)


def _hide_unavailable_search_results() -> bool:
    try:
        from . import hide_unavailable_search_results

        return hide_unavailable_search_results()
    except Exception:
        return True


def _cached_source(provider: Any, song: Any) -> bool | None:
    uin, token = _api_cache_identity(provider)
    identifier = str(getattr(song, "identifier", "") or "")
    key = (uin, token, identifier)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            expires_at, available = cached
            if expires_at > now:
                return available
            del _cache[key]
    return None


def _cache_source(provider: Any, song: Any, available: bool) -> None:
    uin, token = _api_cache_identity(provider)
    identifier = str(getattr(song, "identifier", "") or "")
    key = (uin, token, identifier)
    with _cache_lock:
        _cache[key] = (time.monotonic() + SOURCE_CHECK_TTL_SECONDS, available)
        if len(_cache) > 256:
            expired = [k for k, (expires_at, _) in _cache.items() if expires_at <= time.monotonic()]
            for expired_key in expired:
                _cache.pop(expired_key, None)


def check_song_source(provider: Any, song: Any) -> bool | None:
    """Check one song with QQ Music's lowest MP3 quality.

    ``None`` means the request could not be completed and is deliberately
    treated as unknown rather than as an unavailable song.
    """
    cached = _cached_source(provider, song)
    if cached is not None:
        _set_song_source_state(song, cached)
        return cached

    mid, media_id = _song_identifiers(song)
    api = getattr(provider, "api", None)
    if not mid or not media_id or api is None:
        logger.debug("QQ Music source check skipped: missing song identifiers")
        return None

    try:
        url = api.get_song_url_v2(mid, media_id, LOWEST_AUDIO_QUALITY)
    except Exception:
        logger.warning(
            "QQ Music source check failed for song=%s",
            getattr(song, "identifier", ""),
            exc_info=True,
        )
        return None

    available = bool(url)
    _cache_source(provider, song, available)
    _set_song_source_state(song, available)
    return available


def precheck_search_result(result: Any, provider: Any) -> Any:
    """Probe the first five results and optionally hide unavailable songs."""
    songs = getattr(result, "songs", None)
    if not songs:
        return result

    hide_unavailable = _hide_unavailable_search_results()
    visible_songs = []
    for index, song in enumerate(list(songs)):
        available = True
        if index < SEARCH_SOURCE_CHECK_LIMIT:
            available = check_song_source(provider, song)
        if available is False and hide_unavailable:
            logger.info(
                "QQ Music search result has no playable source: %s",
                getattr(song, "identifier", ""),
            )
            continue
        visible_songs.append(song)

    try:
        result.songs = visible_songs
    except Exception:
        songs[:] = visible_songs
    return result


def _is_song_search(kwargs: dict[str, Any]) -> bool:
    search_type = kwargs.get("type_")
    if search_type is None:
        return True
    value = getattr(search_type, "value", search_type)
    return value in ("song", "so", 0)


def install_source_check() -> bool:
    """Wrap the official provider search without modifying its source package."""
    try:
        from fuo_qqmusic.provider import provider
    except Exception:
        logger.warning("fuo-qqmusic is not available; source check is disabled")
        return False

    if getattr(provider, "_qqmusic_refresh_source_check", None) is not None:
        return True

    original = getattr(provider, "search", None)
    if original is None:
        return False

    @functools.wraps(original)
    def search_with_source_check(*args, **kwargs):
        result = original(*args, **kwargs)
        if _is_song_search(kwargs):
            return precheck_search_result(result, provider)
        return result

    provider.search = search_with_source_check
    provider._qqmusic_refresh_source_check = True
    provider._qqmusic_refresh_original_search = original
    return True


def uninstall_source_check() -> None:
    try:
        from fuo_qqmusic.provider import provider
    except Exception:
        return

    original = getattr(provider, "_qqmusic_refresh_original_search", None)
    if original is not None:
        provider.search = original
    for name in (
        "_qqmusic_refresh_source_check",
        "_qqmusic_refresh_original_search",
    ):
        if hasattr(provider, name):
            delattr(provider, name)
