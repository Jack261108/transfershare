import sys
import types
import unittest
from unittest.mock import Mock

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
from storage_client import BaiduClientAdapter
from storage_errors import classify_storage_error, parse_share_error
from storage_rules import apply_regex_rules, should_include_folder


class BaiduStoragePureMethodTests(unittest.TestCase):
    def setUp(self):
        self.storage = BaiduStorage.__new__(BaiduStorage)
        self.storage.path_service = Mock()
        self.storage.share_service = Mock()

    def test_parse_share_error_maps_known_cases(self):
        self.assertEqual(
            "分享链接已失效（文件禁止分享）",
            parse_share_error("error_code: 115"),
        )
        self.assertEqual(
            "提取码输入错误，请检查提取码",
            parse_share_error("{'errno': 200025}"),
        )
        self.assertEqual(
            "网络请求失败，请检查网络连接或稍后重试",
            parse_share_error("BaiduPCS._request timeout"),
        )

    def test_parse_share_error_simplifies_long_json_errors(self):
        long_error = "{" + "'errno': 999, " + "'message': 'x'" * 80 + "}"

        result = parse_share_error(long_error)

        self.assertEqual("分享链接访问失败（错误码：999）", result)

    def test_apply_regex_rules_handles_match_replace_and_invalid_pattern(self):
        self.assertEqual((True, "/dir/file.mp4"), apply_regex_rules("/dir/file.mp4"))
        self.assertEqual((False, "/dir/file.txt"), apply_regex_rules("/dir/file.txt", r"\\.mp4$"))
        self.assertEqual(
            (True, "/dir/video.mp4"),
            apply_regex_rules("/dir/file.mp4", r"file", "video"),
        )
        self.assertEqual((True, "/dir/file.mp4"), apply_regex_rules("/dir/file.mp4", "["))

    def test_should_include_folder_supports_none_string_list_and_invalid_regex(self):
        self.assertTrue(should_include_folder("Movies"))
        self.assertTrue(should_include_folder("Movies-2026", r"Movies"))
        self.assertFalse(should_include_folder("Shows-2026", r"Movies"))
        self.assertTrue(should_include_folder("Anime", [r"Movies", r"Anime"]))
        self.assertTrue(should_include_folder("Anything", "["))

    def test_classify_storage_error_supports_rate_limit_and_missing_path(self):
        rate_limit = classify_storage_error("error_code: -65")
        self.assertEqual("rate_limit", rate_limit.kind)
        self.assertTrue(rate_limit.retryable)

        missing_path = classify_storage_error("error_code: 31066, message: 文件不存在")
        self.assertEqual("missing_path", missing_path.kind)



