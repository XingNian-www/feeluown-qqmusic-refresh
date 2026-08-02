"""GUI integration for the QQ Music cookie refresh companion plugin."""

from __future__ import annotations

import importlib
import logging

from .credentials import CredentialError
from .storage import default_cookie_file, load_json

logger = logging.getLogger(__name__)


def _qt_class(module_suffix: str, class_name: str):
    """Load the Qt binding already available in the FeelUOwn environment."""
    errors = []
    for binding in ("PyQt5", "PyQt6", "PySide6", "PySide2"):
        try:
            module = importlib.import_module(f"{binding}.{module_suffix}")
        except ImportError as exc:
            errors.append(exc)
            continue
        return getattr(module, class_name)
    raise ImportError("No supported Qt binding is installed") from errors[-1]


def _message_box():
    return _qt_class("QtWidgets", "QMessageBox")


def _message_parent(app):
    ui = getattr(app, "ui", None)
    left_panel = getattr(ui, "left_panel", None)
    return getattr(left_panel, "playlists_header", None)


def check_cookie() -> dict[str, str]:
    """Validate the persisted QQ Music cookie through the live provider."""
    from . import _path_value
    from fuo_qqmusic.provider import provider

    cookie_file = _path_value("CookieFile", default_cookie_file())
    document = load_json(cookie_file, default={"cookies": {}})
    if not isinstance(document, dict):
        raise CredentialError(f"cookie file is not a JSON object: {cookie_file}")

    cookies = document.get("cookies", document)
    if not isinstance(cookies, dict) or not cookies:
        raise CredentialError("QQ Music cookie is empty")

    user, error = provider.try_get_user_from_cookies(cookies)
    if user is None:
        raise CredentialError(error or "QQ Music cookie is unavailable")
    return {"name": str(user.name), "uin": str(user.identifier)}


class _CookieMenuController:
    def __init__(self, app, provider_ui):
        self.app = app
        self.provider_ui = provider_ui
        self.busy = False

    def add_items(self, menu) -> None:
        menu.addSeparator()
        status_action = menu.addAction("查看 Cookie 状态")
        status_action.triggered.connect(self.show_status)
        check_action = menu.addAction("检测 Cookie 可用性")
        check_action.triggered.connect(self.check_cookie)
        refresh_action = menu.addAction("强制更新 Cookie")
        refresh_action.triggered.connect(self.force_refresh)
        login_action = menu.addAction("全新网页登录并获取刷新凭据")
        login_action.triggered.connect(self.fresh_login)
        hide_action = menu.addAction("隐藏无音源搜索结果")
        if hasattr(hide_action, "setCheckable"):
            hide_action.setCheckable(True)
        if hasattr(hide_action, "setChecked"):
            from . import hide_unavailable_search_results

            hide_action.setChecked(hide_unavailable_search_results())
        hide_action.triggered.connect(self.toggle_hide_unavailable)
        check_source_action = menu.addAction("启用音源检测")
        if hasattr(check_source_action, "setCheckable"):
            check_source_action.setCheckable(True)
        if hasattr(check_source_action, "setChecked"):
            from . import search_source_check_enabled

            check_source_action.setChecked(search_source_check_enabled())
        check_source_action.triggered.connect(self.toggle_source_check)
        field_judge_action = menu.addAction("用搜索字段直接判定音源")
        if hasattr(field_judge_action, "setCheckable"):
            field_judge_action.setCheckable(True)
        if hasattr(field_judge_action, "setChecked"):
            from . import judge_by_search_fields

            field_judge_action.setChecked(judge_by_search_fields())
        field_judge_action.triggered.connect(self.toggle_field_judgment)
        vip_action = menu.addAction("我是 VIP 账号（免检测 VIP 歌）")
        if hasattr(vip_action, "setCheckable"):
            vip_action.setCheckable(True)
        if hasattr(vip_action, "setChecked"):
            from . import account_is_vip

            vip_action.setChecked(account_is_vip())
        vip_action.triggered.connect(self.toggle_account_vip)

    def toggle_hide_unavailable(self, checked: bool = True) -> None:
        from . import set_hide_unavailable_search_results

        set_hide_unavailable_search_results(bool(checked))

    def toggle_source_check(self, checked: bool = True) -> None:
        from . import set_search_source_check_enabled

        set_search_source_check_enabled(bool(checked))

    def toggle_field_judgment(self, checked: bool = True) -> None:
        from . import set_judge_by_search_fields

        set_judge_by_search_fields(bool(checked))

    def toggle_account_vip(self, checked: bool = True) -> None:
        from . import set_account_is_vip

        set_account_is_vip(bool(checked))

    def fresh_login(self) -> None:
        relogin = getattr(self.provider_ui, "_re_login", None)
        if relogin is None:
            self._show_error("网页登录失败", "官方 QQ 音乐 provider 不支持重新登录")
            return
        relogin()

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox = _message_box()
        QMessageBox.warning(_message_parent(self.app), title, message)

    def _show_info(self, title: str, message: str) -> None:
        QMessageBox = _message_box()
        QMessageBox.information(_message_parent(self.app), title, message)

    def _defer_dialog(self, method, title: str, message: str) -> None:
        """Show a modal dialog after the current qasync task has returned."""
        QTimer = _qt_class("QtCore", "QTimer")
        QTimer.singleShot(0, lambda: method(title, message))

    def show_status(self) -> None:
        from . import status

        try:
            info = status()
        except Exception as exc:
            self._show_error("Cookie 状态读取失败", str(exc))
            return

        result_text = {
            "success": "成功",
            "failed": "失败",
            "running": "刷新中",
            "never": "从未刷新",
        }.get(info["last_result"], str(info["last_result"]))
        monitoring_text = "运行中" if info["monitoring"] else "未运行"
        healthy_text = "正常" if info["healthy"] else "异常"
        message = "\n".join(
            (
                f"账号：{info['uin'] or '-'}",
                f"Cookie 文件：{'存在' if info['cookie_file_exists'] else '不存在'}",
                f"音乐密钥：{'存在' if info['has_music_key'] else '不存在'}",
                f"openid：{'存在' if info['has_open_id'] else '不存在'}",
                f"access_token：{'存在' if info['has_access_token'] else '不存在'}",
                f"refresh_token：{'存在' if info['has_refresh_token'] else '不存在'}",
                f"refresh_key：{'存在' if info['has_refresh_key'] else '不存在'}",
                f"刷新凭据：{'就绪' if info['refresh_ready'] else '缺失'}",
                f"自动监控：{monitoring_text}",
                f"最近刷新：{result_text}",
                f"健康状态：{healthy_text}",
                f"最近成功：{info['last_success_at'] or '-'}",
                f"下次刷新：{info['next_run_at'] or '-'}",
                f"最近错误：{info['last_error'] or '-'}",
            )
        )
        self._show_info("QQ 音乐 Cookie 状态", message)

    def check_cookie(self) -> None:
        if self.busy:
            return
        self.busy = True
        from feeluown.utils import aio

        aio.create_task(self._check_cookie_async())

    async def _check_cookie_async(self) -> None:
        from feeluown.utils.aio import run_fn

        try:
            user = await run_fn(check_cookie)
        except Exception as exc:
            self._defer_dialog(
                self._show_error,
                "Cookie 检测失败",
                f"当前 Cookie 不可用：{exc}",
            )
        else:
            self._defer_dialog(
                self._show_info,
                "Cookie 检测成功",
                f"当前 Cookie 可用\n用户：{user['name']}\nUIN：{user['uin']}",
            )
        finally:
            self.busy = False

    def force_refresh(self) -> None:
        if self.busy:
            return
        self.busy = True
        from feeluown.utils import aio

        aio.create_task(self._force_refresh_async())

    async def _force_refresh_async(self) -> None:
        from feeluown.utils.aio import run_fn

        try:
            from . import refresh_now, status

            await run_fn(refresh_now)
            info = status()
        except Exception as exc:
            self._defer_dialog(self._show_error, "Cookie 更新失败", str(exc))
        else:
            self._defer_dialog(
                self._show_info,
                "Cookie 更新成功",
                "\n".join(
                    (
                        f"账号：{info['uin'] or '-'}",
                        "新的 QQ Music Cookie 已写入文件",
                        f"下次自动刷新：{info['next_run_at'] or '-'}",
                    )
                ),
            )
        finally:
            self.busy = False


