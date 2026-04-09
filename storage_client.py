#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import functools
import os
import random
import time
from threading import Lock

from baidupcs_py.baidupcs import BaiduPCSApi

from storage_errors import (
    classify_storage_error,
    is_network_error,
    is_retry_abort_error,
)

try:
    from logger import get_logger
except ImportError:
    import logging

    def get_logger(name="transfershare"):
        return logging.getLogger(name)


DEFAULT_REQUEST_TIMEOUT = 60
DEFAULT_RETRY_DELAY = 2
DEFAULT_MIN_RETRY_DELAY = 1
MAX_RETRY_DELAY = 30
MAX_RETRIES_GITHUB = 5
MAX_RETRIES_LOCAL = 3


class BaiduClientAdapter:
    def __init__(self, cookies):
        self._client_lock = Lock()
        self.client = None
        self.default_timeout = DEFAULT_REQUEST_TIMEOUT
        self.is_github_actions = os.getenv("GITHUB_ACTIONS") == "true"
        self.base_retry_delay = (
            DEFAULT_RETRY_DELAY if self.is_github_actions else DEFAULT_MIN_RETRY_DELAY
        )
        self.max_retries = (
            MAX_RETRIES_GITHUB if self.is_github_actions else MAX_RETRIES_LOCAL
        )
        self._init_client(cookies)

    def _inject_timeout(self):
        logger = get_logger()
        pcs_candidate = self._get_pcs_candidate()

        if pcs_candidate:
            if not getattr(pcs_candidate, "_timeout_patched", False):
                self._patch_request_methods(pcs_candidate)
                logger.debug("成功注入超时逻辑到 BaiduPCSApi 请求方法。")
            else:
                logger.debug("超时逻辑已存在，无需重复注入。")
        else:
            logger.warning("未找到可用的 pcs 属性，无法注入超时逻辑。")

    def _get_pcs_candidate(self):
        logger = get_logger()
        for attr in ("_pcs", "pcs", "baidupcs", "_baidupcs"):
            if hasattr(self.client, attr):
                logger.debug(f"找到 pcs 属性：{attr}")
                return getattr(self.client, attr)
        logger.debug("未找到任何有效的 pcs 属性。")
        return None

    def _patch_request_methods(self, pcs_candidate):
        def _wrap_timeout(fn):
            @functools.wraps(fn)
            def _wrapped(*args, **kwargs):
                if "timeout" not in kwargs or kwargs.get("timeout") is None:
                    kwargs["timeout"] = self.default_timeout
                return fn(*args, **kwargs)

            return _wrapped

        logger = get_logger()
        request_methods = [
            "_requestf",
            "_request_get",
            "_request_post",
            "request",
            "_request",
        ]
        for method_name in request_methods:
            if hasattr(pcs_candidate, method_name):
                logger.debug(f"为方法 {method_name} 注入超时逻辑。")
                setattr(
                    pcs_candidate,
                    method_name,
                    _wrap_timeout(getattr(pcs_candidate, method_name)),
                )

        setattr(pcs_candidate, "_timeout_patched", True)
        logger.debug("成功注入超时设置并标记 '_timeout_patched'。")

    def call_with_retry(self, func, *args, **kwargs):
        last_error = None
        logger = get_logger()

        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    if self.is_github_actions:
                        delay = self.base_retry_delay * (
                            2 ** (attempt - 1)
                        ) + random.uniform(0, 1.5)
                    else:
                        delay = self.base_retry_delay * attempt
                    delay = min(delay, MAX_RETRY_DELAY)
                    logger.debug(f"第{attempt + 1}次重试，等待{delay:.1f}秒...")
                    time.sleep(delay)

                return func(*args, **kwargs)
            except Exception as exc:
                last_error = exc
                error_info = classify_storage_error(exc)
                if is_network_error(exc):
                    if attempt < self.max_retries - 1:
                        logger.debug(
                            f"网络请求失败（第{attempt + 1}次尝试）: {error_info.raw_message}"
                        )
                        continue
                    logger.warning(f"网络请求最终失败，已重试{self.max_retries}次")
                    break
                if is_retry_abort_error(exc):
                    last_error = None
                    break
                raise

        if last_error is not None:
            raise last_error
        return None

    def _init_client(self, cookies):
        with self._client_lock:
            cookies_dict = self.parse_cookies(cookies)
            if not self.validate_cookies(cookies_dict):
                raise ValueError("Cookies 验证失败，缺少 BDUSS 或 STOKEN")

            for retry in range(3):
                try:
                    self.client = BaiduPCSApi(cookies=cookies_dict)
                    self.default_timeout = int(
                        os.getenv("BAIDU_REQUEST_TIMEOUT", str(DEFAULT_REQUEST_TIMEOUT))
                    )
                    self._inject_timeout()
                    self.client.quota()
                    return True
                except Exception as exc:
                    if retry < 2:
                        time.sleep(3)
                    else:
                        raise ValueError(
                            f"百度网盘客户端初始化失败: {str(exc)}"
                        ) from exc

    @staticmethod
    def validate_cookies(cookies):
        try:
            required_cookies = ["BDUSS", "STOKEN"]
            missing = [c for c in required_cookies if c not in cookies]
            if missing:
                return False
            return True
        except Exception:
            return False

    @staticmethod
    def parse_cookies(cookies_str):
        cookies = {}
        if not cookies_str:
            return cookies

        items = cookies_str.split(";")
        for item in items:
            if not item.strip() or "=" not in item:
                continue
            key, value = item.split("=", 1)
            cookies[key.strip()] = value.strip()
        return cookies

    def quota(self):
        return self.client.quota()

    def list(self, path):
        return self.client.list(path)

    def makedir(self, path):
        return self.client.makedir(path)

    def rename(self, source, target):
        return self.client.rename(source, target)

    def access_shared(self, share_url, pwd=None):
        return self.call_with_retry(self.client.access_shared, share_url, pwd)

    def shared_paths(self, **kwargs):
        return self.call_with_retry(self.client.shared_paths, **kwargs)

    def list_shared_paths(self, *args, **kwargs):
        return self.call_with_retry(self.client.list_shared_paths, *args, **kwargs)

    def transfer_shared_paths(self, **kwargs):
        return self.call_with_retry(self.client.transfer_shared_paths, **kwargs)
