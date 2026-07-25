"""Capture complete QQ Music credentials during a fresh web login."""

from __future__ import annotations

import json
import importlib
import logging
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

LOGIN_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
CAPTURE_GRACE_SECONDS = 2.5
CAPTURE_TIMEOUT_SECONDS = 15.0


def _qt_class(module_suffix: str, class_name: str):
    errors = []
    for binding in ("PyQt5", "PyQt6", "PySide6", "PySide2"):
        try:
            module = importlib.import_module(f"{binding}.{module_suffix}")
        except ImportError as exc:
            errors.append(exc)
            continue
        return getattr(module, class_name)
    raise ImportError("No supported Qt binding is installed") from errors[-1]


def login_exchange_payload(login_type: str, code: str) -> dict[str, Any]:
    """Build the public QQ Music web-login code exchange request."""
    if login_type == "1":
        return {
            "comm": {"g_tk": 5381, "platform": "yqq", "ct": 24, "cv": 0},
            "req": {
                "module": "QQConnectLogin.LoginServer",
                "method": "QQLogin",
                "param": {"code": code},
            },
        }
    if login_type == "2":
        return {
            "comm": {
                "tmeAppID": "qqmusic",
                "tmeLoginType": "1",
                "g_tk": 5381,
                "platform": "yqq",
                "ct": 24,
                "cv": 0,
            },
            "req": {
                "module": "music.login.LoginServer",
                "method": "Login",
                "param": {"strAppid": "wx48db31d50e334801", "code": code},
            },
        }
    raise ValueError(f"unsupported QQ Music login type: {login_type}")


def _response_data(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    for key in ("req", "req_0", "req_1", "req1"):
        value = body.get(key)
        if isinstance(value, dict) and isinstance(value.get("data"), dict):
            return value["data"]
    return {}


def _response_code(body: Any) -> Any:
    if not isinstance(body, dict):
        return None
    for key in ("req", "req_0", "req_1", "req1"):
        value = body.get(key)
        if isinstance(value, dict) and "code" in value:
            return value["code"]
    return body.get("code")


def _non_empty_cookie_values(response) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in response.cookies.get_dict().items()
        if str(value)
    }


def _merge_response_fields(cookies: dict[str, str], data: dict[str, Any]) -> dict[str, str]:
    merged = dict(cookies)
    field_map = {
        "openid": "psrf_qqopenid",
        "access_token": "psrf_qqaccess_token",
        "refresh_token": "psrf_qqrefresh_token",
        "refresh_key": "psrf_qqrefresh_key",
        "musickey": "qqmusic_key",
        "musicid": "uin",
    }
    for source, target in field_map.items():
        value = str(data.get(source) or "")
        if value:
            merged[target] = value
    return merged


