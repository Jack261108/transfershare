#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import requests
from datetime import datetime


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
        发送消息到企业微信
        Args:
            message: 消息内容
            msg_type: 消息类型，支持 "text", "markdown"
        """
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
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('errcode') == 0:
                    print("企业微信通知发送成功")
                    return True
                else:
                    print(f"企业微信通知发送失败: {result.get('errmsg', '未知错误')}")
                    return False
            else:
                print(f"企业微信通知发送失败: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            print(f"发送企业微信通知时出错: {str(e)}")
            return False
    
    def send_transfer_result(self, result, config):
        """
        发送转存结果通知
        Args:
            result: 转存结果字典
            config: 配置信息
        """
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if result['success']:
            if result.get('skipped'):
                # 没有新文件需要转存
                message = f"""## 📋 百度网盘转存报告
**时间**: {current_time}
**状态**: ✅ 完成（无新文件）
**分享链接**: {config['share_url']}
**保存目录**: {config['save_dir']}
**结果**: {result['message']}"""
            else:
                # 转存成功
                transferred_files = result.get('transferred_files', [])
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
**分享链接**: {config['share_url']}
**保存目录**: {config['save_dir']}
**结果**: {result['message']}{files_info}"""
        else:
            # 转存失败
            error_msg = result.get('error', '未知错误')
            message = f"""## ❌ 百度网盘转存报告
**时间**: {current_time}
**状态**: ❌ 转存失败
**分享链接**: {config['share_url']}
**保存目录**: {config['save_dir']}
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
        
        message = f"""## ⚠️ 百度网盘转存异常
**时间**: {current_time}
**状态**: ❌ 执行异常
**分享链接**: {config.get('share_url', '未知')}
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