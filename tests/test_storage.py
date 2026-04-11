import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
from storage_shares import SharedPathService
from utils import format_error_info
from wechat_notifier import WeChatNotifier


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

    def test_format_error_info_masks_share_urls_and_pwd(self):
        error = ValueError(
            "分享链接: https://pan.baidu.com/s/abc12345?pwd=1a2B&foo=bar, 备用: surl=xyz987"
        )

        result = format_error_info(error, "处理失败")

        self.assertIn("https://pan.baidu.com/s/***?pwd=***&foo=bar", result)
        self.assertIn("surl=***", result)
        self.assertNotIn("abc12345", result)
        self.assertNotIn("1a2B", result)
        self.assertNotIn("xyz987", result)

    def test_format_error_info_masks_standalone_surl_in_plain_text(self):
        error = ValueError("普通文本里有备用码 surl=xyz987，可直接打开")

        result = format_error_info(error, "处理失败")

        self.assertIn("surl=***", result)
        self.assertNotIn("xyz987", result)


class SharedPathServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = SharedPathService(Mock())

    def test_resolve_shared_root_uses_common_parent(self):
        shared_paths = [
            SimpleNamespace(path="/sharelink123-456/电影", is_dir=True),
            SimpleNamespace(path="/sharelink123-456/单集.mp4", is_dir=False),
        ]

        self.assertEqual(
            "/sharelink123-456", self.service._resolve_shared_root(shared_paths)
        )

    def test_trim_shared_root_keeps_relative_structure(self):
        self.assertEqual(
            "电影/单集.mp4",
            self.service._trim_shared_root(
                "/sharelink123-456/电影/单集.mp4", "/sharelink123-456"
            ),
        )
        self.assertEqual(
            "单集.mp4",
            self.service._trim_shared_root(
                "/single-share/单集.mp4", "/single-share"
            ),
        )

    def test_list_shared_files_trims_root_without_hardcoded_sharelink_prefix(self):
        shared_paths = [
            SimpleNamespace(
                uk=1,
                share_id=2,
                bdstoken="token",
                is_dir=False,
                path="/single-share/单集.mp4",
                fs_id=10,
                size=123,
                md5="abc",
            )
        ]

        files = self.service.list_shared_files(shared_paths)

        self.assertEqual(
            [
                {
                    "server_filename": "单集.mp4",
                    "fs_id": 10,
                    "path": "单集.mp4",
                    "size": 123,
                    "isdir": 0,
                    "md5": "abc",
                }
            ],
            files,
        )

    def test_resolve_shared_root_keeps_top_level_dir_when_only_root_node_exists(self):
        shared_paths = [
            SimpleNamespace(
                path="/single-share",
                is_dir=True,
                uk=1,
                share_id=2,
                bdstoken="token",
            )
        ]

        self.assertEqual("/single-share", self.service._resolve_shared_root(shared_paths))

    def test_list_shared_files_trims_nested_paths_when_only_root_dir_node_is_provided(self):
        root_dir = SimpleNamespace(
            path="/single-share",
            is_dir=True,
            uk=1,
            share_id=2,
            bdstoken="token",
        )
        nested_file = SimpleNamespace(
            path="/single-share/子目录/单集.mp4",
            is_dir=False,
            fs_id=11,
            size=456,
            md5="def",
        )
        self.service.client.list_shared_paths.return_value = [nested_file]

        files = self.service.list_shared_files([root_dir])

        self.assertEqual(
            [
                {
                    "server_filename": "单集.mp4",
                    "fs_id": 11,
                    "path": "子目录/单集.mp4",
                    "size": 456,
                    "isdir": 0,
                    "md5": "def",
                }
            ],
            files,
        )


