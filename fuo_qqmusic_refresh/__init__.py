"""FeelUOwn companion plugin for refreshing QQ Music login cookies."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .credentials import CredentialError, credentials_from_sources
from .protocol import refresh_login
from .storage import (
    default_cookie_file,
    default_device_file,
    default_state_file,
    load_json,
    save_json,
    update_cookie_document,
)

__alias__ = "QQ 音乐 Cookie 自动续期"
__feeluown_version__ = "1.1.0"
__version__ = "0.1.0"
__desc__ = "使用 QQ 音乐移动端登录接口自动续期现有 QQ 音乐登录态"
__author__ = "Codex"

logger = logging.getLogger(__name__)

_config = None
_runner = None


def init_config(config):
    """Declare plugin configuration in FeelUOwn's .fuorc namespace."""
    global _config
    _config = config
    config.deffield("Enabled", bool, True, "Enable automatic refresh")
    config.deffield("IntervalHours", int, 24, "Refresh interval")
    config.deffield("CookieFile", str, "", "Override QQ Music cookie file")
    config.deffield("StateFile", str, "", "Refresh state sidecar file")
    config.deffield("DeviceFile", str, "", "Cached Android device file")
    config.deffield("TimeoutSeconds", int, 20, "HTTP timeout")
    config.deffield("RefreshKey", str, "", "Optional refresh_key override")
    config.deffield("OpenID", str, "", "Optional openid override")
    config.deffield("AccessToken", str, "", "Optional access_token override")
    config.deffield("RefreshToken", str, "", "Optional refresh_token override")


def _get_config_value(name: str, default: Any) -> Any:
    if _config is None:
        return default
    return getattr(_config, name, default)


def _path_value(name: str, default: Path) -> Path:
    configured = str(_get_config_value(name, "") or "").strip()
    return Path(configured).expanduser() if configured else default


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_run_at() -> str:
    interval = max(1, int(_get_config_value("IntervalHours", 24)))
    return (datetime.now(timezone.utc) + timedelta(hours=interval)).isoformat()


def _write_status(state_file: Path, state: dict[str, Any], **updates) -> dict[str, Any]:
    result = dict(state)
    current = result.get("status")
    status = dict(current) if isinstance(current, dict) else {}
    status.update(updates)
    result["status"] = status
    try:
        save_json(state_file, result)
    except Exception:
        logger.warning("Failed to persist QQ Music refresh status", exc_info=True)
    return result


def _error_text(exc: Exception) -> str:
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def _refresh_once() -> bool:
    cookie_file = _path_value("CookieFile", default_cookie_file())
    state_file = _path_value("StateFile", default_state_file())
    device_file = _path_value("DeviceFile", default_device_file())

    state = load_json(state_file, default={})
    if not isinstance(state, dict):
        state = {}
    started_at = _timestamp()
    state = _write_status(
        state_file,
        state,
        last_result="running",
        last_attempt_at=started_at,
        last_error="",
    )

    try:
        document = load_json(cookie_file, default={"cookies": {}})
        if not isinstance(document, dict):
            raise CredentialError(f"cookie file is not a JSON object: {cookie_file}")

        cookies = document.get("cookies", document)
        if not isinstance(cookies, dict):
            raise CredentialError(f"cookie field is not an object: {cookie_file}")

        overrides = {
            "open_id": _get_config_value("OpenID", ""),
            "access_token": _get_config_value("AccessToken", ""),
            "refresh_token": _get_config_value("RefreshToken", ""),
            "refresh_key": _get_config_value("RefreshKey", ""),
        }
        credentials = credentials_from_sources(cookies, state, overrides)
        logger.info("Refreshing QQ Music login for uin=%s", credentials.uin)

        data = refresh_login(
            credentials,
            device_file=device_file,
            timeout=int(_get_config_value("TimeoutSeconds", 20)),
        )
        updated_document = update_cookie_document(document, data)
        save_json(cookie_file, updated_document)
        state = dict(state)
        state.update(credentials.updated_state(data))
        state = _write_status(
            state_file,
            state,
            last_result="success",
            last_finished_at=_timestamp(),
            last_success_at=_timestamp(),
            last_error="",
            next_run_at=_next_run_at(),
        )

        _update_live_provider(updated_document.get("cookies", updated_document))
        logger.info("QQ Music login refreshed for uin=%s", credentials.uin)
        return True
    except Exception as exc:
        _write_status(
            state_file,
            state,
            last_result="failed",
            last_finished_at=_timestamp(),
            last_error=_error_text(exc),
            next_run_at=_next_run_at(),
        )
        raise


