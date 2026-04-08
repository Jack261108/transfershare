import unittest

from save_baidu_cookies import build_cookie_map, build_cookie_string, find_cookie


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


if __name__ == "__main__":
    unittest.main()
