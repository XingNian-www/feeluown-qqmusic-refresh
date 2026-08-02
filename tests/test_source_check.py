import sys
import time
import types
import unittest
from unittest import mock

from fuo_qqmusic_refresh import source_check
from fuo_qqmusic_refresh.source_check import (
    _judge_from_raw,
    _raw_meta_for,
    _stash_raw_songs,
    check_song_source,
    install_source_check,
    precheck_search_result,
    uninstall_source_check,
)


class FakeSong:
    def __init__(self, identifier, mid=None, media_id=None):
        self.identifier = identifier
        self.media_flags = None
        self._cache = {}
        if mid is not None:
            self._cache["mid"] = mid
        if media_id is not None:
            self._cache["media_id"] = media_id

    def cache_get(self, key):
        if key in self._cache:
            return self._cache[key], True
        return None, False

    def cache_set(self, key, value, ttl=None):
        self._cache[key] = value


def make_provider(get_song_url_v2=None):
    api = types.SimpleNamespace(_uin="12345")
    api.get_token_from_cookies = lambda: "token"
    api.get_song_url_v2 = get_song_url_v2 or mock.Mock(return_value="http://x")
    return types.SimpleNamespace(api=api)


class JudgeFromRawTests(unittest.TestCase):
    # 真实数据：芊芊 - 西瓜JUN/排骨教主（无音源）switch=65537
    # 真实数据：芊芊 - 排骨教主（VIP/有试听）switch=16897793
    # 真实数据：免费可播歌曲 switch=16889603
    def test_play_bits_off_and_no_try_means_unavailable(self):
        item = {"action": {"switch": 65537}, "pay": {"pay_play": 0}}
        self.assertIs(_judge_from_raw(item), False)

    def test_play_bits_off_with_try_bit_falls_back_to_probe(self):
        # 播放位全 0 但有试听位：全曲能否播放取决于账号，交给 URL 探测
        item = {"action": {"switch": 65537 | (1 << 14)}, "pay": {"pay_play": 0}}
        self.assertIsNone(_judge_from_raw(item))

    def test_free_song_with_play_bits_on_means_available(self):
        item = {"action": {"switch": 16889603}, "pay": {"pay_play": 0}}
        self.assertIs(_judge_from_raw(item), True)

    def test_vip_song_falls_back_to_probe(self):
        item = {"action": {"switch": 16897793}, "pay": {"pay_play": 1}}
        self.assertIsNone(_judge_from_raw(item))

    def test_vip_song_is_available_for_vip_account(self):
        item = {"action": {"switch": 16897793}, "pay": {"pay_play": 1}}
        with mock.patch("fuo_qqmusic_refresh.account_is_vip", return_value=True):
            self.assertIs(_judge_from_raw(item), True)

    def test_vip_account_does_not_excuse_missing_play_bits(self):
        # 播放位全 0 且无试听位是平台级无版权，VIP 也播不了
        item = {"action": {"switch": 65537}, "pay": {"pay_play": 1}}
        with mock.patch("fuo_qqmusic_refresh.account_is_vip", return_value=True):
            self.assertIs(_judge_from_raw(item), False)

    def test_all_zero_file_sizes_means_unavailable(self):
        item = {"file": {"size_128mp3": 0, "size_320mp3": 0, "size_flac": 0}}
        self.assertIs(_judge_from_raw(item), False)

    def test_try_only_file_is_not_conclusive(self):
        # 只有试听片段时不直接判无音源，交给 URL 探测按账号精确判断
        item = {"file": {"size_try": 12345}}
        self.assertIsNone(_judge_from_raw(item))

    def test_missing_fields_are_unknown(self):
        self.assertIsNone(_judge_from_raw({}))
        self.assertIsNone(_judge_from_raw({"action": {}, "pay": {}}))

    def test_string_switch_is_parsed(self):
        item = {"action": {"switch": "16889603"}, "pay": {"pay_play": "0"}}
        self.assertIs(_judge_from_raw(item), True)