def _update_live_provider(cookies: dict) -> None:
    """Update the already-loaded fuo-qqmusic API without forcing a relogin."""
    try:
        from fuo_qqmusic.provider import provider
    except Exception:  # the companion can be installed before fuo-qqmusic
        logger.debug("fuo-qqmusic provider is not available", exc_info=True)
        return
    try:
        provider.api.set_cookies(cookies)
    except Exception:
        logger.warning("Failed to update the live QQ Music provider", exc_info=True)


def refresh_now() -> bool:
    """Refresh once; useful from ``fuo exec`` or a small diagnostic script."""
    return _refresh_once()


def status() -> dict[str, Any]:
    """Return non-secret refresh health information for diagnostics."""
    cookie_file = _path_value("CookieFile", default_cookie_file())
    state_file = _path_value("StateFile", default_state_file())
    document = load_json(cookie_file, default={"cookies": {}})
    state = load_json(state_file, default={})
    if not isinstance(document, dict):
        document = {}
    if not isinstance(state, dict):
        state = {}
    cookies = document.get("cookies", document)
    if not isinstance(cookies, dict):
        cookies = {}
    refresh_status = state.get("status")
    if not isinstance(refresh_status, dict):
        refresh_status = {}
    uin = str(cookies.get("uin") or cookies.get("wxuin") or state.get("uin") or "")
    if uin.startswith("o"):
        uin = uin[1:]
    last_result = refresh_status.get("last_result", "never")
    return {
        "enabled": bool(_get_config_value("Enabled", True)),
        "monitoring": _runner is not None and not _runner.stop_event.is_set(),
        "uin": uin,
        "cookie_file": str(cookie_file),
        "state_file": str(state_file),
        "cookie_file_exists": cookie_file.exists(),
        "has_music_key": bool(cookies.get("qqmusic_key") or cookies.get("qm_keyst")),
        "last_result": last_result,
        "last_attempt_at": refresh_status.get("last_attempt_at"),
        "last_finished_at": refresh_status.get("last_finished_at"),
        "last_success_at": refresh_status.get("last_success_at"),
        "last_error": refresh_status.get("last_error", ""),
        "next_run_at": refresh_status.get("next_run_at"),
        "healthy": last_result == "success",
    }


class _RefreshRunner:
    def __init__(self, app):
        self.app = app
        self.stop_event = threading.Event()
        self.task = None

    def start(self) -> None:
        task_spec = self.app.task_mgr.get_or_create("qqmusic-cookie-refresh")
        self.task = task_spec.bind_coro(self._run())

    def stop(self) -> None:
        self.stop_event.set()
        if self.task is not None and hasattr(self.task, "cancel"):
            self.task.cancel()

    async def _run(self) -> None:
        interval = max(1, int(_get_config_value("IntervalHours", 24))) * 3600
        while not self.stop_event.is_set():
            try:
                await asyncio.to_thread(_refresh_once)
            except CredentialError as exc:
                logger.warning("QQ Music refresh skipped: %s", exc)
            except Exception:
                logger.exception("QQ Music refresh failed")

            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self.stop_event.wait), timeout=interval
                )
            except asyncio.TimeoutError:
                continue


def enable(app):
    global _runner
    if not bool(_get_config_value("Enabled", True)):
        logger.info("QQ Music cookie refresh is disabled")
        return
    _runner = _RefreshRunner(app)
    _runner.start()
    if app.mode & app.GuiMode:
        from .ui import install_qqmusic_ui

        install_qqmusic_ui(app)


def disable(app):
    global _runner
    if _runner is not None:
        _runner.stop()
        _runner = None
    if app.mode & app.GuiMode:
        from .ui import uninstall_qqmusic_ui

        uninstall_qqmusic_ui(app)