def exchange_login_code(
    login_type: str,
    code: str,
    cookies: dict[str, str],
    timeout: int = 15,
) -> dict[str, str]:
    """Exchange a web-login callback code and return only merged cookie fields."""
    import requests

    response = requests.post(
        LOGIN_URL,
        json=login_exchange_payload(login_type, code),
        cookies=cookies,
        headers={"Content-Type": "application/json", "User-Agent": "QQMusic"},
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    code_value = _response_code(body)
    if code_value not in (None, 0, "0"):
        raise RuntimeError(f"QQ Music web login returned code {code_value}")
    return _merge_response_fields(_non_empty_cookie_values(response), _response_data(body))


def build_capturing_login_dialog(base_class):
    """Create a CookiesLoginDialog subclass without importing a Qt binding early."""

    class CapturingLoginDialog(base_class):
        def __init__(self, *args, **kwargs):
            self._capture_started_at = 0.0
            self._capture_timer = None
            self._capture_finished = False
            self._exchange_task = None
            self._exchange_cookies: dict[str, str] = {}
            self._login_code_key = None
            super().__init__(*args, **kwargs)

        def _start_web_login(self):
            from feeluown.gui.widgets.weblogin import WebLoginView

            self._web_login = WebLoginView(self._uri, self._required_cookies_fields)
            self._web_login.succeed.connect(self._on_web_login_succeed)
            self._web_login.urlChanged.connect(self._on_login_url_changed)
            self._web_login.show()

        def _on_login_url_changed(self, url):
            raw_url = url.toString()
            query = parse_qs(urlparse(raw_url).query)
            code = query.get("code", [""])[0]
            login_type = query.get("login_type", [""])[0]
            if not code or not login_type:
                return
            code_key = (login_type, code)
            if code_key == self._login_code_key:
                return
            self._login_code_key = code_key
            from feeluown.utils import aio

            self._exchange_task = aio.create_task(
                self._exchange_login_code(login_type, code)
            )

        async def _exchange_login_code(self, login_type: str, code: str):
            from feeluown.utils.aio import run_fn

            try:
                cookies = dict(getattr(self._web_login, "saved_cookies", {}))
                merged = await run_fn(exchange_login_code, login_type, code, cookies)
            except Exception:
                logger.warning("QQ Music web login code exchange failed", exc_info=True)
            else:
                self._exchange_cookies.update(merged)

        def _on_web_login_succeed(self, cookies):
            if self._capture_finished or not hasattr(self, "_web_login"):
                return
            if self._capture_started_at == 0.0:
                self._capture_started_at = time.monotonic()
            self._schedule_capture_finish()

        def _schedule_capture_finish(self):
            if self._capture_finished or not hasattr(self, "_web_login"):
                return
            QTimer = _qt_class("QtCore", "QTimer")
            elapsed = time.monotonic() - self._capture_started_at
            task_pending = (
                self._exchange_task is not None and not self._exchange_task.done()
            )
            if elapsed < CAPTURE_GRACE_SECONDS or (
                task_pending and elapsed < CAPTURE_TIMEOUT_SECONDS
            ):
                self._capture_timer = QTimer.singleShot(100, self._schedule_capture_finish)
                return
            self._finish_web_login()

        def _finish_web_login(self):
            if self._capture_finished or not hasattr(self, "_web_login"):
                return
            self._capture_finished = True
            cookies = dict(getattr(self._web_login, "saved_cookies", {}))
            cookies.update(self._exchange_cookies)
            self.cookies_text_edit.setText(json.dumps(cookies, indent=2))
            self._web_login.close()
            del self._web_login
            from feeluown.utils import aio

            aio.create_task(self.login())

    return CapturingLoginDialog


def install_login_capture(provider_ui) -> bool:
    """Patch the official QQ Music UI to retain complete web-login cookies."""
    if getattr(provider_ui, "_qqmusic_refresh_login_capture", None) is not None:
        return True
    try:
        from fuo_qqmusic import provider_ui as qqmusic_ui
    except ImportError:
        logger.warning("fuo-qqmusic is not available; login capture is disabled")
        return False

    original_login_dialog = qqmusic_ui.LoginDialog
    captured_login_dialog = build_capturing_login_dialog(original_login_dialog)
    original_login = provider_ui.login_or_go_home

    def login_or_go_home(*args, **kwargs):
        current_login_dialog = qqmusic_ui.LoginDialog
        qqmusic_ui.LoginDialog = captured_login_dialog
        try:
            return original_login(*args, **kwargs)
        finally:
            qqmusic_ui.LoginDialog = current_login_dialog

    provider_ui.login_or_go_home = login_or_go_home
    provider_ui._qqmusic_refresh_login_capture = True
    provider_ui._qqmusic_refresh_original_login_or_go_home = original_login
    return True


def uninstall_login_capture(provider_ui) -> None:
    original = getattr(
        provider_ui, "_qqmusic_refresh_original_login_or_go_home", None
    )
    if original is not None:
        provider_ui.login_or_go_home = original
    for name in (
        "_qqmusic_refresh_login_capture",
        "_qqmusic_refresh_original_login_or_go_home",
    ):
        if hasattr(provider_ui, name):
            delattr(provider_ui, name)
