#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import traceback
from typing import Optional, Dict, Any, List, Set, Tuple
from collections import defaultdict
import threading
import re

# 延迟导入以避免循环依赖
try:
    from wechat_notifier import WeChatNotifier
except ImportError:
    WeChatNotifier = None  # type: ignore


# 用于存储错误信息的全局字典，按线程ID分组
_error_collections: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
_collection_lock = threading.Lock()

# 预编译正则表达式以提高性能
_PWD_PATTERN = re.compile(r"(\bpwd=)([A-Za-z0-9]{4})", re.IGNORECASE)
_UK_PATTERN = re.compile(r"(\buk\s*[:=]\s*)(\d+)", re.IGNORECASE)
_SHARE_ID_PATTERN = re.compile(r"(\bshare_id\s*[:=]\s*)(\d+)", re.IGNORECASE)
_BDSTOKEN_PATTERN = re.compile(
    r"(\bbdstoken\s*[:=]\s*)([A-Za-z0-9_-]+)", re.IGNORECASE
)
_SHARE_LINK_TOKEN_PATTERN = re.compile(
    r"(https?://pan\.baidu\.com/s/)([A-Za-z0-9_-]+)", re.IGNORECASE
)
_SHARE_SURL_TOKEN_PATTERN = re.compile(
    r"(\bsurl=)([A-Za-z0-9_-]+)", re.IGNORECASE
)


def mask_share_url(text: Optional[str]) -> Optional[str]:
    """掩码百度网盘分享链接，仅隐藏链接标识。"""
    if text is None:
        return text

    masked = _SHARE_LINK_TOKEN_PATTERN.sub(r"\1***", str(text))
    return _SHARE_SURL_TOKEN_PATTERN.sub(r"\1***", masked)



def collect_transferred_files(result: Optional[Dict[str, Any]]) -> List[str]:
    """从单个或批量转存结果中提取成功转存的文件列表。"""
    if not isinstance(result, dict):
        return []

    if "results" not in result:
        return list(result.get("transferred_files", []))

    transferred_files = []
    for item in result["results"]:
        if item.get("success") and not item.get("skipped"):
            transferred_files.extend(item.get("transferred_files", []))
    return transferred_files



def _mask_sensitive(text: Optional[str]) -> Optional[str]:
    """
    掩码敏感信息（pwd, uk, share_id, bdstoken、分享链接等）
    注意：此函数会调用 mask_cookies，但通过延迟加载避免循环导入
    """
    if text is None:
        return text

    # 先掩码 cookies（避免循环导入，直接调用函数）
    masked = mask_cookies(text)

    # 掩码其他敏感信息
    masked = _PWD_PATTERN.sub(r"\1***", masked)
    masked = _UK_PATTERN.sub(r"\1***", masked)
    masked = _SHARE_ID_PATTERN.sub(r"\1***", masked)
    masked = _BDSTOKEN_PATTERN.sub(r"\1***", masked)
    masked = _SHARE_LINK_TOKEN_PATTERN.sub(r"\1***", masked)
    masked = _SHARE_SURL_TOKEN_PATTERN.sub(r"\1***", masked)

    return masked


def _format_error_base(error: Exception, context: str = "") -> str:
    """
    统一格式化错误信息的基础部分
    """
    return (
        f"发生异常: {context}\n"
        f"  错误类型: {type(error).__name__}\n"
        f"  错误信息: {str(error)}\n"
        f"  详细堆栈: {traceback.format_exc()}"
    )