class BaiduStorageFlowTests(unittest.TestCase):
    def setUp(self):
        self.storage = BaiduStorage.__new__(BaiduStorage)
        self.storage.client = Mock()
        self.storage.wechat_notifier = None
        self.storage._local_files_cache = {}
        self.storage.path_service = Mock()
        self.storage.share_service = Mock()

    def test_transfer_share_returns_skipped_when_no_transfer_candidates(self):
        self.storage._normalize_save_dir = Mock(return_value="/save")
        self.storage._load_share_context = Mock(
            return_value={
                "shared_paths": [Mock(is_dir=False)],
                "shared_files_info": [],
                "uk": 1,
                "share_id": 2,
                "bdstoken": "token",
            }
        )
        self.storage._scan_local_files_dict = Mock(return_value={})
        self.storage._build_transfer_list = Mock(return_value=[])

        result = self.storage.transfer_share("https://pan.baidu.com/s/abc")

        self.assertEqual(
            {"success": True, "skipped": True, "message": "没有新文件需要转存"},
            result,
        )

    def test_transfer_share_returns_dir_error_directly(self):
        self.storage._normalize_save_dir = Mock(return_value="/save")
        self.storage._load_share_context = Mock(
            return_value={
                "shared_paths": [Mock(is_dir=False)],
                "shared_files_info": [{"fs_id": 1, "path": "a.txt"}],
                "uk": 1,
                "share_id": 2,
                "bdstoken": "token",
            }
        )
        self.storage._scan_local_files_dict = Mock(return_value={})
        self.storage._build_transfer_list = Mock(return_value=[(1, "/save", "a.txt", "a.txt", False)])
        self.storage._ensure_transfer_dirs = Mock(
            return_value={"success": False, "error": "创建目录失败: /save"}
        )

        result = self.storage.transfer_share("https://pan.baidu.com/s/abc")

        self.assertEqual({"success": False, "error": "创建目录失败: /save"}, result)

    def test_transfer_share_executes_plan_and_builds_result(self):
        self.storage._normalize_save_dir = Mock(return_value="/save")
        self.storage._load_share_context = Mock(
            return_value={
                "shared_paths": [Mock(is_dir=False)],
                "shared_files_info": [{"fs_id": 1, "path": "a.txt"}],
                "uk": 1,
                "share_id": 2,
                "bdstoken": "token",
            }
        )
        self.storage._scan_local_files_dict = Mock(return_value={})
        transfer_list = [(1, "/save", "a.txt", "a.txt", False)]
        self.storage._build_transfer_list = Mock(return_value=transfer_list)
        self.storage._ensure_transfer_dirs = Mock(return_value=None)
        self.storage._execute_transfer_plan = Mock(return_value=(1, transfer_list))
        self.storage._rename_transferred_files = Mock(return_value=["a.txt"])
        self.storage._build_transfer_result = Mock(
            return_value={"success": True, "message": "成功转存 1/1 个文件", "transferred_files": ["a.txt"]}
        )

        result = self.storage.transfer_share("https://pan.baidu.com/s/abc")

        self.assertTrue(result["success"])
        self.storage._execute_transfer_plan.assert_called_once()
        self.storage._rename_transferred_files.assert_called_once_with(transfer_list, "/save", None)
        self.storage._build_transfer_result.assert_called_once_with(1, 1, ["a.txt"], None)

    def test_process_single_share_config_handles_successful_result(self):
        self.storage.transfer_share = Mock(
            return_value={"success": True, "message": "成功", "transferred_files": ["f1"]}
        )
        progress_callback = Mock()

        result = self.storage._process_single_share_config(
            1,
            2,
            {"share_url": "https://pan.baidu.com/s/abc", "save_dir": "/save"},
            progress_callback,
        )

        self.assertEqual(1, result["index"])
        self.assertTrue(result["success"])
        self.assertEqual("成功", result["message"])
        progress_callback.assert_any_call("success", "【1/2】成功: 成功")

    def test_process_single_share_config_handles_skipped_result(self):
        self.storage.transfer_share = Mock(
            return_value={"success": True, "skipped": True, "message": "没有新文件需要转存"}
        )
        progress_callback = Mock()

        result = self.storage._process_single_share_config(
            1,
            2,
            {"share_url": "https://pan.baidu.com/s/abc", "save_dir": "/save"},
            progress_callback,
        )

        self.assertTrue(result["skipped"])
        progress_callback.assert_any_call("info", "【1/2】跳过: 没有新文件需要转存")

    def test_process_single_share_config_handles_invalid_config(self):
        progress_callback = Mock()

        result = self.storage._process_single_share_config(1, 2, "bad-config", progress_callback)

        self.assertFalse(result["success"])
        self.assertIn("缺少分享链接", result["error"])
        progress_callback.assert_any_call("error", f"【1/2】失败: {result['error']}")

    def test_transfer_multiple_shares_aggregates_counts(self):
        self.storage._process_single_share_config = Mock(
            side_effect=[
                {"index": 1, "share_url": "u1", "save_dir": "/a", "success": True, "message": "成功"},
                {"index": 2, "share_url": "u2", "save_dir": "/b", "success": True, "skipped": True, "message": "跳过"},
                {"index": 3, "share_url": "u3", "save_dir": "/c", "success": False, "error": "失败"},
            ]
        )
        progress_callback = Mock()

        result = self.storage.transfer_multiple_shares(
            [
                {"share_url": "u1"},
                {"share_url": "u2"},
                {"share_url": "u3"},
            ],
            progress_callback,
        )

        self.assertTrue(result["success"])
        self.assertEqual(1, result["success_count"])
        self.assertEqual(1, result["skipped_count"])
        self.assertEqual(1, result["failed_count"])
        self.assertEqual(3, len(result["results"]))
        progress_callback.assert_any_call("success", result["summary"])

    def test_build_transfer_result_handles_complete_failure(self):
        result = self.storage._build_transfer_result(0, 2, [], None)

        self.assertEqual({"success": False, "error": "转存失败，没有文件成功转存"}, result)


class BaiduClientAdapterTests(unittest.TestCase):
    def test_parse_cookies_skips_invalid_items(self):
        result = BaiduClientAdapter.parse_cookies(
            "BDUSS=foo; invalid; STOKEN=bar; key = value "
        )

        self.assertEqual({"BDUSS": "foo", "STOKEN": "bar", "key": "value"}, result)

    def test_validate_cookies_requires_bduss_and_stoken(self):
        self.assertTrue(BaiduClientAdapter.validate_cookies({"BDUSS": "1", "STOKEN": "2"}))
        self.assertFalse(BaiduClientAdapter.validate_cookies({"BDUSS": "1"}))


if __name__ == "__main__":
    unittest.main()
