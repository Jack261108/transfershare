#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from dataclasses import dataclass
import re
from typing import Optional, Union


_NETWORK_KEYWORDS = (
    "baidupcs._request",
    "network",
    "timeout",
    "connection",
    "urllib",
    "requests",
    "http",
    "ssl",
)


@dataclass(frozen=True)
class StorageErrorInfo:
    kind: str
    message: str
    raw_message: str
    code: Optional[str] = None
    retryable: bool = False


ErrorLike = Union[BaseException, str, None]


def error_to_text(error: ErrorLike) -> str:
    if error is None:
        return ""
    if isinstance(error, BaseException):
        return str(error)
    return str(error)


def _match_error_code(text: str) -> Optional[str]:
    patterns = (
        r"error_code:\s*(-?\d+)",
        r"['\"]errno['\"]\s*[:=]\s*(-?\d+)",
        r"['\"]error_code['\"]\s*[:=]\s*(-?\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _contains_cookie_marker(text: str) -> bool:
    lowered = text.lower()
    return "bduss" in text or "stoken" in text or "cookie" in lowered


def classify_storage_error(error: ErrorLike) -> StorageErrorInfo:
    raw_message = error_to_text(error)
    lowered = raw_message.lower()
    code = _match_error_code(raw_message)

    if any(keyword in lowered for keyword in _NETWORK_KEYWORDS):
        return StorageErrorInfo(
            kind="network",
            message="网络请求失败，请检查网络连接或稍后重试",
            raw_message=raw_message,
            code=code,
            retryable=True,
        )

    if code == "-65":
        return StorageErrorInfo(
            kind="rate_limit",
            message="触发频率限制，请稍后重试",
            raw_message=raw_message,
            code=code,
            retryable=True,
        )

    if code == "4":
        return StorageErrorInfo(
            kind="retry_abort",
            message=raw_message or "请求被中止",
            raw_message=raw_message,
            code=code,
        )

    if code == "31062":
        return StorageErrorInfo(
            kind="invalid_name",
            message="文件名非法",
            raw_message=raw_message,
            code=code,
        )

    if code == "31066" or "-9" in raw_message:
        return StorageErrorInfo(
            kind="missing_path",
            message="文件或目录不存在",
            raw_message=raw_message,
            code=code,
        )

    if "file already exists" in lowered:
        return StorageErrorInfo(
            kind="already_exists",
            message="文件或目录已存在",
            raw_message=raw_message,
            code=code,
        )

    if code == "115":
        return StorageErrorInfo(
            kind="share_forbidden",
            message="分享链接已失效（文件禁止分享）",
            raw_message=raw_message,
            code=code,
        )

    if code == "145":
        return StorageErrorInfo(
            kind="share_invalid",
            message="分享链接已失效",
            raw_message=raw_message,
            code=code,
        )

    if code == "200025":
        return StorageErrorInfo(
            kind="share_password",
            message="提取码输入错误，请检查提取码",
            raw_message=raw_message,
            code=code,
        )

    if "share" in lowered and "not found" in lowered:
        return StorageErrorInfo(
            kind="share_invalid",
            message="分享链接不存在或已失效",
            raw_message=raw_message,
            code=code,
        )

    if "password" in lowered and "wrong" in lowered:
        return StorageErrorInfo(
            kind="share_password",
            message="提取码错误",
            raw_message=raw_message,
            code=code,
        )

    if _contains_cookie_marker(raw_message):
        return StorageErrorInfo(
            kind="cookie_invalid",
            message="百度网盘登录已过期，请更新cookies",
            raw_message=raw_message,
            code=code,
        )

    if code is not None:
        return StorageErrorInfo(
            kind="error_code",
            message=f"分享链接访问失败（错误码：{code}）",
            raw_message=raw_message,
            code=code,
        )

    if len(raw_message) > 200 and "{" in raw_message:
        return StorageErrorInfo(
            kind="share_error",
            message="分享链接访问失败，请检查链接和提取码",
            raw_message=raw_message,
            code=code,
        )

    return StorageErrorInfo(
        kind="unknown",
        message=raw_message or "分享链接访问失败，请检查链接和提取码",
        raw_message=raw_message,
        code=code,
    )


def parse_share_error(error: ErrorLike) -> str:
    return classify_storage_error(error).message


def is_network_error(error: ErrorLike) -> bool:
    return classify_storage_error(error).kind == "network"


def is_rate_limit_error(error: ErrorLike) -> bool:
    return classify_storage_error(error).kind == "rate_limit"


def is_retry_abort_error(error: ErrorLike) -> bool:
    return classify_storage_error(error).kind == "retry_abort"


def is_missing_path_error(error: ErrorLike) -> bool:
    return classify_storage_error(error).kind == "missing_path"


def is_already_exists_error(error: ErrorLike) -> bool:
    return classify_storage_error(error).kind == "already_exists"


def is_invalid_name_error(error: ErrorLike) -> bool:
    return classify_storage_error(error).kind == "invalid_name"
