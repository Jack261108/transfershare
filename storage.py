#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from collections import Counter

import os
import time
import posixpath

# 添加 WeChatNotifier 和工具方法导入
from wechat_notifier import WeChatNotifier
from utils import handle_error_and_notify, ErrorCollector
from config_utils import parse_share_links_from_text
from storage_client import BaiduClientAdapter
from storage_errors import classify_storage_error, is_rate_limit_error, parse_share_error
from storage_paths import StoragePathService
from storage_rules import apply_regex_rules
from storage_shares import SharedPathService

try:
    from logger import get_logger
except ImportError:
    # 日志模块不可用时，使用标准日志
    import logging

    def get_logger(name="transfershare"):
        return logging.getLogger(name)


# 常量定义
RATE_LIMIT_WAIT_TIME = 10
FREQUENCY_LIMIT_DELAY = 1
RENAME_DELAY = 0.5


class BaiduStorage:
    def __init__(self, cookies, wechat_webhook=None):
        self.wechat_notifier = (
            WeChatNotifier(wechat_webhook) if wechat_webhook else None
        )
        self._local_files_cache = {}
        self.client = BaiduClientAdapter(cookies)
        self.path_service = StoragePathService(
            self.client, self.wechat_notifier, self._local_files_cache
        )
        self.share_service = SharedPathService(self.client, self.wechat_notifier)

    def set_notifier(self, notifier):
        """设置微信通知器实例

        Args:
            notifier: WeChatNotifier 实例或 None
        """
        self.wechat_notifier = notifier
        self.path_service.wechat_notifier = notifier
        self.share_service.wechat_notifier = notifier

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

            quota_info = self.get_quota_info()
            return bool(quota_info)

        except Exception as e:
            handle_error_and_notify(
                e, "检查存储可用性时发生异常", self.wechat_notifier, None, collect=False
            )
            return False

    def _build_invalid_share_result(self, index, config):
        error_msg = f"第 {index} 个配置格式错误：缺少分享链接"
        invalid_share_url = (
            config.get("share_url", "未知") if isinstance(config, dict) else str(config)
        )
        handle_error_and_notify(
            ValueError(error_msg),
            f"批量转存配置错误: 第 {index} 个配置格式错误",
            self.wechat_notifier,
            None,
            collect=True,
        )
        return {
            "index": index,
            "share_url": invalid_share_url,
            "success": False,
            "error": error_msg,
        }

    def _notify_batch_progress(self, level, index, total_count, message, progress_callback):
        if progress_callback:
            progress_callback(level, f"【{index}/{total_count}】{message}")

    def _build_result_record(self, index, share_url, save_dir, result):
        record = {
            "index": index,
            "share_url": share_url,
            "save_dir": save_dir,
            "success": result.get("success", False),
        }
        if result.get("success"):
            if result.get("skipped"):
                record["skipped"] = True
                record["message"] = result.get("message", "没有新文件需要转存")
            else:
                record["message"] = result.get("message", "转存成功")
                record["transferred_files"] = result.get("transferred_files", [])
        else:
            record["error"] = result.get("error", "未知错误")
        return record

    def _record_batch_result(self, counters, result_record):
        if result_record.get("success"):
            if result_record.get("skipped"):
                counters["skipped_count"] += 1
            else:
                counters["success_count"] += 1
        else:
            counters["failed_count"] += 1

    def _handle_batch_failure(self, index, share_url, save_dir, error_msg):
        detailed_error = (
            f"批量转存中单个链接失败\n分享链接: {share_url}\n保存目录: {save_dir}\n错误信息: {error_msg}"
        )
        handle_error_and_notify(
            ValueError(detailed_error),
            f"批量转存单个链接失败: 第 {index} 个链接",
            self.wechat_notifier,
            None,
            collect=True,
        )

    def _process_single_share_config(self, index, total_count, config, progress_callback=None):
        if not isinstance(config, dict) or "share_url" not in config:
            result_record = self._build_invalid_share_result(index, config)
            self._notify_batch_progress(
                "error", index, total_count, f"失败: {result_record['error']}", progress_callback
            )
            return result_record

        share_url = config["share_url"]
        pwd = config.get("pwd")
        save_dir = config.get("save_dir")
        regex_pattern = config.get("regex_pattern")
        regex_replace = config.get("regex_replace")
        folder_filter = config.get("folder_filter")

        self._notify_batch_progress(
            "info", index, total_count, f"处理分享链接: {share_url}", progress_callback
        )

        result = self.transfer_share(
            share_url=share_url,
            pwd=pwd,
            save_dir=save_dir,
            progress_callback=progress_callback,
            regex_pattern=regex_pattern,
            regex_replace=regex_replace,
            folder_filter=folder_filter,
        )
        result_record = self._build_result_record(index, share_url, save_dir, result)

        if result.get("success"):
            if result.get("skipped"):
                self._notify_batch_progress(
                    "info",
                    index,
                    total_count,
                    f"跳过: {result_record.get('message')}",
                    progress_callback,
                )
            else:
                self._notify_batch_progress(
                    "success",
                    index,
                    total_count,
                    f"成功: {result_record.get('message')}",
                    progress_callback,
                )
        else:
            error_msg = result_record.get("error", "未知错误")
            self._notify_batch_progress(
                "error", index, total_count, f"失败: {error_msg}", progress_callback
            )
            self._handle_batch_failure(index, share_url, save_dir, error_msg)

        return result_record

    def _build_batch_summary(self, total_count, success_count, failed_count, skipped_count):
        summary_parts = []
        if success_count > 0:
            summary_parts.append(f"成功 {success_count} 个")
        if skipped_count > 0:
            summary_parts.append(f"跳过 {skipped_count} 个")
        if failed_count > 0:
            summary_parts.append(f"失败 {failed_count} 个")
        return f"批量转存完成：共 {total_count} 个链接，" + "、".join(summary_parts)

    def transfer_multiple_shares(self, share_configs, progress_callback=None):
        """批量转存多个分享链接"""
        with ErrorCollector(
            "批量转存多个分享链接", self.wechat_notifier, None, auto_send=False
        ):
            if not share_configs or not isinstance(share_configs, list):
                error_msg = "分享配置列表不能为空或格式错误"
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

            self._local_files_cache.clear()
            total_count = len(share_configs)
            counters = {"success_count": 0, "failed_count": 0, "skipped_count": 0}
            results = []

            for index, config in enumerate(share_configs, 1):
                try:
                    result_record = self._process_single_share_config(
                        index, total_count, config, progress_callback
                    )
                    self._record_batch_result(counters, result_record)
                    results.append(result_record)
                    if index < total_count:
                        time.sleep(2)
                except Exception as e:
                    error_info = classify_storage_error(e)
                    error_msg = f"处理第 {index} 个分享链接时发生异常: {error_info.message}"
                    share_url = config.get("share_url", "未知") if isinstance(config, dict) else "未知"
                    results.append(
                        {
                            "index": index,
                            "share_url": share_url,
                            "success": False,
                            "error": error_msg,
                        }
                    )
                    counters["failed_count"] += 1
                    self._notify_batch_progress(
                        "error", index, total_count, f"异常: {error_info.message}", progress_callback
                    )
                    handle_error_and_notify(
                        e,
                        f"处理第 {index} 个分享链接时发生异常\n分享链接: {share_url}",
                        self.wechat_notifier,
                        None,
                        collect=True,
                    )

            summary = self._build_batch_summary(
                total_count,
                counters["success_count"],
                counters["failed_count"],
                counters["skipped_count"],
            )
            if progress_callback:
                if counters["success_count"] > 0 or counters["skipped_count"] > 0:
                    progress_callback("success", summary)
                else:
                    progress_callback("error", summary)

            return {
                "success": counters["success_count"] > 0 or counters["skipped_count"] > 0,
                "skipped": counters["skipped_count"] > 0 and counters["success_count"] == 0,
                "total_count": total_count,
                "success_count": counters["success_count"],
                "failed_count": counters["failed_count"],
                "skipped_count": counters["skipped_count"],
                "results": results,
                "summary": summary,
                "message": summary,
            }

    @staticmethod
    def parse_share_links_from_text(text, default_save_dir=None):
        """兼容旧调用方式，实际委托给共享配置工具。"""
        return parse_share_links_from_text(text, default_save_dir)

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
        ):
            try:
                if progress_callback:
                    progress_callback("info", "解析文本中的分享链接...")

                share_configs = parse_share_links_from_text(text, default_save_dir)

                if not share_configs:
                    error_msg = "文本中未找到有效的分享链接，请确保使用 https://pan.baidu.com/s/xxxxx?pwd=xxxx 格式"
                    if progress_callback:
                        progress_callback("warning", error_msg)
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

                return self.transfer_multiple_shares(share_configs, progress_callback)

            except Exception as e:
                error_info = classify_storage_error(e)
                error_msg = f"从文本转存失败: {error_info.message}"
                if progress_callback:
                    progress_callback("error", error_msg)
                handle_error_and_notify(
                    e,
                    "从文本转存失败",
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

    def _normalize_save_dir(self, save_dir):
        return self.path_service.normalize_path(save_dir) if save_dir else save_dir

    def _load_share_context(self, share_url, pwd, folder_filter, progress_callback=None):
        if progress_callback:
            progress_callback("info", f"【步骤1/4】访问分享链接: {share_url}")
        if pwd and progress_callback:
            progress_callback("info", "使用密码访问分享链接")

        shared_paths = self.share_service.load_shared_paths(share_url, pwd)
        if progress_callback:
            progress_callback("info", "开始获取共享文件文件列表")
        if not shared_paths:
            handle_error_and_notify(
                ValueError("获取分享文件列表失败"),
                "获取分享文件列表失败",
                self.wechat_notifier,
                None,
                collect=True,
            )
            return None

        uk = shared_paths[0].uk
        share_id = shared_paths[0].share_id
        bdstoken = shared_paths[0].bdstoken
        shared_files_info = self.share_service.list_shared_files(
            shared_paths, folder_filter
        )

        if progress_callback:
            progress_callback("info", f"获取到 {len(shared_files_info)} 个共享文件")

        return {
            "shared_paths": shared_paths,
            "shared_files_info": shared_files_info,
            "uk": uk,
            "share_id": share_id,
            "bdstoken": bdstoken,
        }

    def _scan_local_files_dict(self, save_dir, progress_callback=None):
        if progress_callback:
            progress_callback("info", f"【步骤2/4】扫描本地目录: {save_dir}")

        local_files = []
        if save_dir:
            local_files = self.path_service.list_local_files(save_dir, use_cache=True)
            if progress_callback:
                progress_callback(
                    "info",
                    f"本地目录中有 {len(local_files)} 个文件（按相对路径统计）",
                )

        file_names = [
            self.path_service.normalize_path(file_info["file_name"], file_only=True)
            for file_info in local_files
        ]
        name_counts = Counter(file_names)
        dup_names = [name for name, count in name_counts.items() if count > 1]

        logger = get_logger()
        if dup_names:
            logger.info(f"检测到 {len(dup_names)} 个重复文件名：")
            for name in dup_names:
                logger.info(f"  - {name} 出现 {name_counts[name]} 次")
        else:
            logger.info("没有发现重复文件名。")

        return {
            self.path_service.normalize_path(file_info["relative_path"]): file_info["md5"]
            for file_info in local_files
            if file_info.get("relative_path")
        }

    def _build_transfer_list(
        self,
        shared_files_info,
        shared_paths,
        target_dir,
        local_files_dict,
        regex_pattern=None,
        regex_replace=None,
        progress_callback=None,
    ):
        if progress_callback:
            progress_callback("info", "【步骤3/4】准备转存: 对比文件和准备目录")

        is_single_folder = len(shared_paths) == 1 and shared_paths[0].is_dir
        transfer_list = []

        for file_info in shared_files_info:
            clean_path = file_info["path"]
            if is_single_folder and "/" in clean_path:
                clean_path = "/".join(clean_path.split("/")[1:])

            should_transfer, final_path = apply_regex_rules(
                clean_path, regex_pattern, regex_replace
            )
            if not should_transfer:
                if progress_callback:
                    progress_callback("info", f"文件被正则过滤掉: {clean_path}")
                continue

            clean_normalized = self.path_service.normalize_path(clean_path.lstrip("/"))
            final_normalized = self.path_service.normalize_path(final_path.lstrip("/"))
            existing_paths = []
            if clean_normalized in local_files_dict:
                existing_paths.append(clean_normalized)
            if final_normalized in local_files_dict and final_normalized not in existing_paths:
                existing_paths.append(final_normalized)

            if existing_paths:
                src_md5 = file_info.get("md5") if isinstance(file_info, dict) else None
                if src_md5:
                    existing_md5s = [local_files_dict.get(path) for path in existing_paths]
                    if any(dest_md5 and dest_md5 == src_md5 for dest_md5 in existing_md5s):
                        if progress_callback:
                            progress_callback(
                                "info", f"文件已存在且内容相同（MD5 相同），跳过: {final_path}"
                            )
                        continue
                    if any(dest_md5 is None for dest_md5 in existing_md5s):
                        if progress_callback:
                            progress_callback(
                                "info", f"文件已存在，无法获取目标文件 MD5，跳过: {final_path}"
                            )
                        continue
                    if progress_callback:
                        progress_callback(
                            "warning", f"同路径已存在,但内容不同(md5不同),跳过： {final_path}"
                        )
                    continue
                if progress_callback:
                    progress_callback("info", f"文件已存在（无MD5校验），跳过: {final_path}")
                continue

            if target_dir is None or clean_path is None:
                continue

            target_path = posixpath.join(target_dir, clean_path)
            dir_path = posixpath.dirname(target_path).replace("\\", "/")
            need_rename = final_path != clean_path
            transfer_list.append(
                (file_info["fs_id"], dir_path, clean_path, final_path, need_rename)
            )

            if progress_callback:
                if need_rename:
                    progress_callback("info", f"需要转存文件: {clean_path} -> {final_path}")
                else:
                    progress_callback("info", f"需要转存文件: {final_path}")

        if progress_callback and transfer_list:
            progress_callback("info", f"找到 {len(transfer_list)} 个新文件需要转存")
        return transfer_list

    def _ensure_transfer_dirs(self, transfer_list):
        created_dirs = set()
        for _, dir_path, _, _, _ in transfer_list:
            if dir_path in created_dirs:
                continue
            if not self.path_service.ensure_dir_exists(dir_path):
                handle_error_and_notify(
                    ValueError(f"创建目录失败: {dir_path}"),
                    f"创建目录失败: {dir_path}",
                    self.wechat_notifier,
                    None,
                    collect=True,
                )
                return {"success": False, "error": f"创建目录失败: {dir_path}"}
            created_dirs.add(dir_path)
        return None

    def _transfer_group(
        self,
        dir_path,
        fs_ids,
        share_url,
        uk,
        share_id,
        bdstoken,
        progress_callback=None,
    ):
        dir_path = dir_path.replace("\\", "/")
        if progress_callback:
            progress_callback("info", f"转存到目录 {dir_path} ({len(fs_ids)} 个文件)")

        if not (self.client and uk is not None and share_id is not None and bdstoken is not None):
            raise ValueError("转存失败: 客户端或参数无效")

        self.client.transfer_shared_paths(
            remotedir=dir_path,
            fs_ids=fs_ids,
            uk=int(uk),
            share_id=int(share_id),
            bdstoken=str(bdstoken),
            shared_url=share_url,
        )
        return dir_path

    def _execute_transfer_plan(
        self,
        transfer_list,
        share_url,
        uk,
        share_id,
        bdstoken,
        target_dir,
        progress_callback=None,
    ):
        if progress_callback:
            progress_callback(
                "info", f"【步骤4/4】开始执行转存操作，共 {len(transfer_list)} 个文件"
            )

        grouped_transfers = {}
        grouped_transfer_items = {}
        for item in transfer_list:
            fs_id, dir_path, _, _, _ = item
            grouped_transfers.setdefault(dir_path, []).append(fs_id)
            grouped_transfer_items.setdefault(dir_path, []).append(item)

        success_count = 0
        successful_transfer_items = []
        for dir_path, fs_ids in grouped_transfers.items():
            try:
                normalized_dir_path = self._transfer_group(
                    dir_path,
                    fs_ids,
                    share_url,
                    uk,
                    share_id,
                    bdstoken,
                    progress_callback,
                )
                success_count += len(fs_ids)
                successful_transfer_items.extend(grouped_transfer_items.get(dir_path, []))
                if target_dir:
                    self._local_files_cache.pop(self.path_service.normalize_path(target_dir), None)
                if progress_callback:
                    progress_callback("success", f"成功转存到 {normalized_dir_path}")
            except Exception as e:
                if is_rate_limit_error(e):
                    if progress_callback:
                        progress_callback(
                            "warning", f"触发频率限制，等待{RATE_LIMIT_WAIT_TIME}秒后重试..."
                        )
                    time.sleep(RATE_LIMIT_WAIT_TIME)
                    try:
                        normalized_dir_path = self._transfer_group(
                            dir_path,
                            fs_ids,
                            share_url,
                            uk,
                            share_id,
                            bdstoken,
                            None,
                        )
                        success_count += len(fs_ids)
                        successful_transfer_items.extend(grouped_transfer_items.get(dir_path, []))
                        if target_dir:
                            self._local_files_cache.pop(self.path_service.normalize_path(target_dir), None)
                        if progress_callback:
                            progress_callback("success", f"重试成功: {normalized_dir_path}")
                    except Exception as retry_e:
                        retry_error = classify_storage_error(retry_e)
                        error_msg = f"转存失败: {dir_path} - {retry_error.message}"
                        if progress_callback:
                            progress_callback("error", error_msg)
                        handle_error_and_notify(
                            retry_e,
                            f"转存失败: {dir_path}",
                            self.wechat_notifier,
                            None,
                            collect=True,
                        )
                else:
                    error_info = classify_storage_error(e)
                    error_msg = f"转存失败: {dir_path} - {error_info.message}"
                    if progress_callback:
                        progress_callback("error", error_msg)
                    handle_error_and_notify(
                        e,
                        f"转存失败: {dir_path}",
                        self.wechat_notifier,
                        None,
                        collect=True,
                    )
            time.sleep(FREQUENCY_LIMIT_DELAY)

        return success_count, successful_transfer_items

    def _rename_transferred_files(self, successful_transfer_items, target_dir, progress_callback=None):
        renamed_files = []
        for _, dir_path, clean_path, final_path, need_rename in successful_transfer_items:
            if not need_rename:
                renamed_files.append(final_path)
                continue
            try:
                original_full_path = posixpath.join(target_dir, clean_path)
                final_full_path = posixpath.join(target_dir, final_path)
                final_parent_dir = posixpath.dirname(final_full_path).replace("\\", "/")

                if final_parent_dir and final_parent_dir != dir_path:
                    if not self.path_service.ensure_dir_exists(final_parent_dir):
                        raise ValueError(f"创建重命名目标目录失败: {final_parent_dir}")

                if progress_callback:
                    progress_callback("info", f"重命名文件: {clean_path} -> {final_path}")

                self.client.rename(original_full_path, final_full_path)
                renamed_files.append(final_path)
                time.sleep(RENAME_DELAY)
            except Exception as e:
                error_info = classify_storage_error(e)
                error_msg = (
                    f"重命名文件失败: {os.path.basename(clean_path)} -> {os.path.basename(final_path)}"
                )
                if progress_callback:
                    progress_callback("error", f"{error_msg}: {error_info.message}")
                handle_error_and_notify(
                    e,
                    f"重命名文件失败\n原始文件: {os.path.basename(clean_path)}\n目标文件: {os.path.basename(final_path)}",
                    self.wechat_notifier,
                    None,
                    collect=True,
                )
                renamed_files.append(clean_path)
        return renamed_files

    def _build_transfer_result(self, success_count, total_files, renamed_files, progress_callback=None):
        if success_count == total_files:
            message = f"成功转存 {success_count}/{total_files} 个文件"
            if progress_callback:
                progress_callback("success", f"转存完成，{message}")
            return {"success": True, "message": message, "transferred_files": renamed_files}

        if success_count > 0:
            message = f"部分转存成功，成功转存 {success_count}/{total_files} 个文件"
            if progress_callback:
                progress_callback("warning", message)
            return {"success": True, "message": message, "transferred_files": renamed_files}

        handle_error_and_notify(
            ValueError("转存失败，没有文件成功转存"),
            "转存失败，没有文件成功转存",
            self.wechat_notifier,
            None,
            collect=True,
        )
        return {"success": False, "error": "转存失败，没有文件成功转存"}

    def transfer_share(
        self,
        share_url,
        pwd=None,
        save_dir=None,
        progress_callback=None,
        regex_pattern=None,
        regex_replace=None,
        folder_filter=None,
    ):
        """转存分享文件"""
        with ErrorCollector(
            f"转存分享文件: {share_url}", self.wechat_notifier, None, auto_send=False
        ):
            if not self.client:
                error_msg = "客户端未初始化或初始化失败"
                handle_error_and_notify(
                    ValueError(error_msg),
                    f"转存分享文件: 客户端不可用\n分享链接: {share_url}",
                    self.wechat_notifier,
                    None,
                    collect=True,
                )
                return {"success": False, "error": error_msg}

            save_dir = self._normalize_save_dir(save_dir)

            try:
                context = self._load_share_context(
                    share_url, pwd, folder_filter, progress_callback
                )
                if not context:
                    return {"success": False, "error": "获取分享文件列表失败"}

                local_files_dict = self._scan_local_files_dict(save_dir, progress_callback)
                transfer_list = self._build_transfer_list(
                    context["shared_files_info"],
                    context["shared_paths"],
                    save_dir,
                    local_files_dict,
                    regex_pattern,
                    regex_replace,
                    progress_callback,
                )

                if not transfer_list:
                    if progress_callback:
                        progress_callback("info", "没有找到需要处理的文件")
                    return {
                        "success": True,
                        "skipped": True,
                        "message": "没有新文件需要转存",
                    }

                dir_error = self._ensure_transfer_dirs(transfer_list)
                if dir_error:
                    return dir_error

                success_count, successful_transfer_items = self._execute_transfer_plan(
                    transfer_list,
                    share_url,
                    context["uk"],
                    context["share_id"],
                    context["bdstoken"],
                    save_dir,
                    progress_callback,
                )
                renamed_files = self._rename_transferred_files(
                    successful_transfer_items, save_dir, progress_callback
                )
                return self._build_transfer_result(
                    success_count,
                    len(transfer_list),
                    renamed_files,
                    progress_callback,
                )
            except Exception as e:
                return {"success": False, "error": parse_share_error(e)}

    def get_share_folder_name(self, share_url, pwd=None):
        """获取分享链接的主文件夹名称"""
        try:
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

            shared_paths = self.share_service.load_shared_paths(share_url, pwd)
            if not shared_paths:
                error_msg = "获取分享文件列表失败"
                handle_error_and_notify(
                    ValueError(error_msg),
                    f"获取分享文件列表失败\n分享链接: {share_url}",
                    self.wechat_notifier,
                    None,
                    collect=True,
                )
                return {"success": False, "error": error_msg}

            if len(shared_paths) == 1 and hasattr(shared_paths[0], "is_dir") and shared_paths[0].is_dir:
                folder_name = os.path.basename(shared_paths[0].path)
                return {"success": True, "folder_name": folder_name}

            first_item = shared_paths[0]
            if hasattr(first_item, "is_dir") and first_item.is_dir:
                folder_name = os.path.basename(first_item.path)
            else:
                folder_name = os.path.splitext(os.path.basename(first_item.path))[0]
            return {"success": True, "folder_name": folder_name}

        except Exception as e:
            handle_error_and_notify(
                e,
                f"获取分享文件夹名称时发生异常\n分享链接: {share_url}",
                self.wechat_notifier,
                None,
                collect=True,
            )
            return {"success": False, "error": parse_share_error(e)}
