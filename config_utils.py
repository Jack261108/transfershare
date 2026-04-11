#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

DEFAULT_SAVE_DIR = "/AutoTransfer"
_SHARE_URL_PATTERN = re.compile(r"https://pan\.baidu\.com/s/[A-Za-z0-9_-]+")
_PWD_INLINE_PATTERN = re.compile(
    r"(?:\bpwd\b|密码|提取码)[:：]?\s*([A-Za-z0-9]{4})", re.IGNORECASE
)


def resolve_config_path(config_path: Union[Path, str] = "config.json") -> Path:
    path = Path(config_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def load_json_config(config_path: Union[Path, str] = "config.json") -> Dict[str, Any]:
    path = resolve_config_path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_config_aliases(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = dict(data or {})
    normalized = dict(raw)
    normalized["cookies"] = raw.get("cookies") or raw.get("BAIDU_COOKIES")
    normalized["share_urls"] = raw.get("share_urls") or raw.get("SHARE_URLS")
    normalized["save_dir"] = (
        raw.get("save_dir") or raw.get("SAVE_DIR") or DEFAULT_SAVE_DIR
    )
    normalized["wechat_webhook"] = raw.get("wechat_webhook") or raw.get(
        "WECHAT_WEBHOOK"
    )
    normalized["folder_filter"] = raw.get("folder_filter")
    normalized["regex_pattern"] = raw.get("regex_pattern")
    normalized["regex_replace"] = raw.get("regex_replace")
    return normalized


def load_env_config(env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    values = env or os.environ
    return normalize_config_aliases(
        {
            "BAIDU_COOKIES": values.get("BAIDU_COOKIES"),
            "SHARE_URLS": values.get("SHARE_URLS"),
            "SAVE_DIR": values.get("SAVE_DIR", DEFAULT_SAVE_DIR),
            "WECHAT_WEBHOOK": values.get("WECHAT_WEBHOOK"),
        }
    )


def parse_share_links_from_text(text: str, default_save_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    share_configs: List[Dict[str, Any]] = []
    lines = text.strip().split("\n") if text else []

    for line_idx, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue

        match = _SHARE_URL_PATTERN.search(line)
        if not match:
            continue

        share_url = match.group(0)
        pwd = None
        save_dir = None

        if "?pwd=" in line[match.start() :]:
            try:
                _, pwd_part = line[match.start() :].split("?pwd=", 1)
                pwd = pwd_part[:4]
            except Exception:
                pwd = None

        if not pwd:
            remain = line[match.end() :]
            pwd_match = _PWD_INLINE_PATTERN.search(remain)
            if pwd_match:
                pwd = pwd_match.group(1)

        next_line = lines[line_idx + 1].strip() if line_idx + 1 < len(lines) else ""
        if not _SHARE_URL_PATTERN.search(next_line):
            if not pwd and next_line:
                next_pwd_match = _PWD_INLINE_PATTERN.search(next_line)
                if next_pwd_match:
                    pwd = next_pwd_match.group(1)

        remain_after_url = line[match.end() :].strip()
        if remain_after_url:
            for token in remain_after_url.split():
                if token.startswith("/"):
                    save_dir = token
                    break

        if not save_dir and next_line and not _SHARE_URL_PATTERN.search(next_line):
            for token in next_line.split():
                if token.startswith("/"):
                    save_dir = token
                    break

        if not save_dir:
            save_dir = default_save_dir

        config = {
            "share_url": share_url,
            "pwd": pwd,
            "line_number": line_idx + 1,
        }
        if save_dir:
            config["save_dir"] = save_dir
        share_configs.append(config)

    return share_configs


def _serialize_share_config(
    share_config: Dict[str, Any], default_save_dir: Optional[str] = None
) -> str:
    share_url = str(share_config.get("share_url", "")).strip()
    if not share_url:
        raise ValueError("share_urls 中存在缺少 share_url 的对象配置")

    pwd = str(share_config.get("pwd") or "").strip()
    if pwd and "?pwd=" not in share_url:
        share_url = f"{share_url}?pwd={pwd}"

    save_dir = share_config.get("save_dir") or default_save_dir
    if save_dir:
        return f"{share_url} {save_dir}"
    return share_url


def _normalize_share_list_item(
    item: Any, default_save_dir: Optional[str] = None
) -> List[Dict[str, Any]]:
    if isinstance(item, dict):
        return [dict(item)]
    if isinstance(item, str) and item.strip():
        return parse_share_links_from_text(item.strip(), default_save_dir)
    return []


def normalize_share_urls_value(
    share_urls: Any, default_save_dir: Optional[str] = None
) -> Dict[str, Any]:
    if not share_urls:
        return {
            "share_urls": None,
            "share_urls_text": "",
            "share_configs": [],
            "share_count": 0,
            "raw_count": 0,
        }

    if isinstance(share_urls, str):
        text = share_urls.strip()
        if "," in text and "\n" not in text:
            text = "\n".join([item.strip() for item in text.split(",") if item.strip()])
        share_configs = parse_share_links_from_text(text, default_save_dir)
        raw_count = len([line for line in text.splitlines() if line.strip()])
        return {
            "share_urls": text,
            "share_urls_text": text,
            "share_configs": share_configs,
            "share_count": len(share_configs),
            "raw_count": raw_count,
        }

    if isinstance(share_urls, list):
        share_configs: List[Dict[str, Any]] = []
        share_urls_text_parts: List[str] = []
        raw_count = 0
        has_object_item = False

        for item in share_urls:
            if item in (None, "", []):
                continue

            raw_count += 1
            if isinstance(item, dict):
                has_object_item = True
                share_urls_text_parts.append(
                    _serialize_share_config(item, default_save_dir)
                )
            elif isinstance(item, str) and item.strip():
                share_urls_text_parts.append(item.strip())

            share_configs.extend(_normalize_share_list_item(item, default_save_dir))

        if has_object_item:
            normalized_value: Any = share_configs
        else:
            normalized_value = "\n".join(share_urls_text_parts)

        return {
            "share_urls": normalized_value,
            "share_urls_text": "\n".join(share_urls_text_parts),
            "share_configs": share_configs,
            "share_count": len(share_configs),
            "raw_count": raw_count,
        }

    raise TypeError(
        f"share_urls 格式错误，应为列表或字符串，当前类型: {type(share_urls).__name__}"
    )


def apply_global_share_defaults(
    share_configs: List[Dict[str, Any]], config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    applied_configs: List[Dict[str, Any]] = []
    for item in share_configs or []:
        share_config = dict(item)
        if not share_config.get("save_dir"):
            share_config["save_dir"] = config.get("save_dir") or DEFAULT_SAVE_DIR
        if config.get("folder_filter") and "folder_filter" not in share_config:
            share_config["folder_filter"] = config["folder_filter"]
        if config.get("regex_pattern") and "regex_pattern" not in share_config:
            share_config["regex_pattern"] = config["regex_pattern"]
        if config.get("regex_replace") is not None and "regex_replace" not in share_config:
            share_config["regex_replace"] = config["regex_replace"]
        applied_configs.append(share_config)
    return applied_configs


def build_share_urls_text(
    share_urls: Any, default_save_dir: Optional[str] = None
) -> str:
    share_data = normalize_share_urls_value(share_urls, default_save_dir)
    if share_data["share_urls_text"]:
        return share_data["share_urls_text"]
    return ""


def load_runtime_config(config_path: Union[Path, str] = "config.json") -> Dict[str, Any]:
    path = resolve_config_path(config_path)

    try:
        config = normalize_config_aliases(load_json_config(path))
        if not config.get("cookies"):
            raise ValueError("配置文件缺少 cookies (cookies/BAIDU_COOKIES)")
        if not config.get("share_urls"):
            raise ValueError("配置文件缺少 share_urls (share_urls/SHARE_URLS)")
        config["config_source"] = "file"
    except FileNotFoundError as exc:
        config = load_env_config()
        if not config.get("cookies"):
            raise ValueError("BAIDU_COOKIES 环境变量未设置")
        if not config.get("share_urls"):
            raise ValueError("SHARE_URLS 环境变量未设置")
        config["config_source"] = "env"
        config["config_load_warning"] = str(exc)

    share_data = normalize_share_urls_value(
        config.get("share_urls"), config.get("save_dir")
    )
    config.update(share_data)
    config["share_configs"] = apply_global_share_defaults(
        share_data["share_configs"], config
    )
    config["share_count"] = len(config["share_configs"])
    config["config_path"] = str(path)
    return config


def validate_runtime_config(config: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_config_aliases(config)
    errors: List[str] = []
    warnings: List[str] = []
    info_messages: List[str] = []

    cookies = normalized.get("cookies")
    if not cookies:
        errors.append("❌ 缺少 cookies 字段 (cookies 或 BAIDU_COOKIES)")
    elif not isinstance(cookies, str):
        errors.append(
            f"❌ cookies 必须是字符串，当前类型: {type(cookies).__name__}"
        )
    else:
        if "BDUSS" not in cookies:
            errors.append("❌ Cookies 中缺少 BDUSS")
        if "STOKEN" not in cookies:
            errors.append("❌ Cookies 中缺少 STOKEN")
        if not errors:
            cookie_count = len([item for item in cookies.split(";") if "=" in item])
            info_messages.append(f"✅ Cookies 有效 (包含 {cookie_count} 个值)")

    share_urls = normalized.get("share_urls")
    try:
        share_data = normalize_share_urls_value(share_urls, normalized.get("save_dir"))
    except TypeError as exc:
        share_data = {
            "share_urls": share_urls,
            "share_urls_text": "",
            "share_configs": [],
            "share_count": 0,
            "raw_count": 0,
        }
        errors.append(f"❌ {exc}")
    else:
        if not share_urls:
            errors.append("❌ 缺少 share_urls 字段 (share_urls 或 SHARE_URLS)")
        elif share_data["raw_count"] == 0:
            errors.append("❌ share_urls 为空")
        elif share_data["share_count"] == 0:
            errors.append("❌ 没有找到有效的分享链接")
        else:
            info_messages.append(
                f"✅ 分享链接有效 (共 {share_data['raw_count']} 项，其中 {share_data['share_count']} 个有效)"
            )

        if isinstance(share_urls, list):
            for idx, item in enumerate(share_urls, 1):
                if isinstance(item, dict):
                    share_url = str(item.get("share_url", "")).strip()
                    if not share_url:
                        errors.append(f"❌ 第 {idx} 个链接缺少 share_url 字段")
                    elif not _SHARE_URL_PATTERN.search(share_url):
                        warnings.append(
                            f"⚠️  第 {idx} 个链接格式可能不正确: {share_url[:50]}..."
                        )
                elif isinstance(item, str):
                    if item.strip() and not _SHARE_URL_PATTERN.search(item):
                        warnings.append(
                            f"⚠️  第 {idx} 个链接格式可能不正确: {item.strip()[:50]}..."
                        )
                elif item not in (None, "", []):
                    warnings.append(
                        f"⚠️  第 {idx} 个链接格式可能不正确: {str(item)[:50]}..."
                    )

    save_dir = normalized.get("save_dir") or DEFAULT_SAVE_DIR
    if not isinstance(save_dir, str):
        errors.append(
            f"❌ save_dir 必须是字符串，当前类型: {type(save_dir).__name__}"
        )
    else:
        if not save_dir:
            warnings.append("⚠️  未指定保存目录，将使用默认值: /AutoTransfer")
        elif not save_dir.startswith("/"):
            warnings.append(f"⚠️  保存目录不以 / 开头，可能导致问题: {save_dir}")
        info_messages.append(f"✅ 保存目录有效: {save_dir}")

    webhook = normalized.get("wechat_webhook")
    if not webhook:
        info_messages.append("ℹ️  未配置企业微信通知 (可选，不影响转存)")
    elif not isinstance(webhook, str):
        errors.append(
            f"❌ wechat_webhook 必须是字符串，当前类型: {type(webhook).__name__}"
        )
    else:
        if "qyapi.weixin.qq.com" not in webhook:
            warnings.append("⚠️  企业微信 Webhook 格式可能不正确")
        else:
            info_messages.append("✅ 企业微信 Webhook 有效")

    regex_pattern = normalized.get("regex_pattern")
    regex_replace = normalized.get("regex_replace")
    if not regex_pattern:
        info_messages.append("ℹ️  未设置文件过滤规则 (可选)")
    else:
        try:
            re.compile(regex_pattern)
            info_messages.append(f"✅ 正则过滤规则有效: {regex_pattern}")
            if regex_replace:
                try:
                    re.sub(regex_pattern, regex_replace, "test_file.mp4")
                    info_messages.append(f"✅ 正则替换规则有效: {regex_replace}")
                except Exception as exc:
                    warnings.append(f"⚠️  正则替换规则可能有问题: {exc}")
        except re.error as exc:
            errors.append(f"❌ 正则表达式错误: {exc}")

    folder_filter = normalized.get("folder_filter")
    if not folder_filter:
        info_messages.append("ℹ️  未设置文件夹过滤规则 (可选)")
    elif isinstance(folder_filter, str):
        try:
            re.compile(folder_filter)
            info_messages.append(f"✅ 文件夹过滤规则有效: {folder_filter}")
        except re.error as exc:
            errors.append(f"❌ 文件夹过滤规则错误: {exc}")
    elif isinstance(folder_filter, list):
        try:
            for idx, pattern in enumerate(folder_filter, 1):
                re.compile(pattern)
        except re.error as exc:
            errors.append(f"❌ 第 {idx} 个文件夹过滤规则错误: {exc}")
        else:
            info_messages.append(
                f"✅ 文件夹过滤规则有效 (共 {len(folder_filter)} 个)"
            )
    else:
        errors.append(
            f"❌ folder_filter 类型错误，应为字符串或列表，当前类型: {type(folder_filter).__name__}"
        )

    normalized.update(share_data)
    normalized["share_configs"] = apply_global_share_defaults(
        share_data["share_configs"], normalized
    )
    normalized["share_count"] = len(normalized["share_configs"])

    return {
        "config": normalized,
        "errors": errors,
        "warnings": warnings,
        "info": info_messages,
    }
