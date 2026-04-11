#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, List
import requests
from datetime import datetime
import time
import traceback
import os

# 常量定义
MAX_RETRIES = 2
RETRY_DELAY = 5  # 重试间隔（秒）
REQUEST_TIMEOUT = 60  # 请求超时（秒）
MAX_FILES_TO_SHOW = 5  # 消息中显示的最大文件数量
TIMEZONE = ZoneInfo("Asia/Shanghai")  # 时区
DEFAULT_SAVE_DIR = "默认"  # 默认保存目录


class WeChatNotifier:
    def __init__(self, webhook_url: str):
        """
        初始化企业微信通知器
        Args:
            webhook_url: 企业微信机器人的webhook地址
        """
        self.webhook_url = webhook_url

    def _build_message_data(self, message: str, msg_type: str) -> Dict[str, Any]:
        """
        构建消息数据
        Args:
            message: 消息内容
            msg_type: 消息类型
        Returns:
            消息数据字典
        """
        if msg_type == "text":
            return {"msgtype": "text", "text": {"content": message}}
        elif msg_type == "markdown":
            return {"msgtype": "markdown", "markdown": {"content": message}}
        else:
            raise ValueError(f"不支持的消息类型: {msg_type}")

    def _handle_send_error(self, error: Exception, attempt: int) -> None:
        """
        处理发送错误
        Args:
            error: 异常对象
            attempt: 当前尝试次数
        """
        print(f"发送企业微信通知时出错: {str(error)}")
        print("错误堆栈信息:")
        traceback.print_exc()

        # 使用现有的错误处理工具（在函数内部导入以避免循环导入）
        try:
            from utils import handle_error_and_notify

            handle_error_and_notify(
                error,
                f"发送企业微信通知时出错 (尝试 {attempt + 1}/{MAX_RETRIES + 1})",
                None,
            )
        except ImportError:
            # 如果无法导入工具函数，至少打印错误信息
            pass

    def send_message(self, message: str, msg_type: str = "text") -> bool:
        """
        发送消息到企业微信，失败时重试
        Args:
            message: 消息内容
            msg_type: 消息类型，支持 "text", "markdown"
        Returns:
            是否发送成功
        """
        for attempt in range(MAX_RETRIES + 1):
            try:
                data = self._build_message_data(message, msg_type)
                response = requests.post(
                    self.webhook_url,
                    json=data,
                    headers={"Content-Type": "application/json"},
                    timeout=REQUEST_TIMEOUT,
                )

                if response.status_code == 200:
                    result = response.json()
                    if result.get("errcode") == 0:
                        print("企业微信通知发送成功")
                        return True
                    else:
                        error_msg = result.get("errmsg", "未知错误")
                        print(f"企业微信通知发送失败: {error_msg}")
                else:
                    print(f"企业微信通知发送失败: HTTP {response.status_code}")

                # 判断是否需要重试
                if attempt < MAX_RETRIES:
                    print(f"第 {attempt + 1} 次重试...")
                    time.sleep(RETRY_DELAY)
                    continue
                else:
                    return False

            except Exception as e:
                self._handle_send_error(e, attempt)
                if attempt < MAX_RETRIES:
                    print(f"第 {attempt + 1} 次重试...")
                    time.sleep(RETRY_DELAY)
                    continue
                else:
                    return False

        return False

    def _get_current_time(self) -> str:
        """获取当前时间字符串"""
        return datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

    def _get_save_dir(self, config: Optional[Dict[str, Any]]) -> str:
        """安全获取保存目录"""
        return config.get("save_dir", DEFAULT_SAVE_DIR) if config else DEFAULT_SAVE_DIR

    def _get_github_actions_info(self) -> Optional[Dict[str, str]]:
        """
        获取 GitHub Actions 运行详情
        
        Returns:
            dict: GitHub Actions 信息，如果不是 GitHub Actions 环境则返回 None
        """
        if os.getenv("GITHUB_ACTIONS") != "true":
            return None
        
        try:
            repository = os.getenv("GITHUB_REPOSITORY", "")
            run_id = os.getenv("GITHUB_RUN_ID", "")
            run_number = os.getenv("GITHUB_RUN_NUMBER", "")
            workflow = os.getenv("GITHUB_WORKFLOW", "")
            server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com")
            ref = os.getenv("GITHUB_REF", "")
            sha = os.getenv("GITHUB_SHA", "")
            
            # 构建运行详情链接
            run_url = f"{server_url}/{repository}/actions/runs/{run_id}" if repository and run_id else None
            
            # 构建提交链接
            commit_url = f"{server_url}/{repository}/commit/{sha}" if repository and sha else None
            
            return {
                "repository": repository,
                "run_id": run_id,
                "run_number": run_number,
                "workflow": workflow,
                "ref": ref,
                "sha": sha[:7] if sha else "",  # 只显示前7位
                "run_url": run_url,
                "commit_url": commit_url,
            }
        except Exception:
            return None

    def _format_files_info(self, transferred_files: List[str]) -> str:
        """
        格式化文件信息
        Args:
            transferred_files: 转存的文件列表
        Returns:
            格式化的文件信息字符串
        """
        if not transferred_files:
            return ""

        shown_files = transferred_files[:MAX_FILES_TO_SHOW]
        files_info = "\n**转存文件**:\n" + "\n".join(
            [f"• {file}" for file in shown_files]
        )

        if len(transferred_files) > MAX_FILES_TO_SHOW:
            files_info += (
                f"\n• ... 还有 {len(transferred_files) - MAX_FILES_TO_SHOW} 个文件"
            )

        return files_info

    def _collect_transferred_files(self, result: Dict[str, Any]) -> List[str]:
        """
        从批量结果中收集所有成功转存的文件
        Args:
            result: 转存结果字典
        Returns:
            所有转存的文件列表
        """
        from utils import collect_transferred_files

        return collect_transferred_files(result)

    def send_transfer_result(
        self, result: Dict[str, Any], config: Optional[Dict[str, Any]]
    ) -> bool:
        """
        发送转存结果通知
        Args:
            result: 转存结果字典
            config: 配置信息
        Returns:
            是否发送成功
        """
        current_time = self._get_current_time()
        save_dir = self._get_save_dir(config)

        # 计算总链接数和任务描述
        total_count = result.get("total_count", 1)
        task_desc = (
            f"批量转存任务 ({total_count}个链接)" if total_count > 1 else "转存任务"
        )

        if result.get("success"):
            if result.get("skipped"):
                # 没有新文件需要转存
                result_msg = result.get("message") or result.get(
                    "summary", "没有新文件需要转存"
                )
                message = f"""## 📋 百度网盘转存报告
**时间**: {current_time}
**状态**: ✅ 完成（无新文件）
**任务**: {task_desc}
**保存目录**: {save_dir}
**结果**: {result_msg}"""
            else:
                # 转存成功
                transferred_files = self._collect_transferred_files(result)
                result_msg = result.get("message") or result.get("summary", "转存成功")
                files_info = self._format_files_info(transferred_files)

                message = f"""## 🎉 百度网盘转存报告
**时间**: {current_time}
**状态**: ✅ 转存成功
**任务**: {task_desc}
**保存目录**: {save_dir}
**结果**: {result_msg}{files_info}"""
        elif result.get("partial"):
            error_msg = result.get("error", "部分转存成功")
            rename_failed_files = result.get("rename_failed_files", [])
            rename_failed_info = ""
            if rename_failed_files:
                shown = rename_failed_files[:MAX_FILES_TO_SHOW]
                rename_failed_info = "\n**重命名失败**:\n" + "\n".join(
                    [
                        f"• {item.get('source_path')} -> {item.get('target_path')}: {item.get('error')}"
                        for item in shown
                    ]
                )
                if len(rename_failed_files) > MAX_FILES_TO_SHOW:
                    rename_failed_info += (
                        f"\n• ... 还有 {len(rename_failed_files) - MAX_FILES_TO_SHOW} 个文件"
                    )
            message = f"""## ⚠️ 百度网盘转存报告
**时间**: {current_time}
**状态**: ⚠️ 部分成功（按失败处理，退出码 1）
**任务**: {task_desc}
**保存目录**: {save_dir}
**结果**: {error_msg}{rename_failed_info}"""
        else:
            # 转存失败
            error_msg = result.get("error", "未知错误")
            message = f"""## ❌ 百度网盘转存报告
**时间**: {current_time}
**状态**: ❌ 转存失败
**任务**: {task_desc}
**保存目录**: {save_dir}
**错误信息**: {error_msg}

请检查分享链接是否有效，或查看详细日志排查问题。"""

        return self.send_message(message, "markdown")

    def _mask_sensitive(self, text: Optional[str]) -> Optional[str]:
        """
        掩码敏感信息
        Args:
            text: 原始文本
        Returns:
            掩码后的文本
        """
        if text is None:
            return text

        from utils import _mask_sensitive as shared_mask_sensitive

        masked = shared_mask_sensitive(text)
        return masked if masked is not None else text

    def send_error_notification(
        self, error_msg: str, config: Optional[Dict[str, Any]]
    ) -> bool:
        """
        发送错误通知
        Args:
            error_msg: 错误信息
            config: 配置信息
        Returns:
            是否发送成功
        """
        current_time = self._get_current_time()
        save_dir = self._get_save_dir(config)

        # 掩码敏感信息
        masked_error = self._mask_sensitive(error_msg) or error_msg

        # 获取 GitHub Actions 运行详情
        github_info = self._get_github_actions_info()
        
        # 构建消息
        message = f"""## ⚠️ 百度网盘转存异常
**时间**: {current_time}
**状态**: ❌ 执行异常
**任务类型**: 自动转存任务
**保存目录**: {save_dir}"""

        # 添加 GitHub Actions 运行详情
        if github_info:
            # 格式化分支/标签名称
            ref = github_info.get('ref', '')
            if ref:
                ref = ref.replace('refs/heads/', '').replace('refs/tags/', '').replace('refs/pull/', 'PR-')
            
            message += f"""
**GitHub Actions 详情**:
- 仓库: `{github_info.get('repository', 'N/A')}`
- 工作流: `{github_info.get('workflow', 'N/A')}`
- 运行编号: `#{github_info.get('run_number', 'N/A')}`
- 分支/标签: `{ref or 'N/A'}`
- 提交: `{github_info.get('sha', 'N/A')}`"""
            
            if github_info.get('run_url'):
                message += f"\n- 🔗 [查看运行详情]({github_info['run_url']})"
            
            if github_info.get('commit_url'):
                message += f"\n- 🔗 [查看提交详情]({github_info['commit_url']})"

        message += f"""
**错误信息**: {masked_error}

请检查配置或联系管理员处理。"""

        return self.send_message(message, "markdown")

    def send_test_message(self) -> bool:
        """
        发送测试消息
        Returns:
            是否发送成功
        """
        current_time = self._get_current_time()
        message = f"""## 🔔 测试通知
**时间**: {current_time}
**状态**: ✅ 企业微信通知测试成功

百度网盘自动转存系统已就绪！"""

        return self.send_message(message, "markdown")