def install_qqmusic_ui(app, retries: int = 20) -> bool:
    """Add cookie actions to the already-registered QQ Music provider UI."""
    provider_ui = app.pvd_ui_mgr.get("qqmusic")
    if provider_ui is None:
        if retries > 0:
            QTimer = _qt_class("QtCore", "QTimer")
            QTimer.singleShot(100, lambda: install_qqmusic_ui(app, retries - 1))
        else:
            logger.warning("QQ Music provider UI was not available")
        return False

    if getattr(provider_ui, "_qqmusic_refresh_controller", None) is not None:
        return True

    original = getattr(provider_ui, "context_menu_add_items", None)
    if original is None:
        logger.warning("QQ Music provider UI does not support context menus")
        return False

    controller = _CookieMenuController(app, provider_ui)
    from .login_capture import install_login_capture

    if install_login_capture(provider_ui):
        logger.info("QQ Music web login credential capture enabled")

    def context_menu_add_items(menu, original=original, controller=controller):
        original(menu)
        controller.add_items(menu)

    provider_ui.context_menu_add_items = context_menu_add_items
    provider_ui._qqmusic_refresh_controller = controller
    provider_ui._qqmusic_refresh_original_context_menu_add_items = original
    return True


def uninstall_qqmusic_ui(app) -> None:
    provider_ui = app.pvd_ui_mgr.get("qqmusic")
    if provider_ui is None:
        return
    original = getattr(
        provider_ui, "_qqmusic_refresh_original_context_menu_add_items", None
    )
    if original is not None:
        provider_ui.context_menu_add_items = original
    from .login_capture import uninstall_login_capture

    uninstall_login_capture(provider_ui)
    for name in (
        "_qqmusic_refresh_controller",
        "_qqmusic_refresh_original_context_menu_add_items",
    ):
        if hasattr(provider_ui, name):
            delattr(provider_ui, name)