class WeChatNotifierTests(unittest.TestCase):
    def test_mask_sensitive_uses_shared_helper(self):
        notifier = WeChatNotifier("https://example.com")
        text = "分享链接: https://pan.baidu.com/s/abc12345?pwd=1a2B surl=xyz987"

        masked = notifier._mask_sensitive(text)

        self.assertEqual(
            "分享链接: https://pan.baidu.com/s/***?pwd=*** surl=***",
            masked,
        )
        self.assertNotIn("abc12345", masked)
        self.assertNotIn("1a2B", masked)
        self.assertNotIn("xyz987", masked)


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
        rename_result = {
            "transferred_files": ["a.txt"],
            "rename_failed_files": [],
            "rename_failed_count": 0,
            "completed_count": 1,
        }
        self.storage._rename_transferred_files = Mock(return_value=rename_result)
        self.storage._build_transfer_result = Mock(
            return_value={"success": True, "message": "成功转存 1/1 个文件", "transferred_files": ["a.txt"]}
        )

        result = self.storage.transfer_share("https://pan.baidu.com/s/abc")

        self.assertTrue(result["success"])
        self.storage._execute_transfer_plan.assert_called_once()
        self.storage._rename_transferred_files.assert_called_once_with(transfer_list, "/save", None)
        self.storage._build_transfer_result.assert_called_once_with(
            1,
            1,
            {
                "transferred_files": ["a.txt"],
                "rename_failed_files": [],
                "rename_failed_count": 0,
                "completed_count": 1,
            },
            None,
        )

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

    def test_transfer_multiple_shares_aggregates_counts_as_partial_when_has_failure(self):
        self.storage._process_single_share_config = Mock(
            side_effect=[
                {"index": 1, "share_url": "u1", "save_dir": "/a", "success": True, "partial": False, "message": "成功"},
                {"index": 2, "share_url": "u2", "save_dir": "/b", "success": True, "partial": False, "skipped": True, "message": "跳过"},
                {"index": 3, "share_url": "u3", "save_dir": "/c", "success": False, "partial": False, "error": "失败"},
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

        self.assertFalse(result["success"])
        self.assertTrue(result["partial"])
        self.assertEqual(1, result["success_count"])
        self.assertEqual(1, result["skipped_count"])
        self.assertEqual(1, result["failed_count"])
        self.assertEqual(0, result["partial_count"])
        self.assertEqual(3, len(result["results"]))
        progress_callback.assert_any_call(
            "warning", result["summary"] + "（部分成功按失败退出，退出码 1）"
        )

    def test_transfer_multiple_shares_collects_partial_rename_failed_details(self):
        self.storage._process_single_share_config = Mock(
            side_effect=[
                {
                    "index": 1,
                    "share_url": "u1",
                    "save_dir": "/a",
                    "success": False,
                    "partial": True,
                    "message": "部分成功",
                    "rename_failed_files": [
                        {"source_path": "old/a.txt", "target_path": "new/a.txt", "error": "boom"}
                    ],
                }
            ]
        )

        result = self.storage.transfer_multiple_shares([{"share_url": "u1"}])

        self.assertTrue(result["partial"])
        self.assertEqual(1, result["rename_failed_count"])
        self.assertEqual("old/a.txt", result["rename_failed_files"][0]["source_path"])

    def test_build_transfer_list_skips_rename_candidate_when_source_exists_to_avoid_duplicate_copy(self):
        self.storage.path_service.normalize_path.side_effect = lambda path, file_only=False: path.strip("/")
        progress_callback = Mock()

        result = self.storage._build_transfer_list(
            [{"fs_id": 1, "path": "old/a.txt", "md5": "src-md5"}],
            [Mock(is_dir=False)],
            "/save",
            {"old/a.txt": "other-md5"},
            regex_pattern=r"old",
            regex_replace="new",
            progress_callback=progress_callback,
        )

        self.assertEqual([], result)
        progress_callback.assert_any_call(
            "warning", "源路径已存在，跳过重复转存以避免副本: old/a.txt -> new/a.txt"
        )

    def test_build_transfer_list_skips_rename_candidate_when_target_exists(self):
        self.storage.path_service.normalize_path.side_effect = lambda path, file_only=False: path.strip("/")
        progress_callback = Mock()

        result = self.storage._build_transfer_list(
            [{"fs_id": 1, "path": "old/a.txt", "md5": "src-md5"}],
            [Mock(is_dir=False)],
            "/save",
            {"new/a.txt": "src-md5"},
            regex_pattern=r"old",
            regex_replace="new",
            progress_callback=progress_callback,
        )

        self.assertEqual([], result)
        progress_callback.assert_any_call(
            "info", "重命名目标已存在且内容相同（MD5 相同），跳过: new/a.txt"
        )

    def test_rename_transferred_files_reports_failures_as_partial(self):
        self.storage.client.rename.side_effect = RuntimeError("rename boom")
        self.storage.path_service.ensure_dir_exists.return_value = True
        progress_callback = Mock()

        result = self.storage._rename_transferred_files(
            [(1, "/save/old", "old/a.txt", "new/a.txt", True)],
            "/save",
            progress_callback,
        )

        self.assertEqual([], result["transferred_files"])
        self.assertEqual(1, result["rename_failed_count"])
        self.assertEqual(0, result["completed_count"])
        self.assertEqual("old/a.txt", result["rename_failed_files"][0]["source_path"])
        self.assertEqual("new/a.txt", result["rename_failed_files"][0]["target_path"])

    def test_build_transfer_result_handles_partial_rename_failure(self):
        result = self.storage._build_transfer_result(
            2,
            2,
            {
                "transferred_files": ["done.txt"],
                "rename_failed_files": [
                    {"source_path": "old/a.txt", "target_path": "new/a.txt", "error": "boom"}
                ],
                "rename_failed_count": 1,
                "completed_count": 1,
            },
            None,
        )

        self.assertFalse(result["success"])
        self.assertTrue(result["partial"])
        self.assertEqual(1, result["completed_count"])
        self.assertEqual(1, result["rename_failed_count"])
        self.assertIn("重命名失败", result["message"])

    def test_build_transfer_result_treats_transfer_success_with_all_rename_failures_as_partial(self):
        result = self.storage._build_transfer_result(
            2,
            2,
            {
                "transferred_files": [],
                "rename_failed_files": [
                    {"source_path": "old/a.txt", "target_path": "new/a.txt", "error": "boom"},
                    {"source_path": "old/b.txt", "target_path": "new/b.txt", "error": "boom"},
                ],
                "rename_failed_count": 2,
                "completed_count": 0,
            },
            None,
        )

        self.assertFalse(result["success"])
        self.assertTrue(result["partial"])
        self.assertEqual(0, result["completed_count"])
        self.assertEqual(2, result["rename_failed_count"])
        self.assertEqual(2, result["transfer_success_count"])

    def test_build_transfer_result_handles_complete_failure(self):
        result = self.storage._build_transfer_result(
            0,
            2,
            {
                "transferred_files": [],
                "rename_failed_files": [],
                "rename_failed_count": 0,
                "completed_count": 0,
            },
            None,
        )

        self.assertEqual(
            {
                "success": False,
                "partial": False,
                "error": "转存失败，没有文件成功转存",
                "rename_failed_files": [],
                "rename_failed_count": 0,
                "completed_count": 0,
                "transfer_success_count": 0,
            },
            result,
        )


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
