#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import traceback
from wechat_notifier import WeChatNotifier
from collections import defaultdict
import threading


# 用于存储错误信息的全局字典，按线程ID分组
_error_collections = defaultdict(list)
_collection_lock = threading.Lock()


def _mask_sensitive(text: str) -> str:
    from utils import mask_cookies as _mask_cookies  # local import to avoid cycles
    import re as _re
    if text is None:
        return text
    masked = _mask_cookies(text)
    # mask pwd=xxxx
    masked = _re.sub(r'(\bpwd=)([A-Za-z0-9]{4})', r'\1***', masked, flags=_re.IGNORECASE)
    # mask uk/share_id/bdstoken (keep key show, hide value)
    masked = _re.sub(r'(\buk\s*[:=]\s*)(\d+)', r'\1***', masked, flags=_re.IGNORECASE)
    masked = _re.sub(r'(\bshare_id\s*[:=]\s*)(\d+)', r'\1***', masked, flags=_re.IGNORECASE)
    masked = _re.sub(r'(\bbdstoken\s*[:=]\s*)([A-Za-z0-9_-]+)', r'\1***', masked, flags=_re.IGNORECASE)
    return masked

def print_detailed_error(error, context="", wechat_notifier=None, config=None):
    """
    仅打印详细的错误信息（不直接发送通知），并对敏感信息进行掩码
    """
    base = f"发生异常: {context}\n"
    base += f"  错误类型: {type(error).__name__}\n"
    base += f"  错误信息: {str(error)}\n"
    base += f"  详细堆栈: {traceback.format_exc()}"
    print(_mask_sensitive(base))
    # 不在此处发送企业微信通知，避免与上层统一处理重复发送


def format_error_info(error, context=""):
    """格式化错误信息（包含敏感信息掩码）"""
    base = f"发生异常: {context}\n"
    base += f"  错误类型: {type(error).__name__}\n"
    base += f"  错误信息: {str(error)}\n"
    base += f"  详细堆栈: {traceback.format_exc()}"
    return _mask_sensitive(base)


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
        # 统一掩码
        wechat_notifier.send_error_notification(_mask_sensitive(detailed_error), config)


