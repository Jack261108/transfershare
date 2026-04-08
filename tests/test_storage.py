import sys
import types
import unittest

if "baidupcs_py" not in sys.modules:
    baidupcs_module = types.ModuleType("baidupcs_py")
    baidupcs_submodule = types.ModuleType("baidupcs_py.baidupcs")

    class DummyBaiduPCSApi:
        pass

    baidupcs_submodule.BaiduPCSApi = DummyBaiduPCSApi
    baidupcs_module.baidupcs = baidupcs_submodule
    sys.modules["baidupcs_py"] = baidupcs_module
    sys.modules["baidupcs_py.baidupcs"] = baidupcs_submodule

from storage import BaiduStorage


class BaiduStoragePureMethodTests(unittest.TestCase):
    def setUp(self):
        self.storage = BaiduStorage.__new__(BaiduStorage)

    def test_parse_cookies_skips_invalid_items(self):
        result = self.storage._parse_cookies("BDUSS=foo; invalid; STOKEN=bar; key = value ")

        self.assertEqual({"BDUSS": "foo", "STOKEN": "bar", "key": "value"}, result)

    def test_parse_share_error_maps_known_cases(self):
        self.assertEqual(
            "分享链接已失效（文件禁止分享）",
            self.storage._parse_share_error("error_code: 115"),
        )
        self.assertEqual(
            "提取码输入错误，请检查提取码",
            self.storage._parse_share_error("{'errno': 200025}"),
        )
        self.assertEqual(
            "网络请求失败，请检查网络连接或稍后重试",
            self.storage._parse_share_error("BaiduPCS._request timeout"),
        )

    def test_parse_share_error_simplifies_long_json_errors(self):
        long_error = "{" + "'errno': 999, " + "'message': 'x'" * 80 + "}"

        result = self.storage._parse_share_error(long_error)

        self.assertEqual("分享链接访问失败（错误码：999）", result)

    def test_apply_regex_rules_handles_match_replace_and_invalid_pattern(self):
        self.assertEqual(
            (True, "/dir/file.mp4"),
            self.storage._apply_regex_rules("/dir/file.mp4"),
        )
        self.assertEqual(
            (False, "/dir/file.txt"),
            self.storage._apply_regex_rules("/dir/file.txt", r"\\.mp4$"),
        )
        self.assertEqual(
            (True, "/dir/video.mp4"),
            self.storage._apply_regex_rules("/dir/file.mp4", r"file", "video"),
        )
        self.assertEqual(
            (True, "/dir/file.mp4"),
            self.storage._apply_regex_rules("/dir/file.mp4", "["),
        )

    def test_should_include_folder_supports_none_string_list_and_invalid_regex(self):
        self.assertTrue(self.storage._should_include_folder("Movies"))
        self.assertTrue(self.storage._should_include_folder("Movies-2026", r"Movies"))
        self.assertFalse(self.storage._should_include_folder("Shows-2026", r"Movies"))
        self.assertTrue(
            self.storage._should_include_folder("Anime", [r"Movies", r"Anime"])
        )
        self.assertTrue(self.storage._should_include_folder("Anything", "["))


if __name__ == "__main__":
    unittest.main()
