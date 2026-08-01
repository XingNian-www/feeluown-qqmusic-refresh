import unittest
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import fuo_qqmusic_refresh as plugin
from fuo_qqmusic_refresh.credentials import (
    CredentialError,
    credential_presence,
    credentials_from_sources,
    validate_refresh_credentials,
)
from fuo_qqmusic_refresh.storage import save_json, update_cookie_document
from fuo_qqmusic_refresh import source_check
from fuo_qqmusic_refresh.ui import (
    _CookieMenuController,
    check_cookie,
    install_qqmusic_ui,
)


class _FakeAction:
    def __init__(self, label):
        self.label = label
        self.triggered = SimpleNamespace(connect=lambda callback: None)


class _FakeMenu:
    def __init__(self):
        self.labels = []

    def addSeparator(self):
        self.labels.append("separator")

    def addAction(self, label):
        self.labels.append(label)
        return _FakeAction(label)


class _FakeSong:
    def __init__(self, identifier):
        self.identifier = identifier
        self.media_flags = "unknown"
        self._cache = {"mid": f"mid-{identifier}", "media_id": f"media-{identifier}"}

    def cache_get(self, key):
        return self._cache.get(key), key in self._cache

    def cache_set(self, key, value, ttl=None):
        self._cache[key] = value


class _FakeSourceApi:
    def __init__(self, available=True, available_ids=None):
        self._uin = "12345"
        self.available = available
        self.available_ids = set(available_ids or ())
        self.calls = []

    def get_token_from_cookies(self):
        return 5381

    def get_song_url_v2(self, mid, media_id, quality):
        self.calls.append((mid, media_id, quality))
        identifier = str(media_id).removeprefix("media-")
        is_available = self.available or identifier in self.available_ids
        return "https://audio.example/song.mp3" if is_available else ""