def start_error_collection(context=""):
    """
    开始错误收集
    
    Args:
        context: 错误上下文信息
    """
    thread_id = threading.get_ident()
    with _collection_lock:
        _error_collections[thread_id] = [{"context": context, "errors": [], "seen": set()}]


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
            # 构造去重键：类型 + 消息 + 归一化上下文
            etype = type(error).__name__
            emsg = str(error)
            ectx = str(context)
            key = f"{etype}|{emsg}|{ectx}"
            stack = _error_collections[thread_id][-1]
            seen = stack.get("seen")
            if isinstance(seen, set):
                if key in seen:
                    return  # 已收集，跳过
                seen.add(key)
            error_info = {
                "type": etype,
                "message": emsg,
                "context": ectx,
                "traceback": traceback.format_exc()
            }
            stack["errors"].append(error_info)


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
    结束错误收集（仅弹出当前栈顶，支持嵌套）
    """
    thread_id = threading.get_ident()
    with _collection_lock:
        if thread_id in _error_collections:
            if _error_collections[thread_id]:
                _error_collections[thread_id].pop()
            # 若栈空则删除该线程项
            if not _error_collections[thread_id]:
                del _error_collections[thread_id]


def handle_error_and_notify(error, context, wechat_notifier, config=None, collect=True):
    """
    统一处理错误：收集错误、打印详细信息，并在需要时发送微信告警
    
    Args:
        error: 异常对象
        context: 错误上下文信息
        wechat_notifier: 微信通知器实例
        config: 配置信息
        collect: 是否收集错误（True 表示纳入聚合，由 ErrorCollector 统一发送；False 表示立即发送一次）
    """
    # 收集错误
    if collect:
        collect_error(error, context)
    
    # 仅打印详细的错误信息（不直接发送），避免重复
    print_detailed_error(error, context)
    
    # 在存在收集上下文时，避免即时发送造成重复
    thread_id = threading.get_ident()
    has_collection = False
    try:
        with _collection_lock:
            has_collection = bool(_error_collections.get(thread_id))
    except Exception:
        has_collection = False
    
    # 立即发送一次（仅当未聚合且当前没有收集上下文时）
    if not collect and not has_collection and wechat_notifier:
        send_wechat_alert(wechat_notifier, error, context, config)


# ========== 新增：敏感信息掩码与错误收集上下文管理器 ==========

import re as _re
from contextlib import contextmanager

MASK_REPLACEMENT = "***"

def mask(text, patterns, replacement=MASK_REPLACEMENT):
    """
    通用敏感信息掩码工具。
    Args:
        text: 原始文本
        patterns: 
          - 字符串或正则对象，或其列表/元组
          - 若为字符串，直接整体替换为 replacement
          - 若为正则，优先替换第1个捕获组；无捕获组则整体匹配替换
        replacement: 替换用的掩码（默认 ***）
    Returns:
        str: 已掩码文本
    """
    if text is None:
        return text
    if not isinstance(patterns, (list, tuple)):
        patterns = [patterns]
    masked = str(text)
    for pat in patterns:
        try:
            if isinstance(pat, str):
                masked = masked.replace(pat, replacement)
            else:
                # 视为正则：若存在捕获组，仅替换第1个捕获组
                regex = pat if hasattr(pat, "sub") else _re.compile(pat)
                def _sub(m):
                    if m.groups():
                        g1 = m.group(1)
                        if g1 is None:
                            return replacement
                        start, end = m.start(1), m.end(1)
                        seg = masked[m.start():m.end()]
                        # 将匹配片段中的第1组替换为 replacement
                        return seg[:start - m.start()] + replacement + seg[end - m.start():]
                    return replacement
                masked = regex.sub(_sub, masked)
        except Exception:
            # 掩码过程中失败不应影响主流程
            continue
    return masked

def mask_cookies(text):
    """
    针对常见 Cookie 键的掩码（仅隐藏值，不改变原格式）。
    支持：BDUSS、STOKEN、BDUSS_BFESS、STOKEN_BFESS、BDCLND、BAIDUID
    """
    if text is None:
        return text
    keys = ["BDUSS", "STOKEN", "BDUSS_BFESS", "STOKEN_BFESS", "BDCLND", "BAIDUID"]
    # 形如 KEY=任意非分号字符; 或 KEY="..." 的值掩码
    regs = []
    for k in keys:
        regs.append(_re.compile(rf'({k}\s*=\s*)[^;"]+'))
        regs.append(_re.compile(rf'({k}\s*=\s*")[^"]*(")'))
    masked = text
    for r in regs:
        def repl(m):
            if m.lastindex == 2:
                return f'{m.group(1)}{MASK_REPLACEMENT}{m.group(2)}'
            return f'{m.group(1)}{MASK_REPLACEMENT}'
        masked = r.sub(repl, masked)
    return masked


class ErrorCollector:
    """
    错误收集上下文管理器：
      with ErrorCollector("上下文", wechat_notifier, config) as ec:
          # 业务代码
          try:
              ...
          except Exception as e:
              ec.capture(e, "子步骤说明")  # 只收集，不中断
          # 若 with 块抛出未捕获异常，自动收集并原样抛出
      退出时自动 send_collected_errors 并 end_error_collection
    """
    def __init__(self, context="", wechat_notifier=None, config=None, auto_send=True, suppress=False):
        self.context = context
        self.wechat_notifier = wechat_notifier
        self.config = config
        self.auto_send = auto_send
        self.suppress = suppress  # True 则吞掉异常（默认不吞）
    
    def __enter__(self):
        start_error_collection(self.context)
        return self
    
    def capture(self, error, context=""):
        """手动采集错误"""
        collect_error(error, context)
        return False  # 方便在 except 中 `return ec.capture(e)` 模式使用
    
    def __exit__(self, exc_type, exc, tb):
        # 未捕获异常也纳入收集
        if exc is not None:
            collect_error(exc, f"{self.context}（未捕获异常）")
            # 打印详细错误
            print_detailed_error(exc, self.context, self.wechat_notifier, self.config)
        # 发送聚合错误
        if self.auto_send:
            try:
                send_collected_errors(self.wechat_notifier, self.config)
            finally:
                end_error_collection()
        else:
            end_error_collection()
        # 返回是否吞掉异常
        return bool(self.suppress)


@contextmanager
def error_collection(context="", wechat_notifier=None, config=None, auto_send=True, suppress=False):
    """
    函数式便捷用法：
      with error_collection("ctx", notifier, config):
          ...
    """
    ec = ErrorCollector(context, wechat_notifier, config, auto_send, suppress)
    try:
        yield ec
    except Exception as e:
        # __exit__ 会再次处理，这里只让异常继续抛出
        raise
    finally:
        pass