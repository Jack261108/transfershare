#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import traceback
from wechat_notifier import WeChatNotifier


def print_detailed_error(error, context="", wechat_notifier=None, config=None):
    """
    打印详细的错误信息并可选择发送微信告警
    
    Args:
        error: 异常对象
        context: 错误上下文信息
        wechat_notifier: 微信通知器实例
        config: 配置信息
    """
    error_msg = f"发生异常: {context}\n"
    error_msg += f"  错误类型: {type(error).__name__}\n"
    error_msg += f"  错误信息: {str(error)}\n"
    error_msg += f"  详细堆栈: {traceback.format_exc()}"
    
    print(error_msg)
    
    # 发送微信告警
    if wechat_notifier:
        detailed_error = f"{context}\n错误类型: {type(error).__name__}\n错误信息: {str(error)}\n详细堆栈: {traceback.format_exc()}"
        wechat_notifier.send_error_notification(detailed_error, config)


def format_error_info(error, context=""):
    """
    格式化错误信息
    
    Args:
        error: 异常对象
        context: 错误上下文信息
        
    Returns:
        str: 格式化的错误信息
    """
    error_info = f"发生异常: {context}\n"
    error_info += f"  错误类型: {type(error).__name__}\n"
    error_info += f"  错误信息: {str(error)}\n"
    error_info += f"  详细堆栈: {traceback.format_exc()}"
    
    return error_info


def send_wechat_alert(wechat_notifier, error, context="", config=None):
    """
    发送微信告警
    
    Args:
        wechat_notifier: 微信通知器实例
        error: 异常对象
        context: 错误上下文信息
        config: 配置信息
    """
    if wechat_notifier:
        detailed_error = f"{context}\n错误类型: {type(error).__name__}\n错误信息: {str(error)}\n详细堆栈: {traceback.format_exc()}"
        wechat_notifier.send_error_notification(detailed_error, config)