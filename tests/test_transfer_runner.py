import sys
import types
import unittest
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

import transfer_runner


class TransferRunnerSmokeTests(unittest.TestCase):
    def test_main_runs_success_flow(self):
        config = {
            "config_source": "file",
            "config_path": "config.json",
            "cookies": "BDUSS=foo; STOKEN=bar",
            "wechat_webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
            "share_configs": [{"share_url": "https://pan.baidu.com/s/abc12345"}],
        }
        result = {
            "success": True,
            "summary": "完成",
            "transferred_files": ["video.mp4"],
        }
        fake_storage = Mock()
        fake_storage.is_valid.return_value = True
        fake_storage.get_quota_info.return_value = {"used_gb": 1, "total_gb": 10}
        fake_storage.transfer_multiple_shares.return_value = result
        fake_notifier = Mock()
        fake_notifier.send_transfer_result.return_value = True
        fake_logger = Mock()

        with patch.object(transfer_runner, "setup_logging"), patch.object(
            transfer_runner, "get_logger", return_value=fake_logger
        ), patch.object(transfer_runner, "log_startup"), patch.object(
            transfer_runner, "log_config_loaded"
        ), patch.object(transfer_runner, "check_network_connectivity"), patch.object(
            transfer_runner, "load_runtime_config", return_value=config
        ), patch.object(
            transfer_runner, "WeChatNotifier", return_value=fake_notifier
        ), patch.object(
            transfer_runner, "BaiduStorage", return_value=fake_storage
        ), patch.object(transfer_runner, "log_shutdown") as mock_shutdown:
            transfer_runner.main()

        fake_storage.transfer_multiple_shares.assert_called_once_with(
            share_configs=config["share_configs"],
            progress_callback=transfer_runner.progress_callback,
        )
        fake_notifier.send_transfer_result.assert_called_once_with(result, config)
        mock_shutdown.assert_called_once_with(success=True)

    def test_main_exits_when_transfer_fails(self):
        config = {
            "config_source": "file",
            "config_path": "config.json",
            "cookies": "BDUSS=foo; STOKEN=bar",
            "wechat_webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
            "share_configs": [{"share_url": "https://pan.baidu.com/s/abc12345"}],
        }
        result = {"success": False, "error": "失败"}
        fake_storage = Mock()
        fake_storage.is_valid.return_value = True
        fake_storage.get_quota_info.return_value = None
        fake_storage.transfer_multiple_shares.return_value = result
        fake_notifier = Mock()
        fake_notifier.send_transfer_result.return_value = True
        fake_logger = Mock()

        with patch.object(transfer_runner, "setup_logging"), patch.object(
            transfer_runner, "get_logger", return_value=fake_logger
        ), patch.object(transfer_runner, "log_startup"), patch.object(
            transfer_runner, "log_config_loaded"
        ), patch.object(transfer_runner, "check_network_connectivity"), patch.object(
            transfer_runner, "load_runtime_config", return_value=config
        ), patch.object(
            transfer_runner, "WeChatNotifier", return_value=fake_notifier
        ), patch.object(
            transfer_runner, "BaiduStorage", return_value=fake_storage
        ), patch.object(transfer_runner.sys, "exit", side_effect=SystemExit(1)), patch.object(
            transfer_runner, "log_shutdown"
        ) as mock_shutdown:
            with self.assertRaises(SystemExit) as cm:
                transfer_runner.main()

        self.assertEqual(1, cm.exception.code)
        fake_notifier.send_transfer_result.assert_called_once_with(result, config)
        mock_shutdown.assert_called_once_with(success=False)


if __name__ == "__main__":
    unittest.main()
