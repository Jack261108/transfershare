#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import traceback
from wechat_notifier import WeChatNotifier
from collections import defaultdict
import threading


# 用于存储错误信息的全局字典，按线程ID分组
_error_collections = defaultdict(list)
_collection_lock = threading.Lock()


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


def start_error_collection(context=""):
    """
    开始错误收集
    
    Args:
        context: 错误上下文信息
    """
    thread_id = threading.get_ident()
    with _collection_lock:
        _error_collections[thread_id] = [{"context": context, "errors": []}]


def collect_error(error, context=""):
    """
    收集错误信息
    
    Args:
        error: 异常对象
        context: 错误上下文信息
    """
    thread_id = threading.get_ident()
    with _collection_lock:
        if thread_id in _error_collections and _error_collections[thread_id]:
            error_info = {
                "type": type(error).__name__,
                "message": str(error),
                "context": context,
                "traceback": traceback.format_exc()
            }
            _error_collections[thread_id][-1]["errors"].append(error_info)


def send_collected_errors(wechat_notifier, config=None):
    """
    发送收集到的错误信息
    
    Args:
        wechat_notifier: 微信通知器实例
        config: 配置信息
    """
    if not wechat_notifier:
        return
        
    thread_id = threading.get_ident()
    with _collection_lock:
        if thread_id in _error_collections and _error_collections[thread_id]:
            collection = _error_collections[thread_id][-1]
            if collection["errors"]:
                # 构建整合的错误消息
                error_message = f"方法调用过程中发生一系列错误\n主上下文: {collection['context']}\n\n"
                for i, error in enumerate(collection["errors"], 1):
                    error_message += f"{i}. {error['context']}\n"
                    error_message += f"   错误类型: {error['type']}\n"
                    error_message += f"   错误信息: {error['message']}\n"
                    error_message += f"   详细堆栈:\n{error['traceback']}\n\n"
                
                wechat_notifier.send_error_notification(error_message.strip(), config)
            
            # 清除已发送的错误
            _error_collections[thread_id].pop()


def end_error_collection():
    """
    结束错误收集
    """
    thread_id = threading.get_ident()
    with _collection_lock:
        if thread_id in _error_collections:
            _error_collections[thread_id].clear()
            if not _error_collections[thread_id]:
                del _error_collections[thread_id]


def handle_error_and_notify(error, context, wechat_notifier, config=None, collect=True):
    """
    统一处理错误：收集错误、打印详细信息并发送微信告警
    
    Args:
        error: 异常对象
        context: 错误上下文信息
        wechat_notifier: 微信通知器实例
        config: 配置信息
        collect: 是否收集错误
    """
    # 收集错误
    if collect:
        collect_error(error, context)
    
    # 打印详细的错误信息
    print_detailed_error(error, context, wechat_notifier, config)
    
    # 发送微信告警（如果未使用错误收集机制）
    if not collect and wechat_notifier:
        send_wechat_alert(wechat_notifier, error, context, config)