def print_detailed_error(
    error: Exception,
    context: str = "",
    wechat_notifier: Optional[Any] = None,
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """
    仅打印详细的错误信息（不直接发送通知），并对敏感信息进行掩码

    Args:
        error: 异常对象
        context: 错误上下文信息
        wechat_notifier: 微信通知器实例（未使用，为兼容性保留）
        config: 配置信息（未使用，为兼容性保留）
    """
    base = _format_error_base(error, context)
    masked = _mask_sensitive(base)
    print(masked if masked is not None else base)
    # 不在此处发送企业微信通知，避免与上层统一处理重复发送


def format_error_info(error: Exception, context: str = "") -> str:
    """
    格式化错误信息（包含敏感信息掩码）

    Args:
        error: 异常对象
        context: 错误上下文信息

    Returns:
        已掩码的错误信息字符串
    """
    base = _format_error_base(error, context)
    masked = _mask_sensitive(base)
    return masked if masked is not None else base


def send_wechat_alert(
    wechat_notifier: Optional[Any],
    error: Exception,
    context: str = "",
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """
    发送微信告警

    Args:
        wechat_notifier: 微信通知器实例
        error: 异常对象
        context: 错误上下文信息
        config: 配置信息
    """
    if wechat_notifier:
        detailed_error = _format_error_base(error, context)
        masked_error = _mask_sensitive(detailed_error)
        # 统一掩码，send_error_notification 会自动包含 GitHub Actions 详情
        wechat_notifier.send_error_notification(
            masked_error if masked_error is not None else detailed_error, config
        )


def start_error_collection(context: str = "") -> None:
    """
    开始错误收集

    Args:
        context: 错误上下文信息
    """
    thread_id = threading.get_ident()
    with _collection_lock:
        _error_collections[thread_id].append(
            {"context": context, "errors": [], "seen": set()}
        )


def _has_active_collection() -> bool:
    """
    检查当前线程是否有活跃的错误收集上下文（线程安全，不持有锁）

    Returns:
        是否有活跃的错误收集上下文
    """
    thread_id = threading.get_ident()
    with _collection_lock:
        return bool(
            thread_id in _error_collections and _error_collections[thread_id]
        )


def collect_error(error: Exception, context: str = "") -> bool:
    """
    收集错误信息（线程安全，支持去重）

    Args:
        error: 异常对象
        context: 错误上下文信息

    Returns:
        bool: True 表示成功收集，False 表示没有活跃的收集上下文或已去重

    Note:
        错误会被去重，相同类型、消息和上下文的错误只会收集一次
    """
    thread_id = threading.get_ident()
    with _collection_lock:
        if not (
            thread_id in _error_collections and _error_collections[thread_id]
        ):
            return False  # 没有活跃的错误收集上下文

        # 构造去重键：类型 + 消息 + 归一化上下文
        etype = type(error).__name__
        emsg = str(error)
        ectx = str(context)
        key = f"{etype}|{emsg}|{ectx}"

        stack = _error_collections[thread_id][-1]
        seen: Set[str] = stack.get("seen", set())
        if key in seen:
            return False  # 已收集，跳过

        seen.add(key)
        error_info = {
            "type": etype,
            "message": emsg,
            "context": ectx,
            "traceback": traceback.format_exc(),
        }
        stack["errors"].append(error_info)
        return True


def send_collected_errors(
    wechat_notifier: Optional[Any], config: Optional[Dict[str, Any]] = None
) -> None:
    """
    发送收集到的错误信息（线程安全）
    注意：GitHub Actions 详情会自动包含在错误通知中

    Args:
        wechat_notifier: 微信通知器实例
        config: 配置信息
    """
    if not wechat_notifier:
        return

    thread_id = threading.get_ident()
    # 先获取数据，然后释放锁再调用外部函数，避免死锁
    error_message = None
    with _collection_lock:
        if not (
            thread_id in _error_collections and _error_collections[thread_id]
        ):
            return

        collection = _error_collections[thread_id][-1]
        errors = collection.get("errors", [])

        if errors:
            # 构建整合的错误消息（在持有锁时构建，避免数据竞争）
            error_message = (
                f"方法调用过程中发生一系列错误\n"
                f"主上下文: {collection['context']}\n\n"
            )
            for i, error_info in enumerate(errors, 1):
                error_message += (
                    f"{i}. {error_info['context']}\n"
                    f"   错误类型: {error_info['type']}\n"
                    f"   错误信息: {error_info['message']}\n"
                    f"   详细堆栈:\n{error_info['traceback']}\n\n"
                )

        # 清除已发送的错误（不在此处 pop，由 end_error_collection 统一处理）

    # 在锁外调用外部函数，避免死锁
    # send_error_notification 会自动包含 GitHub Actions 详情
    if error_message:
        masked_message = _mask_sensitive(error_message.strip())
        wechat_notifier.send_error_notification(
            masked_message if masked_message is not None else error_message.strip(),
            config,
        )


def end_error_collection() -> None:
    """
    结束错误收集（仅弹出当前栈顶，支持嵌套）

    Note:
        此函数会弹出当前线程的错误收集栈顶，如果栈为空则删除线程项
    """
    thread_id = threading.get_ident()
    with _collection_lock:
        if thread_id in _error_collections:
            if _error_collections[thread_id]:
                _error_collections[thread_id].pop()
            # 若栈空则删除该线程项
            if not _error_collections[thread_id]:
                del _error_collections[thread_id]


def handle_error_and_notify(
    error: Exception,
    context: str,
    wechat_notifier: Optional[Any],
    config: Optional[Dict[str, Any]] = None,
    collect: bool = True,
) -> None:
    """
    统一处理错误：收集错误、打印详细信息，并在需要时发送微信告警

    Args:
        error: 异常对象
        context: 错误上下文信息
        wechat_notifier: 微信通知器实例
        config: 配置信息
        collect: 是否收集错误（True 表示纳入聚合，由 ErrorCollector 统一发送；False 表示立即发送一次）

    Note:
        - 当 collect=True 时，错误会被收集到 ErrorCollector 中，稍后统一发送
        - 当 collect=False 且当前没有活跃的 ErrorCollector 时，会立即发送告警
        - 避免重复告警：在 ErrorCollector 作用域内不会立即发送
    """
    # 收集错误（如果 collect=True，会检查是否有活跃的收集上下文）
    if collect:
        collect_error(error, context)
    
    # 检查是否存在活跃的错误收集上下文（在锁外调用，避免重复获取锁）
    has_collection = _has_active_collection()

    # 仅打印详细的错误信息（不直接发送），避免重复
    print_detailed_error(error, context, wechat_notifier, config)

    # 立即发送一次（仅当未聚合且当前没有收集上下文时）
    if not collect and not has_collection and wechat_notifier:
        send_wechat_alert(wechat_notifier, error, context, config)


# ========== 敏感信息掩码与错误收集上下文管理器 ==========

from contextlib import contextmanager

MASK_REPLACEMENT = "***"


def mask(
    text: Optional[str],
    patterns: Any,
    replacement: str = MASK_REPLACEMENT,
) -> Optional[str]:
    """
    通用敏感信息掩码工具。

    Args:
        text: 原始文本
        patterns: 掩码模式
            - 字符串或正则对象，或其列表/元组
            - 若为字符串，直接整体替换为 replacement
            - 若为正则，优先替换第1个捕获组；无捕获组则整体匹配替换
        replacement: 替换用的掩码（默认 ***）

    Returns:
        已掩码文本，如果输入为 None 则返回 None
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
                regex = pat if hasattr(pat, "sub") else re.compile(pat)

                def _sub(match: re.Match[str]) -> str:
                    if match.groups():
                        g1 = match.group(1)
                        if g1 is None:
                            return replacement
                        start, end = match.start(1), match.end(1)
                        seg = masked[match.start() : match.end()]
                        # 将匹配片段中的第1组替换为 replacement
                        return (
                            seg[: start - match.start()]
                            + replacement
                            + seg[end - match.start() :]
                        )
                    return replacement

                masked = regex.sub(_sub, masked)
        except Exception:
            # 掩码过程中失败不应影响主流程
            continue
    return masked


# 预编译 Cookie 掩码正则表达式
_COOKIE_KEYS = [
    "BDUSS",
    "STOKEN",
    "BDUSS_BFESS",
    "STOKEN_BFESS",
    "BDCLND",
    "BAIDUID",
]
_COOKIE_PATTERNS: List[re.Pattern[str]] = []
for key in _COOKIE_KEYS:
    # 匹配 KEY=任意非分号字符; 或 KEY="..."
    _COOKIE_PATTERNS.append(re.compile(rf"({key}\s*=\s*)[^;\"]+"))
    _COOKIE_PATTERNS.append(re.compile(rf'({key}\s*=\s*")[^"]*(")'))


def mask_cookies(text: Optional[str]) -> Optional[str]:
    """
    针对常见 Cookie 键的掩码（仅隐藏值，不改变原格式）。

    支持：BDUSS、STOKEN、BDUSS_BFESS、STOKEN_BFESS、BDCLND、BAIDUID

    Args:
        text: 原始文本

    Returns:
        已掩码文本，如果输入为 None 则返回 None
    """
    if text is None:
        return text

    def repl(match: re.Match[str]) -> str:
        if match.lastindex == 2:
            return f"{match.group(1)}{MASK_REPLACEMENT}{match.group(2)}"
        return f"{match.group(1)}{MASK_REPLACEMENT}"

    masked = text
    for pattern in _COOKIE_PATTERNS:
        masked = pattern.sub(repl, masked)
    return masked


class ErrorCollector:
    """
    错误收集上下文管理器，用于聚合收集多个错误并统一发送。

    使用示例：
        with ErrorCollector("批量转存", wechat_notifier, config) as ec:
            try:
                # 业务代码
                ...
            except Exception as e:
                ec.capture(e, "子步骤说明")  # 只收集，不中断
            # 若 with 块抛出未捕获异常，自动收集并原样抛出
        退出时自动 send_collected_errors 并 end_error_collection

    Attributes:
        context: 错误上下文信息
        wechat_notifier: 微信通知器实例
        config: 配置信息
        auto_send: 是否自动发送收集的错误
        suppress: 是否吞掉异常（True 则吞掉，默认不吞）
    """

    def __init__(
        self,
        context: str = "",
        wechat_notifier: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
        auto_send: bool = True,
        suppress: bool = False,
    ) -> None:
        self.context = context
        self.wechat_notifier = wechat_notifier
        self.config = config
        self.auto_send = auto_send
        self.suppress = suppress  # True 则吞掉异常（默认不吞）

    def __enter__(self) -> "ErrorCollector":
        """进入上下文管理器，开始错误收集"""
        start_error_collection(self.context)
        return self

    def capture(self, error: Exception, context: str = "") -> bool:
        """
        手动采集错误

        Args:
            error: 异常对象
            context: 错误上下文信息

        Returns:
            False，方便在 except 中 `return ec.capture(e)` 模式使用
        """
        collect_error(error, context)  # 返回值被忽略，保持原有接口
        return False

    def __exit__(
        self,
        exc_type: Optional[type],
        exc: Optional[Exception],
        tb: Optional[Any],
    ) -> bool:
        """
        退出上下文管理器，处理收集的错误

        Args:
            exc_type: 异常类型
            exc: 异常对象
            tb: 追溯对象

        Returns:
            是否吞掉异常（由 suppress 参数决定）
        """
        # 未捕获异常也纳入收集
        if exc is not None:
            collect_error(exc, f"{self.context}（未捕获异常）")
            # 打印详细错误
            print_detailed_error(
                exc, self.context, self.wechat_notifier, self.config
            )

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
def error_collection(
    context: str = "",
    wechat_notifier: Optional[Any] = None,
    config: Optional[Dict[str, Any]] = None,
    auto_send: bool = True,
    suppress: bool = False,
):
    """
    函数式便捷用法（ErrorCollector 的便捷包装器）

    使用示例：
        with error_collection("ctx", notifier, config) as ec:
            try:
                # 业务代码
                ...
            except Exception as e:
                ec.capture(e, "子步骤说明")

    Args:
        context: 错误上下文信息
        wechat_notifier: 微信通知器实例
        config: 配置信息
        auto_send: 是否自动发送收集的错误
        suppress: 是否吞掉异常

    Yields:
        ErrorCollector 实例
    """
    with ErrorCollector(
        context, wechat_notifier, config, auto_send, suppress
    ) as ec:
        yield ec
