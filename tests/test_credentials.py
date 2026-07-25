import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import fuo_qqmusic_refresh as plugin
from fuo_qqmusic_refresh.credentials import credentials_from_sources
from fuo_qqmusic_refresh.storage import save_json, update_cookie_document


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
        self.assertNotIn("psrf_qqopenid", updated["cookies"])

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
