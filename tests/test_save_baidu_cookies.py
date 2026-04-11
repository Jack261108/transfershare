import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from save_baidu_cookies import (
    build_cookie_map,
    build_cookie_string,
    find_cookie,
    load_config,
    read_env_values,
)


class SaveBaiduCookiesTests(unittest.TestCase):
    def test_find_cookie_prefers_pan_domain(self):
        cookies = [
            {"name": "BDUSS", "value": "low", "domain": ".baidu.com"},
            {"name": "BDUSS", "value": "high", "domain": "pan.baidu.com"},
        ]

        result = find_cookie(cookies, "BDUSS")

        self.assertEqual("high", result)

    def test_find_cookie_returns_none_when_missing(self):
        self.assertIsNone(find_cookie([], "STOKEN"))

    def test_build_cookie_map_uses_domain_priority_and_skips_invalid_entries(self):
        cookies = [
            {"name": "BDUSS", "value": "fallback", "domain": ".baidu.com"},
            {"name": "BDUSS", "value": "preferred", "domain": "pan.baidu.com"},
            {"name": "STOKEN", "value": "token", "domain": ".pan.baidu.com"},
            {"name": "PANWEB", "value": None, "domain": "pan.baidu.com"},
            {"name": "", "value": "ignored", "domain": "pan.baidu.com"},
        ]

        result = build_cookie_map(cookies)

        self.assertEqual({"BDUSS": "preferred", "STOKEN": "token"}, result)

    def test_build_cookie_string_orders_preferred_then_sorted_remaining(self):
        cookie_map = {
            "ZKEY": "last",
            "STOKEN": "token",
            "BDUSS": "bduss",
            "AKEY": "first",
        }

        result = build_cookie_string(cookie_map)

        self.assertEqual("BDUSS=bduss; STOKEN=token; AKEY=first; ZKEY=last", result)

    def test_load_config_normalizes_alias_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "BAIDU_COOKIES": "BDUSS=foo; STOKEN=bar",
                        "SHARE_URLS": "https://pan.baidu.com/s/abc12345 /Docs",
                        "SAVE_DIR": "/Auto",
                    }
                ),
                encoding="utf-8",
            )

            result = load_config(config_path)

        self.assertEqual("BDUSS=foo; STOKEN=bar", result["cookies"])
        self.assertEqual("https://pan.baidu.com/s/abc12345 /Docs", result["share_urls"])
        self.assertEqual("/Auto", result["save_dir"])

    def test_load_config_exits_when_json_is_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text('{"cookies": "BDUSS=foo", invalid', encoding="utf-8")

            with patch("save_baidu_cookies.sys.exit", side_effect=SystemExit(1)):
                with self.assertRaises(SystemExit) as cm:
                    load_config(config_path)

        self.assertEqual(1, cm.exception.code)

    def test_load_config_exits_when_file_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "missing.json"

            with patch("save_baidu_cookies.sys.exit", side_effect=SystemExit(1)):
                with self.assertRaises(SystemExit) as cm:
                    load_config(config_path)

        self.assertEqual(1, cm.exception.code)

    def test_read_env_values_strips_quotes_and_ignores_unknown_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / "baidu_cookies.env"
            env_path.write_text(
                'BAIDU_COOKIES="BDUSS=foo; STOKEN=bar"\n'
                "IGNORED_KEY=ignored\n"
                "BAIDU_COOKIES_FULL='BDUSS=foo; STOKEN=bar; PANWEB=baz'\n",
                encoding="utf-8",
            )

            result = read_env_values(env_path)

        self.assertEqual("BDUSS=foo; STOKEN=bar", result["BAIDU_COOKIES"])
        self.assertEqual(
            "BDUSS=foo; STOKEN=bar; PANWEB=baz", result["BAIDU_COOKIES_FULL"]
        )

    def test_read_env_values_exits_when_file_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / "missing.env"

            with patch("save_baidu_cookies.sys.exit", side_effect=SystemExit(1)):
                with self.assertRaises(SystemExit) as cm:
                    read_env_values(env_path)

        self.assertEqual(1, cm.exception.code)


if __name__ == "__main__":
    unittest.main()
