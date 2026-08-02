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

RAW_META_TTL_SECONDS = SOURCE_CHECK_TTL_SECONDS
RAW_META_MAX_ENTRIES = 512
_raw_meta: dict[str, tuple[float, dict]] = {}
_raw_meta_lock = threading.Lock()


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


def _field_judgment_enabled() -> bool:
    try:
        from . import judge_by_search_fields

        return judge_by_search_fields()
    except Exception:
        return True


def _account_is_vip() -> bool:
    try:
        from . import account_is_vip

        return account_is_vip()
    except Exception:
        return False


def _stash_raw_songs(songs: Any) -> None:
    """Keep the raw search response items so playability fields stay reachable.

    ``fuo_qqmusic`` deserializes search results with marshmallow ``EXCLUDE``,
    which drops ``action``/``pay``/``status`` from the song models. Stashing
    the raw dicts keyed by song id lets the source check read them afterwards.
    """
    if not isinstance(songs, list):
        return
    expires = time.monotonic() + RAW_META_TTL_SECONDS
    with _raw_meta_lock:
        for item in songs:
            if not isinstance(item, dict):
                continue
            identifier = item.get("id")
            if identifier is None:
                continue
            _raw_meta[str(identifier)] = (expires, item)
        if len(_raw_meta) > RAW_META_MAX_ENTRIES:
            now = time.monotonic()
            expired = [k for k, (exp, _) in _raw_meta.items() if exp <= now]
            for expired_key in expired:
                _raw_meta.pop(expired_key, None)


def _raw_meta_for(song: Any) -> dict | None:
    identifier = str(getattr(song, "identifier", "") or "")
    if not identifier:
        return None
    now = time.monotonic()
    with _raw_meta_lock:
        entry = _raw_meta.get(identifier)
        if entry is None:
            return None
        expires, item = entry
        if expires <= now:
            del _raw_meta[identifier]
            return None
        return item


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# Bit layout of ``action.switch`` as decoded by the official QQ Music web
# client: after dropping the lowest bit, the remaining bits map to
# ["play_lq", "play_hq", "play_sq", "down_lq", ..., "try", "give"].
# The web client greys out a song when ``action.play`` is 0, where
# ``action.play = play_lq | play_hq | play_sq`` -> bits 1-3.
PLAY_BITS_MASK = 0b1110
# ``try`` (试听) is bit 14: only a short preview exists for non-VIP accounts.
TRY_BIT_MASK = 1 << 14