class RawMetaStoreTests(unittest.TestCase):
    def setUp(self):
        source_check._raw_meta.clear()

    def test_stash_and_lookup_by_identifier(self):
        _stash_raw_songs([{"id": 42, "action": {"switch": 1}}])
        item = _raw_meta_for(FakeSong("42"))
        self.assertIsNotNone(item)
        self.assertEqual(item["id"], 42)

    def test_lookup_miss_returns_none(self):
        self.assertIsNone(_raw_meta_for(FakeSong("404")))

    def test_expired_entry_is_dropped(self):
        _stash_raw_songs([{"id": 7}])
        key = "7"
        _, item = source_check._raw_meta[key]
        source_check._raw_meta[key] = (time.monotonic() - 1, item)
        self.assertIsNone(_raw_meta_for(FakeSong("7")))
        self.assertNotIn(key, source_check._raw_meta)

    def test_non_list_and_non_dict_items_are_ignored(self):
        _stash_raw_songs("not-a-list")
        _stash_raw_songs(["x", {"no_id": 1}])
        self.assertEqual(len(source_check._raw_meta), 0)


class CheckSongSourceTests(unittest.TestCase):
    def setUp(self):
        source_check._cache.clear()
        source_check._raw_meta.clear()

    def seed_raw(self, identifier, item):
        source_check._raw_meta[str(identifier)] = (
            time.monotonic() + 60,
            item,
        )

    def test_no_source_song_is_judged_without_probing(self):
        provider = make_provider()
        song = FakeSong("1", mid="m1", media_id="md1")
        self.seed_raw("1", {"action": {"switch": 65537}, "pay": {"pay_play": 0}})
        self.assertIs(check_song_source(provider, song), False)
        provider.api.get_song_url_v2.assert_not_called()

    def test_free_song_is_available_without_probing(self):
        provider = make_provider()
        song = FakeSong("2", mid="m2", media_id="md2")
        self.seed_raw("2", {"action": {"switch": 16889603}, "pay": {"pay_play": 0}})
        self.assertIs(check_song_source(provider, song), True)
        provider.api.get_song_url_v2.assert_not_called()

    def test_vip_song_falls_back_to_url_probe(self):
        provider = make_provider(get_song_url_v2=mock.Mock(return_value=""))
        song = FakeSong("3", mid="m3", media_id="md3")
        self.seed_raw("3", {"action": {"switch": 16889603}, "pay": {"pay_play": 1}})
        self.assertIs(check_song_source(provider, song), False)
        provider.api.get_song_url_v2.assert_called_once_with("m3", "md3", "M500")

    def test_vip_account_skips_vip_song_probe(self):
        provider = make_provider()
        song = FakeSong("6", mid="m6", media_id="md6")
        self.seed_raw("6", {"action": {"switch": 16889603}, "pay": {"pay_play": 1}})
        with mock.patch("fuo_qqmusic_refresh.account_is_vip", return_value=True):
            self.assertIs(check_song_source(provider, song), True)
        provider.api.get_song_url_v2.assert_not_called()

    def test_field_judgment_disabled_uses_probe(self):
        provider = make_provider()
        song = FakeSong("4", mid="m4", media_id="md4")
        self.seed_raw("4", {"action": {"switch": 65537}, "pay": {"pay_play": 0}})
        with mock.patch(
            "fuo_qqmusic_refresh.judge_by_search_fields", return_value=False
        ):
            self.assertIs(check_song_source(provider, song), True)
        provider.api.get_song_url_v2.assert_called_once_with("m4", "md4", "M500")

    def test_probe_failure_is_unknown_not_unavailable(self):
        provider = make_provider(get_song_url_v2=mock.Mock(side_effect=RuntimeError))
        song = FakeSong("5", mid="m5", media_id="md5")
        self.assertIsNone(check_song_source(provider, song))


class FakeApiSearch:
    def __init__(self, raw):
        self.raw = raw
        self.calls = []

    def __call__(self, keyword, type_=0, limit=20, page=1):
        self.calls.append((keyword, type_))
        return self.raw


