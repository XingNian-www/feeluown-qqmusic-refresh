import unittest

from fuo_qqmusic_refresh.credentials import Credentials
from fuo_qqmusic_refresh.device import Device
from fuo_qqmusic_refresh.protocol import (
    build_login_payload,
    compact_json,
    sign_payload,
)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.credentials = Credentials(
            uin="12345",
            token="Q_H_L_token",
            open_id="openid",
            access_token="access",
            refresh_token="refresh",
            refresh_key="key",
        )

    def test_sign_is_stable_and_looks_like_qq_music_sign(self):
        body = compact_json({"a": 1, "b": "中文"})
        first = sign_payload(body)
        self.assertEqual(first, sign_payload(body))
        self.assertTrue(first.startswith("zzc"))
        self.assertNotRegex(first, r"[\\/+=]")

    def test_login_payload_matches_mobile_rpc_shape(self):
        payload = build_login_payload(
            self.credentials,
            {"q16": "", "q36": "qimei36"},
            Device(),
        )
        self.assertEqual(payload["req"]["module"], "music.login.LoginServer")
        self.assertEqual(payload["req"]["method"], "Login")
        self.assertEqual(payload["req"]["param"]["refresh_key"], "key")
        self.assertEqual(payload["comm"]["qq"], "12345")


if __name__ == "__main__":
    unittest.main()