def _judge_from_raw(item: dict) -> bool | None:
    """Judge playability from the raw search response fields.

    Returns ``True``/``False`` when the fields give a definitive answer and
    ``None`` when the account-specific URL probe is still needed:

    - ``action.switch`` play bits (1-3) all off and no ``try`` bit ->
      unavailable for every account; this is the same condition the QQ Music
      web client uses to grey out search results.
    - play bits off but ``try`` bit set -> only a preview exists; whether the
      full song plays depends on the account, so probe.
    - ``pay.pay_play == 1`` -> VIP-gated: available directly when the user
      declared a VIP account, otherwise probe.
    - all ``file.size_*`` values zero -> no audio files exist at all.
    """
    action = item.get("action")
    switch = _int_or_none(action.get("switch")) if isinstance(action, dict) else None
    play_bits_off = switch is not None and (switch & PLAY_BITS_MASK) == 0
    if play_bits_off and (switch & TRY_BIT_MASK) == 0:
        return False

    pay = item.get("pay")
    pay_play = _int_or_none(pay.get("pay_play")) if isinstance(pay, dict) else None
    if pay_play == 1:
        return True if _account_is_vip() else None

    if play_bits_off:
        # Only the ``try`` preview bit is set; full playback depends on the
        # account, so let the URL probe decide.
        return None

    if switch is not None:
        return True

    files = item.get("file")
    if isinstance(files, dict) and files:
        sizes = [
            value
            for key, value in files.items()
            if key.startswith("size_")
            and key != "size_try"
            and isinstance(value, (int, float))
        ]
        if sizes and all(value <= 0 for value in sizes):
            return False
    return None


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
    """Check one song, preferring search response fields over a URL probe.

    Judgment order: in-memory result cache -> raw search fields
    (``action.switch``/``pay.pay_play``/``file.size_*``) -> request the lowest
    MP3 quality URL. ``None`` means the answer could not be determined and is
    deliberately treated as unknown rather than as an unavailable song.
    """
    cached = _cached_source(provider, song)
    if cached is not None:
        _set_song_source_state(song, cached)
        return cached

    if _field_judgment_enabled():
        raw = _raw_meta_for(song)
        if raw is not None:
            verdict = _judge_from_raw(raw)
            if verdict is not None:
                logger.debug(
                    "QQ Music source judged from search fields: song=%s available=%s",
                    getattr(song, "identifier", ""),
                    verdict,
                )
                _cache_source(provider, song, verdict)
                _set_song_source_state(song, verdict)
                return verdict

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
    """Probe enough results to keep five playable candidates when hiding."""
    songs = getattr(result, "songs", None)
    if not songs:
        return result

    try:
        from . import search_source_check_enabled

        if not search_source_check_enabled():
            return result
    except Exception:
        pass

    songs = list(songs)
    hide_unavailable = _hide_unavailable_search_results()

    if not hide_unavailable:
        for song in songs[:SEARCH_SOURCE_CHECK_LIMIT]:
            check_song_source(provider, song)
        return result

    visible_songs = []
    playable_count = 0
    for song in songs:
        if playable_count >= SEARCH_SOURCE_CHECK_LIMIT:
            visible_songs.append(song)
            continue

        available = check_song_source(provider, song)
        if available is False and hide_unavailable:
            logger.info(
                "QQ Music search result has no playable source: %s",
                getattr(song, "identifier", ""),
            )
            continue
        playable_count += 1
        visible_songs.append(song)

    try:
        result.songs = visible_songs
    except Exception:
        result.songs[:] = visible_songs
    return result


def _is_song_search(kwargs: dict[str, Any]) -> bool:
    search_type = kwargs.get("type_")
    if search_type is None:
        return True
    value = getattr(search_type, "value", search_type)
    return value in ("song", "so", 0)


def _install_api_meta_capture(provider: Any) -> bool:
    """Wrap ``api.search`` to stash raw song fields before deserialization."""
    api = getattr(provider, "api", None)
    if api is None:
        return False
    if getattr(api, "_qqmusic_refresh_meta_capture", None) is not None:
        return True
    original = getattr(api, "search", None)
    if original is None:
        return False

    @functools.wraps(original)
    def search_with_meta_capture(*args, **kwargs):
        result = original(*args, **kwargs)
        type_ = kwargs.get("type_", args[1] if len(args) > 1 else 0)
        if type_ == 0:
            try:
                _stash_raw_songs(result)
            except Exception:
                logger.debug("Failed to stash QQ Music search metadata", exc_info=True)
        return result

    api.search = search_with_meta_capture
    api._qqmusic_refresh_meta_capture = True
    api._qqmusic_refresh_original_api_search = original
    return True


def _uninstall_api_meta_capture(provider: Any) -> None:
    api = getattr(provider, "api", None)
    if api is None:
        return
    original = getattr(api, "_qqmusic_refresh_original_api_search", None)
    if original is not None:
        api.search = original
    for name in (
        "_qqmusic_refresh_meta_capture",
        "_qqmusic_refresh_original_api_search",
    ):
        if hasattr(api, name):
            delattr(api, name)


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

    _install_api_meta_capture(provider)

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

    _uninstall_api_meta_capture(provider)
    original = getattr(provider, "_qqmusic_refresh_original_search", None)
    if original is not None:
        provider.search = original
    for name in (
        "_qqmusic_refresh_source_check",
        "_qqmusic_refresh_original_search",
    ):
        if hasattr(provider, name):
            delattr(provider, name)