def build_fake_fuo_qqmusic(api_search, provider_search):
    provider_module = types.ModuleType("fuo_qqmusic.provider")
    package = types.ModuleType("fuo_qqmusic")
    api = types.SimpleNamespace(search=api_search, _uin="12345")
    api.get_token_from_cookies = lambda: "token"
    api.get_song_url_v2 = mock.Mock(return_value="http://x")
    provider = types.SimpleNamespace(search=provider_search, api=api)
    provider_module.provider = provider
    package.provider = provider_module
    modules = {"fuo_qqmusic": package, "fuo_qqmusic.provider": provider_module}
    return modules, provider


class InstallCaptureTests(unittest.TestCase):
    def setUp(self):
        source_check._cache.clear()
        source_check._raw_meta.clear()

    def test_api_search_wrapper_stashes_raw_items(self):
        raw = [
            {"id": 11, "action": {"switch": 1}, "pay": {"pay_play": 0}},
            {"id": 22, "action": {"switch": 2}, "pay": {"pay_play": 1}},
        ]
        api_search = FakeApiSearch(raw)
        modules, provider = build_fake_fuo_qqmusic(api_search, mock.Mock())
        with mock.patch.dict(sys.modules, modules):
            self.assertTrue(install_source_check())
            provider.api.search("keyword", type_=0)
            self.assertEqual(set(source_check._raw_meta), {"11", "22"})
            # 非歌曲搜索不暂存
            source_check._raw_meta.clear()
            provider.api.search("keyword", type_=1)
            self.assertEqual(len(source_check._raw_meta), 0)
            uninstall_source_check()
            self.assertIsNone(
                getattr(provider.api, "_qqmusic_refresh_meta_capture", None)
            )

    def test_end_to_end_hides_no_source_without_probing(self):
        raw = [
            {"id": 1, "action": {"switch": 65537}, "pay": {"pay_play": 0}},
            {"id": 2, "action": {"switch": 16889603}, "pay": {"pay_play": 0}},
        ]
        songs = [FakeSong("1", mid="m1", media_id="md1"),
                 FakeSong("2", mid="m2", media_id="md2")]

        def provider_search(keyword, **kwargs):
            data = provider.api.search(keyword, type_=0)
            self.assertEqual(data, raw)
            return types.SimpleNamespace(q=keyword, songs=list(songs))

        modules, provider = build_fake_fuo_qqmusic(FakeApiSearch(raw), provider_search)
        with mock.patch.dict(sys.modules, modules):
            self.assertTrue(install_source_check())
            result = provider.search("keyword")
            remaining = [s.identifier for s in result.songs]
            self.assertEqual(remaining, ["2"])
            provider.api.get_song_url_v2.assert_not_called()
            uninstall_source_check()

    def test_end_to_end_vip_song_uses_probe(self):
        raw = [{"id": 9, "action": {"switch": 16889603}, "pay": {"pay_play": 1}}]
        songs = [FakeSong("9", mid="m9", media_id="md9")]

        def provider_search(keyword, **kwargs):
            provider.api.search(keyword, type_=0)
            return types.SimpleNamespace(q=keyword, songs=list(songs))

        modules, provider = build_fake_fuo_qqmusic(FakeApiSearch(raw), provider_search)
        provider.api.get_song_url_v2 = mock.Mock(return_value="")
        with mock.patch.dict(sys.modules, modules):
            self.assertTrue(install_source_check())
            result = provider.search("keyword")
            self.assertEqual(result.songs, [])
            provider.api.get_song_url_v2.assert_called_once_with("m9", "md9", "M500")
            uninstall_source_check()

    def test_double_install_is_idempotent(self):
        modules, provider = build_fake_fuo_qqmusic(FakeApiSearch([]), mock.Mock())
        with mock.patch.dict(sys.modules, modules):
            self.assertTrue(install_source_check())
            wrapped = provider.search
            self.assertTrue(install_source_check())
            self.assertIs(provider.search, wrapped)
            uninstall_source_check()


if __name__ == "__main__":
    unittest.main()
