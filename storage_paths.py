#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

from storage_errors import (
    is_already_exists_error,
    is_invalid_name_error,
    is_missing_path_error,
)
from utils import handle_error_and_notify


class StoragePathService:
    def __init__(self, client, wechat_notifier=None, local_files_cache=None):
        self.client = client
        self.wechat_notifier = wechat_notifier
        self._local_files_cache = local_files_cache if local_files_cache is not None else {}

    @staticmethod
    def normalize_path(path, file_only=False):
        try:
            path = path.replace("\\", "/").strip("/")
            if file_only:
                return path.split("/")[-1]
            if not path.startswith("/"):
                path = "/" + path
            return path
        except Exception:
            return path

    def ensure_dir_exists(self, path):
        try:
            if not self.client:
                handle_error_and_notify(
                    ValueError("客户端未初始化或初始化失败"),
                    "创建目录失败: 客户端不可用",
                    self.wechat_notifier,
                    None,
                    collect=True,
                )
                return False

            path = self.normalize_path(path)
            if path in ("", "/"):
                return True

            parts = [p for p in path.strip("/").split("/") if p]
            prefixes = []
            curr = ""
            for part in parts:
                curr = f"{curr}/{part}" if curr else f"/{part}"
                prefixes.append(curr)

            for seg in prefixes:
                try:
                    self.client.makedir(seg)
                except Exception as exc:
                    if is_already_exists_error(exc):
                        continue
                    if is_invalid_name_error(exc):
                        handle_error_and_notify(
                            ValueError(f"创建目录失败，文件名非法: {seg}"),
                            "创建目录失败: 文件名非法",
                            self.wechat_notifier,
                            None,
                            collect=True,
                        )
                        return False
                    try:
                        self.client.list(seg)
                        continue
                    except Exception:
                        handle_error_and_notify(
                            exc,
                            f"创建目录出错\n目录路径: {seg}",
                            self.wechat_notifier,
                            None,
                            collect=True,
                        )
                        return False

            return True
        except Exception as exc:
            handle_error_and_notify(
                exc,
                f"确保目录存在时发生异常\n目录路径: {path}",
                self.wechat_notifier,
                None,
                collect=True,
            )
            return False

    def list_local_files(self, dir_path, use_cache=False):
        normalized_dir_path = self.normalize_path(dir_path)
        if use_cache and normalized_dir_path in self._local_files_cache:
            return [dict(item) for item in self._local_files_cache[normalized_dir_path]]

        try:
            if not self.client:
                handle_error_and_notify(
                    ValueError("客户端未初始化或初始化失败"),
                    "获取本地文件列表失败: 客户端不可用",
                    self.wechat_notifier,
                    None,
                    collect=False,
                )
                return []

            files = []
            base = normalized_dir_path.replace("\\", "/")
            if not base.endswith("/"):
                base += "/"

            def _list_dir(path):
                try:
                    content = self.client.list(path)
                    for item in content:
                        if item.is_file:
                            item_path = getattr(item, "path", "").replace("\\", "/")
                            if item_path.startswith(base):
                                relative_path = item_path[len(base) :]
                            else:
                                relative_path = item_path.lstrip("/")
                            files.append(
                                {
                                    "relative_path": relative_path,
                                    "file_name": os.path.basename(item_path),
                                    "md5": getattr(item, "md5", None),
                                }
                            )
                        elif item.is_dir:
                            _list_dir(item.path)
                except Exception as exc:
                    if path == normalized_dir_path and is_missing_path_error(exc):
                        return
                    handle_error_and_notify(
                        exc,
                        f"列出目录内容时发生错误\n目录路径: {path}",
                        self.wechat_notifier,
                        None,
                        collect=False,
                    )
                    raise

            _list_dir(normalized_dir_path)
            if use_cache:
                self._local_files_cache[normalized_dir_path] = [dict(item) for item in files]
            return files
        except Exception as exc:
            handle_error_and_notify(
                exc,
                f"获取本地文件列表时发生异常\n目录路径: {dir_path}",
                self.wechat_notifier,
                None,
                collect=False,
            )
            return []

