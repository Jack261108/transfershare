import unittest
from unittest.mock import patch

from validate_config import ConfigValidator


class ConfigValidatorTests(unittest.TestCase):
    def test_validate_all_returns_false_when_load_config_fails(self):
        validator = ConfigValidator("missing.json")

        with patch("validate_config.load_json_config", side_effect=FileNotFoundError("配置文件不存在: missing.json")), patch(
            "validate_config.validate_runtime_config"
        ) as mock_validate:
            result = validator.validate_all()

        self.assertFalse(result)
        self.assertTrue(any("配置文件不存在" in msg for msg in validator.errors))
        mock_validate.assert_not_called()

    def test_validate_all_aggregates_validation_results(self):
        validator = ConfigValidator("config.json")
        raw_config = {"cookies": "BDUSS=foo; STOKEN=bar", "share_urls": "https://pan.baidu.com/s/abc12345"}
        validated_config = {"cookies": "BDUSS=foo; STOKEN=bar", "share_count": 1, "save_dir": "/AutoTransfer"}

        with patch("validate_config.load_json_config", return_value=raw_config), patch(
            "validate_config.validate_runtime_config",
            return_value={
                "config": validated_config,
                "errors": [],
                "warnings": ["warning"],
                "info": ["info"],
            },
        ):
            result = validator.validate_all()

        self.assertTrue(result)
        self.assertEqual(validated_config, validator.config)
        self.assertIn("warning", validator.warnings)
        self.assertIn("info", validator.info_messages)
        self.assertTrue(any("成功加载配置文件" in msg for msg in validator.info_messages))


if __name__ == "__main__":
    unittest.main()
