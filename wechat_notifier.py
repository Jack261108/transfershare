#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from zoneinfo import ZoneInfo
import requests
from datetime import datetime
import time
import traceback


class WeChatNotifier:
    def __init__(self, webhook_url):
        """
        初始化企业微信通知器
        Args:
            webhook_url: 企业微信机器人的webhook地址
        """
        self.webhook_url = webhook_url
        
    def send_message(self, message, msg_type="text"):
        """
        发送消息到企业微信，失败时重试两次
        Args:
            message: 消息内容
            msg_type: 消息类型，支持 "text", "markdown"
        """
        max_retries = 2
        retry_delay = 5  # 重试间隔秒数
        
        for attempt in range(max_retries + 1):
            try:
                if msg_type == "text":
                    data = {
                        "msgtype": "text",
                        "text": {
                            "content": message
                        }
                    }
                elif msg_type == "markdown":
                    data = {
                        "msgtype": "markdown",
                        "markdown": {
                            "content": message
                        }
                    }
                else:
                    raise ValueError(f"不支持的消息类型: {msg_type}")
                
                response = requests.post(
                    self.webhook_url,
                    json=data,
                    headers={'Content-Type': 'application/json'},
                    timeout=60
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get('errcode') == 0:
                        print("企业微信通知发送成功")
                        return True
                    else:
                        error_msg = result.get('errmsg', '未知错误')
                        print(f"企业微信通知发送失败: {error_msg}")
                        if attempt < max_retries:
                            print(f"第 {attempt + 1} 次重试...")
                            time.sleep(retry_delay)
                            continue
                        else:
                            return False
                else:
                    print(f"企业微信通知发送失败: HTTP {response.status_code}")
                    if attempt < max_retries:
                        print(f"第 {attempt + 1} 次重试...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        return False
                    
            except Exception as e:
                # 打印完整的错误堆栈信息
                print(f"发送企业微信通知时出错: {str(e)}")
                print("错误堆栈信息:")
                traceback.print_exc()
                
                # 使用现有的错误处理工具（在函数内部导入以避免循环导入）
                try:
                    from utils import handle_error_and_notify
                    handle_error_and_notify(e, f"发送企业微信通知时出错 (尝试 {attempt + 1}/{max_retries + 1})", None)
                except ImportError:
                    # 如果无法导入工具函数，至少打印错误信息
                    print(f"无法导入错误处理工具: {str(e)}")
                
                if attempt < max_retries:
                    print(f"第 {attempt + 1} 次重试...")
                    time.sleep(retry_delay)
                    continue
                else:
                    return False
        
        return False
    
    def send_transfer_result(self, result, config):
        """
        发送转存结果通知
        Args:
            result: 转存结果字典
            config: 配置信息
        """
        current_time = datetime.now(ZoneInfo("Asia/Shanghai")).strftime('%Y-%m-%d %H:%M:%S')
        
        # 安全获取配置信息
        save_dir = config.get('save_dir', '默认') if config else '默认'
        
        # 计算总链接数和任务描述
        total_count = result.get('total_count', 1)
        if total_count > 1:
            task_desc = f'批量转存任务 ({total_count}个链接)'
        else:
            task_desc = '转存任务'
        
        if result.get('success'):
            if result.get('skipped'):
                # 没有新文件需要转存
                result_msg = result.get('message') or result.get('summary', '没有新文件需要转存')
                message = f"""## 📋 百度网盘转存报告
**时间**: {current_time}
**状态**: ✅ 完成（无新文件）
**任务**: {task_desc}
**保存目录**: {save_dir}
**结果**: {result_msg}"""
            else:
                # 转存成功
                transferred_files = result.get('transferred_files', [])
                result_msg = result.get('message') or result.get('summary', '转存成功')
                
                # 处理批量转存的文件列表
                if 'results' in result:
                    # 从批量结果中收集所有成功转存的文件
                    all_transferred_files = []
                    for res in result['results']:
                        if res.get('success') and not res.get('skipped'):
                            files = res.get('transferred_files', [])
                            all_transferred_files.extend(files)
                    transferred_files = all_transferred_files
                
                files_info = ""
                if transferred_files:
                    # 显示前5个文件
                    shown_files = transferred_files[:5]
                    files_info = "\n**转存文件**:\n" + "\n".join([f"• {file}" for file in shown_files])
                    if len(transferred_files) > 5:
                        files_info += f"\n• ... 还有 {len(transferred_files) - 5} 个文件"
                
                message = f"""## 🎉 百度网盘转存报告
**时间**: {current_time}
**状态**: ✅ 转存成功
**任务**: {task_desc}
**保存目录**: {save_dir}
**结果**: {result_msg}{files_info}"""
        else:
            # 转存失败
            error_msg = result.get('error', '未知错误')
            message = f"""## ❌ 百度网盘转存报告
**时间**: {current_time}
**状态**: ❌ 转存失败
**任务**: {task_desc}
**保存目录**: {save_dir}
**错误信息**: {error_msg}

请检查分享链接是否有效，或查看详细日志排查问题。"""
        
        return self.send_message(message, "markdown")
    
    def send_error_notification(self, error_msg, config):
        """
        发送错误通知
        Args:
            error_msg: 错误信息
            config: 配置信息
        """
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 安全获取配置信息
        save_dir = config.get('save_dir', '默认') if config else '默认'
        
        message = f"""## ⚠️ 百度网盘转存异常
**时间**: {current_time}
**状态**: ❌ 执行异常
**任务类型**: 自动转存任务
**保存目录**: {save_dir}
**错误信息**: {error_msg}

请检查配置或联系管理员处理。"""
        
        return self.send_message(message, "markdown")
    
    def send_test_message(self):
        """
        发送测试消息
        """
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        message = f"""## 🔔 测试通知
**时间**: {current_time}
**状态**: ✅ 企业微信通知测试成功

百度网盘自动转存系统已就绪！"""
        
        return self.send_message(message, "markdown")