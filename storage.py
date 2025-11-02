#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from collections import Counter
import functools
from baidupcs_py.baidupcs import BaiduPCSApi
from baidupcs_py.baidupcs.errors import BaiduPCSError

import json
import os
import time
import re
import posixpath
from threading import Lock
import random
import traceback

# 添加 WeChatNotifier 和工具方法导入
from wechat_notifier import WeChatNotifier
from utils import (
    print_detailed_error,
    format_error_info,
    send_wechat_alert,
    collect_error,
    handle_error_and_notify,
    ErrorCollector,
    error_collection,
    mask_cookies,
)


class BaiduStorage:
    def __init__(self, cookies, wechat_webhook=None):
        self._client_lock = Lock()
        self.client = None
        self._init_client(cookies)
        self.last_request_time = 0
        self.min_request_interval = 2
        # GitHub Actions环境检测
        self.is_github_actions = os.getenv("GITHUB_ACTIONS") == "true"
        # 在GitHub Actions环境中使用更激进的重试策略（指数退避+抖动）
        self.base_retry_delay = 2 if self.is_github_actions else 1
        self.max_retries = 5 if self.is_github_actions else 3

        # 初始化微信通知器
        self.wechat_notifier = (
            WeChatNotifier(wechat_webhook) if wechat_webhook else None
        )

    def _inject_timeout(self):
        """
        为客户端请求方法注入超时逻辑
        """
        pcs_candidate = self._get_pcs_candidate()

        if pcs_candidate:
            if not getattr(pcs_candidate, "_timeout_patched", False):
                # 执行注入操作
                self._patch_request_methods(pcs_candidate)
                print("成功注入超时逻辑到 BaiduPCSApi 请求方法。")
            else:
                print("超时逻辑已存在，无需重复注入。")
        else:
            print("未找到可用的 pcs 属性，无法注入超时逻辑。")

    def _get_pcs_candidate(self):
        """
        获取可用的 BaiduPCS 实例属性
        """
        for attr in ("_pcs", "pcs", "baidupcs", "_baidupcs"):
            if hasattr(self.client, attr):
                print(f"找到 pcs 属性：{attr}")
                return getattr(self.client, attr)
        print("未找到任何有效的 pcs 属性。")
        return None

    def _patch_request_methods(self, pcs_candidate):
        """
        为 BaiduPCS 实例中的请求方法注入超时
        """

        def _wrap_timeout(fn):
            """
            装饰器：为请求方法注入超时
            """

            @functools.wraps(fn)
            def _wrapped(*args, **kwargs):
                if "timeout" not in kwargs or kwargs.get("timeout") is None:
                    kwargs["timeout"] = self.default_timeout
                return fn(*args, **kwargs)

            return _wrapped

        # 注入超时逻辑
        request_methods = [
            "_requestf",
            "_request_get",
            "_request_post",
            "request",
            "_request",
        ]
        for method_name in request_methods:
            if hasattr(pcs_candidate, method_name):
                print(f"为方法 {method_name} 注入超时逻辑。")
                setattr(
                    pcs_candidate,
                    method_name,
                    _wrap_timeout(getattr(pcs_candidate, method_name)),
                )

        # 标记已注入超时设置
        setattr(pcs_candidate, "_timeout_patched", True)
        print("成功注入超时设置并标记 '_timeout_patched'。")

    def _retry_on_network_error(self, func, *args, **kwargs):
        """网络请求重试装饰器"""
        last_error = None

        for attempt in range(self.max_retries):
            try:
                # 在 GitHub Actions 环境采用指数退避+抖动；本地使用线性退避
                if attempt > 0:
                    if self.is_github_actions:
                        delay = self.base_retry_delay * (
                            2 ** (attempt - 1)
                        ) + random.uniform(0, 1.5)
                    else:
                        delay = self.base_retry_delay * attempt
                    # 最大等待 30 秒以避免过长阻塞
                    delay = min(delay, 30)
                    print(f"第{attempt + 1}次重试，等待{delay:.1f}秒...")
                    time.sleep(delay)

                # 执行请求
                return func(*args, **kwargs)

            except Exception as e:
                last_error = e
                error_str = str(e)
                if any(
                    keyword in error_str.lower()
                    for keyword in [
                        "baidupcs._request",
                        "network",
                        "timeout",
                        "connection",
                        "urllib",
                        "requests",
                        "http",
                        "ssl",
                    ]
                ):
                    if attempt < self.max_retries - 1:
                        print(f"网络请求失败（第{attempt + 1}次尝试）: {error_str}")
                        continue
                    else:
                        print(f"网络请求最终失败，已重试{self.max_retries}次")
                        # 收集最终失败的错误
                        collect_error(
                            e, f"网络请求最终失败，已重试{self.max_retries}次"
                        )
                        break
                elif "error_code: 4" in error_str:
                    last_error = None
                    break
                else:
                    # 非网络错误，直接抛出（由 ErrorCollector 统一处理聚合）
                    raise e

        # 所有重试都失败，抛出最后一个错误（由 ErrorCollector 统一处理聚合）
        if last_error is not None:
            raise last_error

    def _init_client(self, cookies):
        """初始化客户端"""
        with self._client_lock:
            try:
                cookies_dict = self._parse_cookies(cookies)
                if not self._validate_cookies(cookies_dict):
                    error_msg = "Cookies验证失败"
                    # 统一错误处理
                    handle_error_and_notify(
                        ValueError(error_msg),
                        "百度网盘客户端初始化失败",
                        self.wechat_notifier,
                        None,
                        collect=False,
                    )
                    return False

                # 使用重试机制初始化客户端
                for retry in range(3):
                    try:
                        self.client = BaiduPCSApi(cookies=cookies_dict)
                        # 获取超时时间，缺省为 60 秒
                        self.default_timeout = int(
                            os.getenv("BAIDU_REQUEST_TIMEOUT", "60")
                        )
                        self._inject_timeout()
                        # 验证客户端
                        quota = self.client.quota()
                        total_gb = round(quota[0] / (1024**3), 2)
                        used_gb = round(quota[1] / (1024**3), 2)
                        return True
                    except Exception as e:
                        if retry < 2:
                            time.sleep(3)
                        else:
                            # 使用统一的错误处理函数
                            handle_error_and_notify(
                                e,
                                "百度网盘客户端初始化最终失败",
                                self.wechat_notifier,
                                None,
                                collect=False,
                            )
                            return False

            except Exception as e:
                # 使用统一的错误处理函数
                handle_error_and_notify(
                    e,
                    "百度网盘客户端初始化异常",
                    self.wechat_notifier,
                    None,
                    collect=False,
                )
                return False

    def _validate_cookies(self, cookies):
        """验证cookies是否有效
        Args:
            cookies: cookies字典
        Returns:
            bool: 是否有效
        """
        try:
            required_cookies = ["BDUSS", "STOKEN"]
            missing = [c for c in required_cookies if c not in cookies]
            if missing:
                return False
            return True
        except Exception as e:
            return False

    def _parse_cookies(self, cookies_str):
        """解析 cookies 字符串为字典
        Args:
            cookies_str: cookies 字符串，格式如 'key1=value1; key2=value2'
        Returns:
            dict: cookies 字典
        """
        cookies = {}
        if not cookies_str:
            return cookies

        items = cookies_str.split(";")
        for item in items:
            if not item.strip():
                continue
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            cookies[key.strip()] = value.strip()
        return cookies

    def get_quota_info(self):
        """获取网盘配额信息"""
        try:
            if not self.client:
                return None

            quota_info = self.client.quota()
            if isinstance(quota_info, (tuple, list)):
                quota = {
                    "total": quota_info[0],
                    "used": quota_info[1],
                    "total_gb": round(quota_info[0] / (1024**3), 2),
                    "used_gb": round(quota_info[1] / (1024**3), 2),
                }
            else:
                quota = quota_info

            return quota
        except Exception as e:
            # 使用统一的错误处理函数
            handle_error_and_notify(
                e,
                "获取网盘配额信息时发生异常",
                self.wechat_notifier,
                None,
                collect=False,
            )
            return None

    def is_valid(self):
        """检查存储是否可用"""
        try:
            if not self.client:
                return False

            # 尝试获取配额信息来验证客户端是否有效
            quota_info = self.get_quota_info()
            return bool(quota_info)

        except Exception as e:
            # 使用统一的错误处理函数
            handle_error_and_notify(
                e, "检查存储可用性时发生异常", self.wechat_notifier, None, collect=False
            )
            return False

    def _normalize_path(self, path, file_only=False):
        """标准化路径
        Args:
            path: 原始路径
            file_only: 是否只返回文件名
        Returns:
            str: 标准化后的路径
        """
        try:
            # 统一使用正斜杠，去除多余斜杠
            path = path.replace("\\", "/").strip("/")

            if file_only:
                # 只返回文件名
                return path.split("/")[-1]

            # 确保目录以 / 开头
            if not path.startswith("/"):
                path = "/" + path
            return path
        except Exception as e:
            return path

    def _ensure_dir_exists(self, path):
        """确保目录存在：自顶向下构建路径树，已存在则跳过，减少递归与日志噪音
        Args:
            path: 目录路径，如 '/a/b/c'
        Returns:
            bool: 是否成功
        """
        try:
            # 检查客户端是否可用
            if not self.client:
                error_msg = "客户端未初始化或初始化失败"
                handle_error_and_notify(
                    ValueError(error_msg),
                    "创建目录失败: 客户端不可用",
                    self.wechat_notifier,
                    None,
                    collect=True,
                )
                return False

            path = self._normalize_path(path)
            if path in ("", "/"):  # 根目录视为已存在
                return True

            # 自顶向下逐级创建，避免“父目录不存在”的重复错误
            # 例：/a/b/c -> ['/a', '/a/b', '/a/b/c']
            parts = [p for p in path.strip("/").split("/") if p]
            prefixes = []
            curr = ""
            for p in parts:
                curr = f"{curr}/{p}" if curr else f"/{p}"
                prefixes.append(curr)

            for seg in prefixes:
                try:
                    self.client.makedir(seg)
                except Exception as ce:
                    msg = str(ce)
                    # 已存在则跳过下一层
                    if "file already exists" in msg.lower():
                        continue
                    # 文件名非法（立即失败）
                    if "error_code: 31062" in msg:
                        err = ValueError(f"创建目录失败，文件名非法: {seg}")
                        handle_error_and_notify(
                            err,
                            "创建目录失败: 文件名非法",
                            self.wechat_notifier,
                            None,
                            collect=True,
                        )
                        return False
                    # 某些实现可能在已存在时抛其他错误，做一次存在性校验
                    try:
                        self.client.list(seg)
                        continue
                    except Exception as le:
                        # 确认真的不可用再报错
                        handle_error_and_notify(
                            ce,
                            f"创建目录出错\n目录路径: {seg}",
                            self.wechat_notifier,
                            None,
                            collect=True,
                        )
                        return False

            return True
        except Exception as e:
            handle_error_and_notify(
                e,
                f"确保目录存在时发生异常\n目录路径: {path}",
                self.wechat_notifier,
                None,
                collect=True,
            )
            return False

    def _parse_share_error(self, error_str):
        """解析分享链接相关的错误信息，返回用户友好的错误消息
        Args:
            error_str: 原始错误信息字符串
        Returns:
            str: 用户友好的错误信息
        """
        try:
            # 检查BaiduPCS._request错误
            if "BaiduPCS._request" in error_str:
                return "网络请求失败，请检查网络连接或稍后重试"

            # 检查错误码115（分享文件禁止分享）
            if "error_code: 115" in error_str:
                return "分享链接已失效（文件禁止分享）"

            # 检查错误码145或errno: 145（分享链接失效）
            if "error_code: 145" in error_str or "'errno': 145" in error_str:
                return "分享链接已失效"

            # 检查错误码200025（提取码错误）
            if "error_code: 200025" in error_str or "'errno': 200025" in error_str:
                return "提取码输入错误，请检查提取码"

            # 检查其他常见分享错误
            if "share" in error_str.lower() and "not found" in error_str.lower():
                return "分享链接不存在或已失效"

            if "password" in error_str.lower() and "wrong" in error_str.lower():
                return "提取码错误"

            # 检查cookies相关错误
            if (
                "BDUSS" in error_str
                or "STOKEN" in error_str
                or "cookie" in error_str.lower()
            ):
                return "百度网盘登录已过期，请更新cookies"

            # 如果包含复杂的JSON错误信息，尝试简化
            if "{" in error_str and "errno" in error_str:
                # 尝试提取错误码
                import re

                errno_match = re.search(r"'errno':\s*(\d+)", error_str)
                if errno_match:
                    errno = int(errno_match.group(1))
                    if errno == 145:
                        return "分享链接已失效"
                    elif errno == 200025:
                        return "提取码输入错误，请检查提取码"
                    elif errno == 115:
                        return "分享链接已失效（文件禁止分享）"
                    else:
                        return f"分享链接访问失败（错误码：{errno}）"

            # 如果没有匹配到特定错误，返回简化后的原始错误
            # 移除复杂的JSON信息
            if len(error_str) > 200 and "{" in error_str:
                return "分享链接访问失败，请检查链接和提取码"

            return error_str

        except Exception as e:
            return "分享链接访问失败，请检查链接和提取码"

    def _apply_regex_rules(self, file_path, regex_pattern=None, regex_replace=None):
        """应用正则处理规则
        Args:
            file_path: 原始文件路径
            regex_pattern: 正则表达式模式
            regex_replace: 替换字符串
        Returns:
            tuple: (should_transfer, final_path)
                should_transfer: 是否应该转存（False表示被过滤掉）
                final_path: 处理后的文件路径
        """
        try:
            if not regex_pattern:
                # 没有规则，直接返回原文件
                return True, file_path

            try:
                # 1. 尝试匹配
                match = re.search(regex_pattern, file_path)
                if not match:
                    # 匹配失败 = 文件被过滤掉
                    return False, file_path

                # 2. 匹配成功，检查是否需要重命名
                if regex_replace and regex_replace.strip():
                    # 有替换内容，执行重命名
                    new_path = re.sub(regex_pattern, regex_replace, file_path)
                    if new_path != file_path:
                        return True, new_path

                # 3. 匹配成功但无重命名，返回原路径
                return True, file_path

            except re.error as e:
                # 正则错误时不过滤，返回原文件
                return True, file_path

        except Exception as e:
            # 出错时返回原始路径，不影响正常流程
            return True, file_path

    def list_local_files(self, dir_path):
        """获取指定目录下已存在文件的相对路径集合
        返回相对于 dir_path 的规范化相对路径（使用正斜杠），用于去重对比
        """
        try:
            # 检查客户端是否可用
            if not self.client:
                error_msg = "客户端未初始化或初始化失败"
                handle_error_and_notify(
                    ValueError(error_msg),
                    f"获取本地文件列表失败: 客户端不可用",
                    self.wechat_notifier,
                    None,
                    collect=False,
                )
                return set()

            files = []

            # 检查目录是否存在
            try:
                self.client.list(dir_path)
            except Exception as e:
                if "error_code: 31066, message: 文件不存在" in str(e) or "-9" in str(e):
                    return set()
                else:
                    handle_error_and_notify(
                        e,
                        f"检查本地目录时发生错误\n目录路径: {dir_path}",
                        self.wechat_notifier,
                        None,
                        collect=False,
                    )
                    return set()

            base = dir_path.replace("\\", "/")
            if not base.endswith("/"):
                base += "/"

            def _list_dir(path):
                try:
                    content = self.client.list(path)
                    for item in content:
                        if item.is_file:
                            if item.is_file:
                                # 只保留文件名进行对比
                                md5 = item.md5
                                file_name = os.path.basename(item.path)
                                files.append({"file_name": file_name, "md5": item.md5})
                            #   logger.debug(f"记录本地文件: {file_name}")
                        elif item.is_dir:
                            _list_dir(item.path)
                except Exception as e:
                    handle_error_and_notify(
                        e,
                        f"列出目录内容时发生错误\n目录路径: {path}",
                        self.wechat_notifier,
                        None,
                        collect=False,
                    )
                    raise

            _list_dir(dir_path)
            return files
        except Exception as e:
            handle_error_and_notify(
                e,
                f"获取本地文件列表时发生异常\n目录路径: {dir_path}",
                self.wechat_notifier,
                None,
                collect=False,
            )
            return set()

    def _get_remote_file_md5(self, full_path: str):
        """查询目标网盘上指定文件的 md5（若 API 返回）
        full_path: 形如 '/apps/xxx/dir/file.ext'
        返回 md5 字符串或 None
        """
        try:
            parent = posixpath.dirname(full_path).replace("\\", "/")
            name = os.path.basename(full_path)
            try:
                items = self.client.list(parent)
            except Exception as e:
                handle_error_and_notify(
                    e,
                    f"查询目标文件MD5时列目录失败\n目录路径: {parent}",
                    self.wechat_notifier,
                    None,
                    collect=False,
                )
                return None
            for it in items:
                try:
                    if (
                        getattr(it, "is_file", False)
                        and os.path.basename(getattr(it, "path", "")) == name
                    ):
                        if hasattr(it, "_asdict"):
                            d = it._asdict()
                            return d.get("md5") or None
                        return getattr(it, "md5", None)
                except Exception:
                    continue
            return None
        except Exception as e:
            handle_error_and_notify(
                e,
                f"获取目标文件MD5时发生异常\n文件路径: {full_path}",
                self.wechat_notifier,
                None,
                collect=False,
            )
            return None

    def _extract_file_info(self, file_dict):
        """从文件字典中提取文件信息
        Args:
            file_dict: 文件信息字典
        Returns:
            dict: 标准化的文件信息
        """
        try:
            if isinstance(file_dict, dict):
                # 如果没有 server_filename，从路径中提取
                server_filename = file_dict.get("server_filename", "")
                if not server_filename and file_dict.get("path"):
                    server_filename = file_dict["path"].split("/")[-1]

                return {
                    "server_filename": server_filename,
                    "fs_id": file_dict.get("fs_id", ""),
                    "path": file_dict.get("path", ""),
                    "size": file_dict.get("size", 0),
                    "isdir": file_dict.get("isdir", 0),
                    "md5": file_dict.get("md5", None),
                }
            return None
        except Exception as e:
            return None

    def _list_shared_dir_files(self, path, uk, share_id, bdstoken):
        """递归获取共享目录下的所有文件
        Args:
            path: 目录路径
            uk: 用户uk
            share_id: 分享ID
            bdstoken: token
        Returns:
            list: 文件列表
        """
        files = []
        try:
            # 检查客户端是否可用
            if not self.client:
                error_msg = "客户端未初始化或初始化失败"
                handle_error_and_notify(
                    ValueError(error_msg),
                    f"获取共享目录文件失败: 客户端不可用",
                    self.wechat_notifier,
                    None,
                    collect=False,
                )
                return files

            # 分页获取所有文件
            page = 1
            page_size = 100
            all_sub_files = []

            while True:
                sub_paths = self.client.list_shared_paths(
                    path.path, uk, share_id, bdstoken, page=page, size=page_size
                )

                if isinstance(sub_paths, list):
                    sub_files = sub_paths
                elif isinstance(sub_paths, dict):
                    sub_files = sub_paths.get("list", [])
                else:
                    break

                if not sub_files:
                    # 没有更多文件了
                    break

                all_sub_files.extend(sub_files)

                # 如果当前页文件数少于页大小，说明已经是最后一页
                if len(sub_files) < page_size:
                    break

                page += 1

            sub_files = all_sub_files

            for sub_file in sub_files:
                if hasattr(sub_file, "_asdict"):
                    sub_file_dict = sub_file._asdict()
                else:
                    sub_file_dict = sub_file if isinstance(sub_file, dict) else {}

                # 如果是目录，递归获取
                is_dir = getattr(sub_file, "is_dir", False)
                if is_dir:
                    sub_dir_files = self._list_shared_dir_files(
                        sub_file, uk, share_id, bdstoken
                    )
                    files.extend(sub_dir_files)
                else:
                    # 如果是文件，添加到列表
                    file_info = self._extract_file_info(sub_file_dict)
                    if file_info:
                        # 去掉路径中的 sharelink 部分
                        sub_file_path = getattr(sub_file, "path", "")
                        if sub_file_path:
                            file_info["path"] = re.sub(
                                r"^/sharelink\d*-\d+/?", "", sub_file_path
                            )
                            # 去掉开头的斜杠
                            file_info["path"] = file_info["path"].lstrip("/")
                        files.append(file_info)

        except Exception as e:
            pass

        return files

    def transfer_multiple_shares(self, share_configs, progress_callback=None):
        """
        批量转存多个分享链接
        Args:
            share_configs: 分享配置列表，每个配置包含:
                {
                    'share_url': str,      # 分享链接
                    'pwd': str,            # 提取码（可选）
                    'save_dir': str,       # 保存目录（可选）
                    'regex_pattern': str,  # 正则表达式（可选）
                    'regex_replace': str   # 正则替换（可选）
                }
            progress_callback: 进度回调函数
        Returns:
            dict: {
                'success': bool,          # 是否有成功的转存
                'total_count': int,       # 总链接数
                'success_count': int,     # 成功转存的链接数
                'failed_count': int,      # 失败的链接数
                'skipped_count': int,     # 跳过的链接数（无新文件）
                'results': list,          # 每个链接的详细结果
                'summary': str            # 总结信息
            }
        """
        with ErrorCollector("批量转存多个分享链接", self.wechat_notifier, None) as ec:
            if not share_configs or not isinstance(share_configs, list):
                error_msg = "分享配置列表不能为空或格式错误"
                # 收集错误
                collect_error(ValueError(error_msg), "分享配置列表验证失败")
                # 统一错误处理
                handle_error_and_notify(
                    ValueError(error_msg),
                    "批量转存配置错误",
                    self.wechat_notifier,
                    None,
                    collect=True,
                )
                return {
                    "success": False,
                    "error": error_msg,
                    "total_count": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "skipped_count": 0,
                    "results": [],
                }

            total_count = len(share_configs)
            success_count = 0
            failed_count = 0
            skipped_count = 0
            results = []

            for index, config in enumerate(share_configs, 1):
                try:
                    # 验证配置
                    if not isinstance(config, dict) or "share_url" not in config:
                        error_msg = f"第 {index} 个配置格式错误：缺少分享链接"
                        results.append(
                            {
                                "index": index,
                                "share_url": config.get("share_url", "未知"),
                                "success": False,
                                "error": error_msg,
                            }
                        )
                        failed_count += 1
                        # 收集错误
                        collect_error(
                            ValueError(error_msg), f"第 {index} 个配置格式错误"
                        )
                        # 统一错误处理
                        handle_error_and_notify(
                            ValueError(error_msg),
                            "批量转存配置错误",
                            self.wechat_notifier,
                            None,
                            collect=True,
                        )
                        continue

                    share_url = config["share_url"]
                    pwd = config.get("pwd")
                    save_dir = config.get("save_dir")
                    regex_pattern = config.get("regex_pattern")
                    regex_replace = config.get("regex_replace")

                    if progress_callback:
                        progress_callback(
                            "info",
                            f"【{index}/{total_count}】处理分享链接: {share_url}",
                        )

                    # 调用单个转存方法
                    result = self.transfer_share(
                        share_url=share_url,
                        pwd=pwd,
                        save_dir=save_dir,
                        progress_callback=progress_callback,
                        regex_pattern=regex_pattern,
                        regex_replace=regex_replace,
                    )

                    # 记录结果
                    result_record = {
                        "index": index,
                        "share_url": share_url,
                        "save_dir": save_dir,
                        "success": result.get("success", False),
                    }

                    if result.get("success"):
                        if result.get("skipped"):
                            # 跳过（无新文件）
                            skipped_count += 1
                            result_record["skipped"] = True
                            result_record["message"] = result.get(
                                "message", "没有新文件需要转存"
                            )
                            if progress_callback:
                                progress_callback(
                                    "info",
                                    f'【{index}/{total_count}】跳过: {result.get("message")}',
                                )
                        else:
                            # 成功
                            success_count += 1
                            result_record["message"] = result.get("message", "转存成功")
                            result_record["transferred_files"] = result.get(
                                "transferred_files", []
                            )
                            if progress_callback:
                                progress_callback(
                                    "success",
                                    f'【{index}/{total_count}】成功: {result.get("message")}',
                                )
                    else:
                        # 失败
                        failed_count += 1
                        result_record["error"] = result.get("error", "未知错误")
                        if progress_callback:
                            progress_callback(
                                "error",
                                f'【{index}/{total_count}】失败: {result.get("error")}',
                            )
                        # 收集错误
                        collect_error(
                            Exception(result.get("error", "未知错误")),
                            f"第 {index} 个链接转存失败",
                        )
                        # 发送微信告警
                        if self.wechat_notifier:
                            error_msg = result.get("error", "未知错误")
                            detailed_error = f"批量转存中单个链接失败\n分享链接: {share_url}\n保存目录: {save_dir}\n错误信息: {error_msg}"
                            # 聚合策略：仅收集，不即时发送
                            handle_error_and_notify(
                                ValueError(detailed_error),
                                "批量转存单个链接失败",
                                self.wechat_notifier,
                                None,
                                collect=True,
                            )

                    results.append(result_record)

                    # 链接间添加延迟，避免API限制
                    if index < total_count:
                        time.sleep(2)

                except Exception as e:
                    error_msg = f"处理第 {index} 个分享链接时发生异常: {str(e)}"
                    results.append(
                        {
                            "index": index,
                            "share_url": config.get("share_url", "未知"),
                            "success": False,
                            "error": error_msg,
                        }
                    )
                    failed_count += 1
                    if progress_callback:
                        progress_callback(
                            "error", f"【{index}/{total_count}】异常: {str(e)}"
                        )
                    # 收集错误
                    collect_error(e, f"处理第 {index} 个分享链接时发生异常")
                    # 打印详细的错误信息
                    print_detailed_error(
                        e,
                        f"处理第 {index} 个分享链接时发生异常\n分享链接: {config.get('share_url', '未知')}",
                        self.wechat_notifier,
                        None,
                    )

            # 生成总结信息
            summary_parts = []
            if success_count > 0:
                summary_parts.append(f"成功 {success_count} 个")
            if skipped_count > 0:
                summary_parts.append(f"跳过 {skipped_count} 个")
            if failed_count > 0:
                summary_parts.append(f"失败 {failed_count} 个")

            summary = f"批量转存完成：共 {total_count} 个链接，" + "、".join(
                summary_parts
            )

            if progress_callback:
                if success_count > 0 or skipped_count > 0:
                    progress_callback("success", summary)
                else:
                    progress_callback("error", summary)

            return {
                "success": success_count > 0 or skipped_count > 0,
                "skipped": skipped_count > 0
                and success_count == 0,  # 只有在只有跳过没有成功时才设置为skipped
                "total_count": total_count,
                "success_count": success_count,
                "failed_count": failed_count,
                "skipped_count": skipped_count,
                "results": results,
                "summary": summary,
                "message": summary,  # 为兼容性添加message字段
            }

    def parse_share_links_from_text(self, text, default_save_dir=None):
        """
        解析分享链接，支持以下格式：
        - https://pan.baidu.com/s/xxxxxx?pwd=abcd
        - https://pan.baidu.com/s/xxxxxx 以及 同行/下一行 指定提取码与保存目录
          示例：
            https://pan.baidu.com/s/1abcDefGh
            提取码: abcd /保存目录/子目录
        Args:
            text: 包含分享链接的文本
            default_save_dir: 默认保存目录（当链接后没有指定目录时使用）
        Returns:
            list: 分享配置列表
        """
        try:
            share_configs = []

            # 允许可选的 ?pwd=xxxx
            url_pattern = (
                r"https://pan\.baidu\.com/s/[A-Za-z0-9_-]+"  # 不强制要求 ?pwd=
            )
            pwd_inline_pattern = r"(?:\bpwd\b|密码|提取码)[:：]?\s*([A-Za-z0-9]{4})"

            lines = text.strip().split("\n") if text else []

            for line_idx, raw_line in enumerate(lines):
                line = raw_line.strip()
                if not line:
                    continue

                m = re.search(url_pattern, line)
                if not m:
                    continue

                share_url = m.group(0)
                pwd = None
                save_dir = None

                # 1) URL 内自带 ?pwd=xxxx（优先识别）
                if "?pwd=" in line[m.start() :]:
                    try:
                        _, pwd_part = line[m.start() :].split("?pwd=", 1)
                        pwd = pwd_part[:4]
                    except Exception:
                        pwd = None

                # 2) 同行剩余文本里查找“pwd/提取码/密码”
                if not pwd:
                    remain = line[m.end() :]
                    mm = re.search(pwd_inline_pattern, remain, flags=re.IGNORECASE)
                    if mm:
                        pwd = mm.group(1)

                # 3) 下一行里查找密码与保存目录（若下一行不是另一个 URL）
                next_line = (
                    lines[line_idx + 1].strip() if line_idx + 1 < len(lines) else ""
                )
                if not re.search(url_pattern, next_line):
                    if not pwd and next_line:
                        mm2 = re.search(
                            pwd_inline_pattern, next_line, flags=re.IGNORECASE
                        )
                        if mm2:
                            pwd = mm2.group(1)

                # 保存目录：优先同行 URL 之后第一个以 / 开头的 token；否则看下一行
                remain_after_url = line[m.end() :].strip()
                if remain_after_url:
                    tokens = remain_after_url.split()
                    for t in tokens:
                        if t.startswith("/"):
                            save_dir = t
                            break
                if not save_dir and next_line and not re.search(url_pattern, next_line):
                    tokens2 = next_line.split()
                    for t in tokens2:
                        if t.startswith("/"):
                            save_dir = t
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
        except Exception:
            return []

    def transfer_shares_from_text(
        self, text, default_save_dir=None, progress_callback=None
    ):
        """
        从文本中解析并批量转存分享链接
        只支持 https://pan.baidu.com/s/xxxxx?pwd=xxxx 格式
        Args:
            text: 包含分享链接的文本
            default_save_dir: 默认保存目录
            progress_callback: 进度回调函数
        Returns:
            dict: 批量转存结果
        """
        with ErrorCollector(
            "从文本中解析并批量转存分享链接", self.wechat_notifier, None
        ) as ec:
            try:
                if progress_callback:
                    progress_callback("info", "解析文本中的分享链接...")

                # 解析分享链接
                share_configs = self.parse_share_links_from_text(text, default_save_dir)

                if not share_configs:
                    error_msg = "文本中未找到有效的分享链接，请确保使用 https://pan.baidu.com/s/xxxxx?pwd=xxxx 格式"
                    if progress_callback:
                        progress_callback("warning", error_msg)
                    # 收集错误
                    ec.capture(ValueError(error_msg), "解析分享链接失败")
                    # 统一错误处理
                    handle_error_and_notify(
                        ValueError(error_msg),
                        "解析分享链接失败",
                        self.wechat_notifier,
                        None,
                        collect=True,
                    )
                    return {
                        "success": False,
                        "error": error_msg,
                        "total_count": 0,
                        "success_count": 0,
                        "failed_count": 0,
                        "skipped_count": 0,
                        "results": [],
                    }

                if progress_callback:
                    progress_callback(
                        "success", f"解析完成，找到 {len(share_configs)} 个分享链接"
                    )

                # 执行批量转存
                return self.transfer_multiple_shares(share_configs, progress_callback)

            except Exception as e:
                error_msg = f"从文本转存失败: {str(e)}"
                if progress_callback:
                    progress_callback("error", error_msg)
                # 收集错误
                ec.capture(e, "从文本转存失败")
                # 打印详细的错误信息
                print_detailed_error(e, "从文本转存失败", self.wechat_notifier, None)
                return {
                    "success": False,
                    "error": error_msg,
                    "total_count": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "skipped_count": 0,
                    "results": [],
                }

    def _send_error_and_return(
        self, error_msg, share_url=None, save_dir=None, error_obj=None, context=""
    ):
        """
        发送错误信息并返回错误结果

        Args:
            error_msg: 错误消息
            share_url: 分享链接
            save_dir: 保存目录
            error_obj: 错误对象
            context: 错误上下文

        Returns:
            dict: 错误结果
        """
        # 收集错误
        if error_obj:
            collect_error(error_obj, context)

        # 发送微信告警
        if self.wechat_notifier:
            full_error_msg = error_msg
            if share_url:
                full_error_msg += f"\n分享链接: {share_url}"
            if save_dir:
                full_error_msg += f"\n保存目录: {save_dir}"
            # 聚合策略：仅收集，延迟到结尾统一发送
            handle_error_and_notify(
                ValueError(full_error_msg),
                "转存失败",
                self.wechat_notifier,
                None,
                collect=True,
            )

        return {"success": False, "error": error_msg}

    def transfer_share(
        self,
        share_url,
        pwd=None,
        save_dir=None,
        progress_callback=None,
        regex_pattern=None,
        regex_replace=None,
    ):
        """转存分享文件
        Args:
            share_url: 分享链接
            pwd: 提取码
            save_dir: 保存目录
            progress_callback: 进度回调函数
            regex_pattern: 正则表达式模式（用于文件过滤和重命名）
            regex_replace: 正则替换字符串
        Returns:
            dict: {
                'success': bool,  # 是否成功
                'message': str,   # 成功时的消息
                'error': str,     # 失败时的错误信息
                'skipped': bool,  # 是否跳过（没有新文件）
                'transferred_files': list  # 成功转存的文件列表
            }
        """
        # 检查客户端是否可用
        if not self.client:
            error_msg = "客户端未初始化或初始化失败"
            return self._send_error_and_return(
                error_msg,
                share_url,
                save_dir,
                ValueError(error_msg),
                "转存分享文件: 客户端不可用",
            )

        with ErrorCollector(
            f"转存分享文件: {share_url}", self.wechat_notifier, None
        ) as ec:

            # 规范化保存路径
            if save_dir and not save_dir.startswith("/"):
                save_dir = "/" + save_dir

            # 步骤1：访问分享链接并获取文件列表
            if progress_callback:
                progress_callback("info", f"【步骤1/4】访问分享链接: {share_url}")

            try:
                # 访问分享链接
                if pwd:
                    if progress_callback:
                        progress_callback("info", f"使用密码访问分享链接")

                # 使用重试机制访问分享链接
                self._retry_on_network_error(self.client.access_shared, share_url, pwd)
                if progress_callback:
                    progress_callback("info", "开始获取共享文件文件列表")
                # 步骤1.1：获取分享文件列表并记录
                shared_paths = self._retry_on_network_error(
                    self.client.shared_paths, shared_url=share_url
                )
                if not shared_paths:
                    return self._send_error_and_return(
                        "获取分享文件列表失败",
                        share_url,
                        None,
                        None,
                        "获取分享文件列表失败",
                    )

                # 记录分享文件信息

                # 获取分享信息
                uk = shared_paths[0].uk
                share_id = shared_paths[0].share_id
                bdstoken = shared_paths[0].bdstoken

                # 记录共享文件详情
                shared_files_info = []
                for path in shared_paths:
                    if path.is_dir:
                        # 获取文件夹内容
                        folder_files = self._list_shared_dir_files(
                            path, uk, share_id, bdstoken
                        )
                        for file_info in folder_files:
                            shared_files_info.append(file_info)
                    else:
                        shared_files_info.append(
                            {
                                "server_filename": os.path.basename(path.path),
                                "fs_id": path.fs_id,
                                "path": path.path,
                                "size": path.size,
                                "isdir": 0,
                            }
                        )

                if progress_callback:
                    progress_callback(
                        "info", f"获取到 {len(shared_files_info)} 个共享文件"
                    )

                # 步骤2：扫描本地目录中的文件
                if progress_callback:
                    progress_callback("info", f"【步骤2/4】扫描本地目录: {save_dir}")

                # 获取本地文件列表
                local_files = []
                if save_dir:
                    local_files = self.list_local_files(save_dir)
                    if progress_callback:
                        progress_callback(
                            "info",
                            f"本地目录中有 {len(local_files)} 个文件（按相对路径统计）",
                        )

                # 提取所有文件名（只取文件名部分）
                file_names = [
                    self._normalize_path(f["file_name"], file_only=True)
                    for f in local_files
                ]

                # 统计重复文件名
                name_counts = Counter(file_names)
                dup_names = [name for name, count in name_counts.items() if count > 1]

                if dup_names:
                    print(f"⚠️ 检测到 {len(dup_names)} 个重复文件名：")
                    for name in dup_names:
                        print(f"  - {name} 出现 {name_counts[name]} 次")
                else:
                    print("✅ 没有发现重复文件名。")

                local_files_dict = {
                    self._normalize_path(f["file_name"], file_only=True): f["md5"]
                    for f in local_files
                }
                # 步骤3：准备转存（对比文件、准备目录）
                target_dir = save_dir
                is_single_folder = len(shared_paths) == 1 and shared_paths[0].is_dir

                if progress_callback:
                    progress_callback(
                        "info", f"【步骤3/4】准备转存: 对比文件和准备目录"
                    )

                # 步骤3.1：对比文件，确定需要转存的文件
                transfer_list = (
                    []
                )  # 存储(fs_id, dir_path, clean_path, final_path, need_rename)元组

                # 使用之前收集的共享文件信息进行对比
                for file_info in shared_files_info:
                    clean_path = file_info["path"]
                    if is_single_folder and "/" in clean_path:
                        clean_path = "/".join(clean_path.split("/")[1:])

                    # 应用正则规则
                    should_transfer = True
                    final_path = clean_path

                    if regex_pattern:
                        should_transfer, final_path = self._apply_regex_rules(
                            clean_path, regex_pattern, regex_replace
                        )
                        if not should_transfer:
                            if progress_callback:
                                progress_callback(
                                    "info", f"文件被正则过滤掉: {clean_path}"
                                )
                            continue

                    # 去重检查逻辑：使用相对路径去重，避免不同子目录同名误判
                    clean_normalized = self._normalize_path(
                        clean_path.lstrip("/"), file_only=True
                    )
                    final_normalized = self._normalize_path(
                        final_path.lstrip("/"), file_only=True
                    )
                    # 检查原文件是否存在
                    original_exists = clean_normalized in local_files_dict.keys()
                    # 检查重命名后文件是否存在
                    final_exists = final_normalized in local_files_dict.keys()
                    # 检查文件是否已存在（对比相对路径）
                    if original_exists or final_exists:
                        src_md5 = (
                            file_info.get("md5")
                            if isinstance(file_info, dict)
                            else None
                        )
                        if src_md5:
                            # 可获取 md5 时：与目标同路径文件的 md5 对比再决定是否跳过
                            try:
                                dest_md5 = local_files_dict[clean_normalized]
                            except Exception:
                                dest_md5 = None
                                if progress_callback:
                                    progress_callback(
                                        "info",
                                        f"文件已存在，无法获取目标文件 MD5，跳过: {final_path}",
                                    )
                                continue
                            if dest_md5 and dest_md5 == src_md5:
                                if progress_callback:
                                    progress_callback(
                                        "info",
                                        f"文件已存在且内容相同（MD5 相同），跳过: {final_path}",
                                    )
                                continue
                            else:
                                if progress_callback:
                                    progress_callback(
                                        "warning",
                                        f"同路径已存在,但内容不同(md5不同),跳过： {final_path}",
                                    )
                                continue
                                # 不 continue，后续加入 transfer_list
                        else:
                            # 无法获取源 MD5：保持原有策略，按路径命中直接跳过
                            if progress_callback:
                                progress_callback(
                                    "info",
                                    f"文件已存在（无MD5校验），跳过: {final_path}",
                                )
                            continue

                    # 转存到原始路径的目录
                    if target_dir is not None and clean_path is not None:
                        target_path = posixpath.join(target_dir, clean_path)
                        dir_path = posixpath.dirname(target_path).replace("\\", "/")
                        need_rename = final_path != clean_path
                        transfer_list.append(
                            (
                                file_info["fs_id"],
                                dir_path,
                                clean_path,
                                final_path,
                                need_rename,
                            )
                        )

                        # 日志显示重命名信息
                        if need_rename:
                            if progress_callback:
                                progress_callback(
                                    "info",
                                    f"需要转存文件: {clean_path} -> {final_path}",
                                )
                        else:
                            if progress_callback:
                                progress_callback("info", f"需要转存文件: {final_path}")

                # 检查是否有需要转存的文件
                if not transfer_list:
                    if progress_callback:
                        progress_callback("info", "没有找到需要处理的文件")
                    return {
                        "success": True,
                        "skipped": True,
                        "message": "没有新文件需要转存",
                    }

                if progress_callback:
                    progress_callback(
                        "info", f"找到 {len(transfer_list)} 个新文件需要转存"
                    )

                # 步骤3.2：创建所有必要的目录
                created_dirs = set()
                for _, dir_path, _, _, _ in transfer_list:
                    if dir_path not in created_dirs:
                        if not self._ensure_dir_exists(dir_path):
                            return self._send_error_and_return(
                                f"创建目录失败: {dir_path}",
                                share_url,
                                save_dir,
                                None,
                                f"创建目录失败: {dir_path}",
                            )
                        created_dirs.add(dir_path)

                # 步骤4：执行文件转存
                if progress_callback:
                    progress_callback(
                        "info",
                        f"【步骤4/4】开始执行转存操作，共 {len(transfer_list)} 个文件",
                    )

                # 按目录分组进行转存
                success_count = 0
                grouped_transfers = {}
                for fs_id, dir_path, _, _, _ in transfer_list:
                    grouped_transfers.setdefault(dir_path, []).append(fs_id)

                total_files = len(transfer_list)

                # 对每个目录进行批量转存
                for dir_path, fs_ids in grouped_transfers.items():
                    # 确保目录路径使用正斜杠
                    dir_path = dir_path.replace("\\", "/")
                    if progress_callback:
                        progress_callback(
                            "info", f"转存到目录 {dir_path} ({len(fs_ids)} 个文件)"
                        )

                    try:
                        # 确保客户端和参数都有效
                        if (
                            self.client
                            and uk is not None
                            and share_id is not None
                            and bdstoken is not None
                        ):
                            # 使用重试机制执行转存
                            self._retry_on_network_error(
                                self.client.transfer_shared_paths,
                                remotedir=dir_path,
                                fs_ids=fs_ids,
                                uk=int(uk),
                                share_id=int(share_id),
                                bdstoken=str(bdstoken),
                                shared_url=share_url,
                            )
                        else:
                            error_msg = "转存失败: 客户端或参数无效"
                            raise ValueError(error_msg)
                        success_count += len(fs_ids)
                        if progress_callback:
                            progress_callback("success", f"成功转存到 {dir_path}")
                    except Exception as e:
                        if "error_code: -65" in str(e):  # 频率限制
                            if progress_callback:
                                progress_callback(
                                    "warning", "触发频率限制，等待10秒后重试..."
                                )
                            time.sleep(10)
                            try:
                                # 使用重试机制重试转存
                                if (
                                    self.client
                                    and uk is not None
                                    and share_id is not None
                                    and bdstoken is not None
                                ):
                                    self._retry_on_network_error(
                                        self.client.transfer_shared_paths,
                                        remotedir=dir_path,
                                        fs_ids=fs_ids,
                                        uk=int(uk),
                                        share_id=int(share_id),
                                        bdstoken=str(bdstoken),
                                        shared_url=share_url,
                                    )
                                else:
                                    error_msg = "重试转存失败: 客户端或参数无效"
                                    raise ValueError(error_msg)
                                success_count += len(fs_ids)
                                if progress_callback:
                                    progress_callback(
                                        "success", f"重试成功: {dir_path}"
                                    )
                            except Exception as retry_e:
                                error_msg = f"转存失败: {dir_path} - {str(retry_e)}"
                                if progress_callback:
                                    progress_callback("error", error_msg)
                                # 收集错误
                                collect_error(retry_e, f"转存失败: {dir_path}")
                                # 发送微信告警
                                if self.wechat_notifier:
                                    print_detailed_error(
                                        retry_e,
                                        f"转存失败: {dir_path}",
                                        self.wechat_notifier,
                                        None,
                                    )
                                return {"success": False, "error": error_msg}
                        else:
                            error_msg = f"转存失败: {dir_path} - {str(e)}"
                            if progress_callback:
                                progress_callback("error", error_msg)
                            # 收集错误
                            collect_error(e, f"转存失败: {dir_path}")
                            # 发送微信告警
                            if self.wechat_notifier:
                                print_detailed_error(
                                    e,
                                    f"转存失败: {dir_path}",
                                    self.wechat_notifier,
                                    None,
                                )
                            return {"success": False, "error": error_msg}

                    time.sleep(1)  # 遍历避免频率限制

                # 步骤5：执行重命名操作（如果需要）
                renamed_files = []

                for (
                    fs_id,
                    dir_path,
                    clean_path,
                    final_path,
                    need_rename,
                ) in transfer_list:
                    if need_rename:
                        try:
                            # 构建转存后的完整路径（原始文件名）
                            original_full_path = posixpath.join(
                                dir_path, os.path.basename(clean_path)
                            )
                            # 构建重命名后的完整路径
                            final_full_path = posixpath.join(
                                dir_path, os.path.basename(final_path)
                            )

                            if progress_callback:
                                progress_callback(
                                    "info",
                                    f"重命名文件: {os.path.basename(clean_path)} -> {os.path.basename(final_path)}",
                                )

                            # 使用baidupcs-py的rename方法（需要完整路径）
                            self.client.rename(original_full_path, final_full_path)

                            renamed_files.append(final_path)

                            # 添加延迟避免API频率限制
                            time.sleep(0.5)

                        except Exception as e:
                            # 重命名失败时使用原文件名
                            error_msg = f"重命名文件失败: {os.path.basename(clean_path)} -> {os.path.basename(final_path)}"
                            if progress_callback:
                                progress_callback("error", f"{error_msg}: {str(e)}")
                            # 收集错误
                            collect_error(
                                e,
                                f"重命名文件失败\n原始文件: {os.path.basename(clean_path)}\n目标文件: {os.path.basename(final_path)}",
                            )
                            # 发送微信告警
                            if self.wechat_notifier:
                                print_detailed_error(
                                    e,
                                    f"重命名文件失败\n原始文件: {os.path.basename(clean_path)}\n目标文件: {os.path.basename(final_path)}",
                                    self.wechat_notifier,
                                    None,
                                )
                            renamed_files.append(clean_path)
                    else:
                        renamed_files.append(final_path)

                # 转存结果汇总

                # 根据转存结果返回不同状态
                if success_count == total_files:  # 全部成功
                    if progress_callback:
                        progress_callback(
                            "success",
                            f"转存完成，成功转存 {success_count}/{total_files} 个文件",
                        )
                    return {
                        "success": True,
                        "message": f"成功转存 {success_count}/{total_files} 个文件",
                        "transferred_files": renamed_files,
                    }
                elif success_count > 0:  # 部分成功
                    if progress_callback:
                        progress_callback(
                            "warning",
                            f"部分转存成功，成功转存 {success_count}/{total_files} 个文件",
                        )
                    return {
                        "success": True,
                        "message": f"部分转存成功，成功转存 {success_count}/{total_files} 个文件",
                        "transferred_files": renamed_files[:success_count],
                    }
                else:  # 全部失败
                    return self._send_error_and_return(
                        "转存失败，没有文件成功转存",
                        share_url,
                        save_dir,
                        None,
                        "转存失败，没有文件成功转存",
                    )

            except Exception as e:
                error_msg = str(e)
                # 使用新的错误解析函数
                parsed_error = self._parse_share_error(error_msg)
                # 收集错误
                collect_error(e, f"转存分享链接时发生异常\n分享链接: {share_url}")
                # 打印详细的错误信息
                print_detailed_error(
                    e,
                    f"转存分享链接时发生异常\n分享链接: {share_url}",
                    self.wechat_notifier,
                    None,
                )
                # 仅收集，返回错误由上层汇总处理
                return {"success": False, "error": parsed_error}

    def get_share_folder_name(self, share_url, pwd=None):
        """获取分享链接的主文件夹名称"""
        try:
            # 检查客户端是否可用
            if not self.client:
                error_msg = "客户端未初始化或初始化失败"
                handle_error_and_notify(
                    ValueError(error_msg),
                    f"获取分享文件夹名称失败: 客户端不可用",
                    self.wechat_notifier,
                    None,
                    collect=True,
                )
                return {"success": False, "error": error_msg}

            # 访问分享链接
            if pwd:
                pass
            self.client.access_shared(share_url, pwd)

            # 获取分享文件列表
            shared_paths = self.client.shared_paths(shared_url=share_url)
            if not shared_paths:
                error_msg = "获取分享文件列表失败"
                # 统一错误处理
                handle_error_and_notify(
                    ValueError(error_msg),
                    f"获取分享文件列表失败\n分享链接: {share_url}",
                    self.wechat_notifier,
                    None,
                    collect=True,
                )
                return {"success": False, "error": error_msg}

            # 获取主文件夹名称
            if (
                len(shared_paths) == 1
                and hasattr(shared_paths[0], "is_dir")
                and shared_paths[0].is_dir
            ):
                # 如果只有一个文件夹，使用该文件夹名称
                folder_name = os.path.basename(shared_paths[0].path)
                return {"success": True, "folder_name": folder_name}
            else:
                # 如果有多个文件或不是文件夹，使用分享链接的默认名称或第一个项目的名称
                if shared_paths:
                    first_item = shared_paths[0]
                    if hasattr(first_item, "is_dir") and first_item.is_dir:
                        folder_name = os.path.basename(first_item.path)
                    else:
                        # 如果第一个是文件，尝试获取文件名（去掉扩展名）
                        folder_name = os.path.splitext(
                            os.path.basename(first_item.path)
                        )[0]
                    return {"success": True, "folder_name": folder_name}
                else:
                    error_msg = "分享内容为空"
                    # 统一错误处理
                    handle_error_and_notify(
                        ValueError(error_msg),
                        f"分享内容为空\n分享链接: {share_url}",
                        self.wechat_notifier,
                        None,
                        collect=True,
                    )
                    return {"success": False, "error": error_msg}

        except Exception as e:
            # 使用统一的错误处理函数
            handle_error_and_notify(
                e,
                f"获取分享文件夹名称时发生异常\n分享链接: {share_url}",
                self.wechat_notifier,
                None,
                collect=True,
            )
            return {"success": False, "error": str(e)}