class CredentialTests(unittest.TestCase):
    def test_extracts_browser_cookie_fields(self):
        credentials = credentials_from_sources(
            {
                "uin": "12345",
                "qqmusic_key": "Q_H_L_old",
                "psrf_qqopenid": "openid",
                "psrf_qqaccess_token": "access",
                "psrf_qqrefresh_token": "refresh",
            }
        )
        self.assertEqual(credentials.uin, "12345")
        self.assertEqual(credentials.token, "Q_H_L_old")
        self.assertEqual(credentials.refresh_token, "refresh")

    def test_state_and_override_fill_optional_mobile_fields(self):
        credentials = credentials_from_sources(
            {"uin": "12345", "qm_keyst": "W_X_old"},
            {"refresh_key": "state-key"},
            {"open_id": "override-openid"},
        )
        self.assertEqual(credentials.token, "W_X_old")
        self.assertEqual(credentials.refresh_key, "state-key")
        self.assertEqual(credentials.open_id, "override-openid")

    def test_saved_state_wins_over_an_old_bootstrap_override(self):
        credentials = credentials_from_sources(
            {"uin": "12345", "qqmusic_key": "token"},
            {"refresh_key": "new-state-key"},
            {"refresh_key": "old-config-key"},
        )
        self.assertEqual(credentials.refresh_key, "new-state-key")

    def test_refresh_requires_a_refresh_credential(self):
        credentials = credentials_from_sources(
            {"uin": "12345", "qqmusic_key": "token"}
        )
        with self.assertRaisesRegex(CredentialError, "refresh_token or refresh_key"):
            validate_refresh_credentials(credentials)

    def test_credential_presence_never_contains_secret_values(self):
        result = credential_presence(
            {
                "uin": "12345",
                "qqmusic_key": "secret-key",
                "psrf_qqrefresh_token": "secret-refresh-token",
            }
        )
        self.assertEqual(
            result,
            {
                "has_uin": True,
                "has_music_key": True,
                "has_open_id": False,
                "has_access_token": False,
                "has_refresh_token": True,
                "has_refresh_key": False,
                "refresh_ready": True,
            },
        )

    def test_response_updates_existing_cookie_aliases(self):
        document = {
            "identifier": "12345",
            "cookies": {"uin": "12345", "qqmusic_key": "old", "qm_keyst": "old"},
        }
        updated = update_cookie_document(
            document,
            {
                "musicid": 12345,
                "musickey": "new",
                "openid": "new-openid",
            },
        )
        self.assertEqual(updated["cookies"]["qqmusic_key"], "new")
        self.assertEqual(updated["cookies"]["qm_keyst"], "new")
        self.assertEqual(updated["cookies"]["psrf_qqopenid"], "new-openid")

    def test_response_adds_refresh_fields_to_basic_browser_cookie(self):
        updated = update_cookie_document(
            {"cookies": {"uin": "12345", "qqmusic_key": "old"}},
            {"refresh_token": "new-refresh-token", "refresh_key": "new-refresh-key"},
        )
        self.assertEqual(
            updated["cookies"]["psrf_qqrefresh_token"], "new-refresh-token"
        )
        self.assertEqual(updated["cookies"]["psrf_qqrefresh_key"], "new-refresh-key")

    def test_status_reports_persisted_refresh_health_without_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cookie_file = root / "cookies.json"
            state_file = root / "state.json"
            save_json(cookie_file, {"cookies": {"uin": "12345", "qqmusic_key": "secret"}})
            save_json(
                state_file,
                {
                    "uin": "12345",
                    "status": {
                        "last_result": "success",
                        "last_success_at": "2026-07-25T00:00:00+00:00",
                    },
                },
            )
            config = SimpleNamespace(
                CookieFile=str(cookie_file),
                StateFile=str(state_file),
                Enabled=True,
            )
            with patch.object(plugin, "_config", config):
                result = plugin.status()
            self.assertTrue(result["healthy"])
            self.assertTrue(result["has_music_key"])
            self.assertNotIn("secret", str(result))

    def test_check_cookie_delegates_to_qqmusic_provider(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cookie_file = Path(temp_dir) / "cookies.json"
            save_json(cookie_file, {"cookies": {"uin": "12345", "qqmusic_key": "key"}})
            user = SimpleNamespace(name="tester", identifier="12345")
            qq_provider = SimpleNamespace(
                try_get_user_from_cookies=lambda cookies: (user, "")
            )
            qqmusic_package = types.ModuleType("fuo_qqmusic")
            qqmusic_provider = types.ModuleType("fuo_qqmusic.provider")
            qqmusic_provider.provider = qq_provider
            qqmusic_package.provider = qqmusic_provider
            config = SimpleNamespace(CookieFile=str(cookie_file))
            with patch.dict(
                sys.modules,
                {
                    "fuo_qqmusic": qqmusic_package,
                    "fuo_qqmusic.provider": qqmusic_provider,
                },
            ), patch.object(plugin, "_config", config):
                self.assertEqual(
                    check_cookie(),
                    {"name": "tester", "uin": "12345"},
                )

    def test_install_qqmusic_ui_adds_cookie_actions_once(self):
        original_calls = []

        def original(menu):
            original_calls.append(True)

        provider_ui = SimpleNamespace(
            provider=SimpleNamespace(meta=SimpleNamespace(identifier="qqmusic")),
            context_menu_add_items=original,
        )
        app = SimpleNamespace(
            pvd_ui_mgr=SimpleNamespace(get=lambda identifier: provider_ui)
        )
        self.assertTrue(install_qqmusic_ui(app))
        menu = _FakeMenu()
        provider_ui.context_menu_add_items(menu)
        self.assertEqual(original_calls, [True])
        self.assertEqual(
            menu.labels,
            [
                "separator",
                "查看 Cookie 状态",
                "检测 Cookie 可用性",
                "强制更新 Cookie",
                "全新网页登录并获取刷新凭据",
                "隐藏无音源搜索结果",
                "启用音源检测",
            ],
        )
        self.assertTrue(install_qqmusic_ui(app))


class SourceCheckTests(unittest.TestCase):
    def setUp(self):
        with source_check._cache_lock:
            source_check._cache.clear()

    def test_checks_supplemental_results_until_five_are_playable(self):
        api = _FakeSourceApi(
            available=False,
            available_ids={"5", "6", "7", "8", "9"},
        )
        provider = SimpleNamespace(api=api)
        songs = [_FakeSong(str(index)) for index in range(12)]
        result = SimpleNamespace(songs=songs)

        source_check.precheck_search_result(result, provider)

        self.assertEqual(len(api.calls), 10)
        self.assertTrue(all(call[2] == "M500" for call in api.calls))
        self.assertEqual(songs[0]._cache["qqmusic_source_available"], False)
        self.assertEqual(
            [song.identifier for song in result.songs],
            [str(index) for index in range(5, 12)],
        )
        self.assertNotIn("qqmusic_source_available", songs[10]._cache)

    def test_source_check_uses_cache(self):
        api = _FakeSourceApi()
        provider = SimpleNamespace(api=api)
        song = _FakeSong("1")

        self.assertTrue(source_check.check_song_source(provider, song))
        self.assertTrue(source_check.check_song_source(provider, song))

        self.assertEqual(len(api.calls), 1)

    def test_config_can_keep_unavailable_search_results(self):
        api = _FakeSourceApi(available=False)
        provider = SimpleNamespace(api=api)
        result = SimpleNamespace(songs=[_FakeSong(str(index)) for index in range(3)])
        config = SimpleNamespace(HideUnavailableSearchResults=False)

        with patch.object(plugin, "_config", config):
            source_check.precheck_search_result(result, provider)

        self.assertEqual([song.identifier for song in result.songs], ["0", "1", "2"])
        self.assertEqual(len(api.calls), 3)

    def test_gui_toggle_updates_hide_setting(self):
        config = SimpleNamespace(HideUnavailableSearchResults=True)
        controller = _CookieMenuController(SimpleNamespace(), SimpleNamespace())

        with patch.object(plugin, "_config", config):
            controller.toggle_hide_unavailable(False)
            self.assertFalse(plugin.hide_unavailable_search_results())

    def test_config_can_disable_source_check(self):
        api = _FakeSourceApi(available=False)
        provider = SimpleNamespace(api=api)
        result = SimpleNamespace(songs=[_FakeSong(str(index)) for index in range(5)])
        config = SimpleNamespace(EnableSearchSourceCheck=False)

        with patch.object(plugin, "_config", config):
            source_check.precheck_search_result(result, provider)

        self.assertEqual(api.calls, [])

    def test_gui_toggle_updates_source_check_setting(self):
        config = SimpleNamespace(EnableSearchSourceCheck=True)
        controller = _CookieMenuController(SimpleNamespace(), SimpleNamespace())

        with patch.object(plugin, "_config", config):
            controller.toggle_source_check(False)
            self.assertFalse(plugin.search_source_check_enabled())

    def test_search_wrapper_skips_non_song_search(self):
        api = _FakeSourceApi()
        provider = SimpleNamespace(api=api)

        def original_search(keyword, **kwargs):
            return SimpleNamespace(songs=[_FakeSong("1")])

        provider.search = original_search
        qqmusic_package = types.ModuleType("fuo_qqmusic")
        qqmusic_provider = types.ModuleType("fuo_qqmusic.provider")
        qqmusic_provider.provider = provider
        with patch.dict(
            sys.modules,
            {
                "fuo_qqmusic": qqmusic_package,
                "fuo_qqmusic.provider": qqmusic_provider,
            },
        ):
            self.assertTrue(source_check.install_source_check())
            provider.search("query", type_="album")
            self.assertEqual(api.calls, [])
            source_check.uninstall_source_check()
