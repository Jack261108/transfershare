#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# 日志级别定义
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# 日志格式 - 简化格式避免行截断问题
LOG_FORMAT = "[%(asctime)s] [%(levelname)-8s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 全局日志器
_logger = None


def _get_logger(
    name: str = "transfershare",
    level: str = "INFO",
    log_file: str = None,
    console_output: bool = True,
) -> logging.Logger:
    """获取或创建日志器

    Args:
        name: 日志器名称
        level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
        log_file: 日志文件路径（可选）
        console_output: 是否输出到控制台

    Returns:
        配置好的日志器实例
    """
    global _logger

    if _logger is not None:
        return _logger

    _logger = logging.getLogger(name)
    _logger.setLevel(LOG_LEVELS.get(level.upper(), logging.INFO))
    _logger.handlers.clear()

    # 格式化器
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # 控制台输出
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(LOG_LEVELS.get(level.upper(), logging.INFO))
        console_handler.setFormatter(formatter)
        # 确保每条日志立即输出，避免缓冲问题
        console_handler.flush()
        _logger.addHandler(console_handler)

    # 文件输出
    if log_file:
        try:
            log_path = Path(log_file).parent
            log_path.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            _logger.addHandler(file_handler)
        except Exception as e:
            _logger.warning(f"无法创建日志文件 {log_file}: {e}")

    # 防止日志传播到根日志器
    _logger.propagate = False

    # 启用 flush=True 确保日志立即输出
    for handler in _logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.stream.flush = sys.stdout.flush

    return _logger


def get_logger(name: str = "transfershare") -> logging.Logger:
    """获取日志器实例"""
    global _logger
    if _logger is None:
        _logger = _get_logger(name)
    return _logger


def setup_logging(
    level: str = "INFO",
    log_file: str = None,
    console_output: bool = True,
) -> logging.Logger:
    """配置日志系统

    Args:
        level: 日志级别
        log_file: 日志文件路径
        console_output: 是否输出到控制台

    Returns:
        配置好的日志器实例
    """
    return _get_logger("transfershare", level, log_file, console_output)


def log_startup(version: str = None) -> None:
    """记录启动信息"""
    logger = get_logger()
    tz = ZoneInfo("Asia/Shanghai")
    timestamp = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    logger.info("=" * 50)
    logger.info("百度网盘自动转存任务开始")
    if version:
        logger.info(f"版本: {version}")
    logger.info(f"执行时间: {timestamp}")
    logger.info("=" * 50)


def log_shutdown(success: bool = True) -> None:
    """记录关闭info信息"""
    logger = get_logger()
    tz = ZoneInfo("Asia/Shanghai")
    timestamp = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    status = "成功完成" if success else "异常中断"
    logger.info("=" * 50)
    logger.info(f"任务{status}")
    logger.info(f"结束时间: {timestamp}")
    logger.info("=" * 50)


def log_config_loaded(config: dict = None) -> None:
    """记录配置加载信息"""
    logger = get_logger()
    logger.info("配置信息:")
    if config:
        if config.get("cookies"):
            logger.debug("✓ Cookies 已配置")
        if config.get("share_urls"):
            share_count = (
                len(config["share_urls"])
                if isinstance(config["share_urls"], list)
                else len(
                    [
                        x.strip()
                        for x in str(config["share_urls"]).split("\n")
                        if x.strip()
                    ]
                )
            )
            logger.info(f"  分享链接数量: {share_count} 个")
        if config.get("save_dir"):
            logger.info(f"  保存目录: {config['save_dir']}")
        if config.get("regex_pattern"):
            logger.debug(f"  文件过滤规则: {config['regex_pattern']}")
        if config.get("wechat_webhook"):
            logger.debug("  ✓ 企业微信通知已配置")


def log_separator(char: str = "-", width: int = 60) -> None:
    """记录分隔线"""
    logger = get_logger()
    logger.info(char * width)
