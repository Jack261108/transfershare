#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from storage import BaiduStorage
from wechat_notifier import WeChatNotifier
from utils import handle_error_and_notify
from logger import (
    get_logger,
    setup_logging,
    log_startup,
    log_shutdown,
    log_config_loaded,
)


def get_env_config():
    """从环境变量获取配置"""
    config = {
        "cookies": os.getenv("BAIDU_COOKIES"),
        "share_urls": os.getenv("SHARE_URLS"),
        "save_dir": os.getenv("SAVE_DIR", "/AutoTransfer"),
        "wechat_webhook": os.getenv("WECHAT_WEBHOOK"),
    }

    # 检查必需的配置
    if not config["cookies"]:
        raise ValueError("BAIDU_COOKIES 环境变量未设置")
    if not config["share_urls"]:
        raise ValueError("SHARE_URLS 环境变量未设置")

    return config


def get_config():
    """优先使用本地 config.json；不存在时再读环境变量"""
    logger = get_logger()
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        cfg_path = os.path.join(base_dir, "config.json")
        if os.path.isfile(cfg_path):
            logger.info(f"检测到本地配置文件: {cfg_path}，优先使用本地配置")
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 兼容字段名，提供默认值
            cookies = data.get("cookies") or data.get("BAIDU_COOKIES")
            share_urls = data.get("share_urls") or data.get("SHARE_URLS")
            save_dir = data.get("save_dir") or data.get("SAVE_DIR", "/AutoTransfer")
            wechat_webhook = data.get("wechat_webhook") or data.get("WECHAT_WEBHOOK")

            # 全局高级参数（可选，会应用到所有链接）
            global_folder_filter = data.get("folder_filter")
            global_regex_pattern = data.get("regex_pattern")
            global_regex_replace = data.get("regex_replace")

            # 允许 share_urls 为列表或字符串（多行/逗号分隔）
            # 如果列表中的元素是对象（字典），则保留原样（支持高级配置如 folder_filter）
            # 如果列表中的元素是字符串，则转换为文本格式
            if isinstance(share_urls, list):
                # 检查是否包含对象配置（高级配置）
                has_objects = any(isinstance(item, dict) for item in share_urls)
                if has_objects:
                    # 包含对象配置，保留原样
                    pass  # share_urls 保持为列表
                else:
                    # 全是字符串，转换为文本格式
                    share_urls = "\n".join(
                        [s for s in share_urls if isinstance(s, str) and s.strip()]
                    )
            elif isinstance(share_urls, str):
                # 统一换行分隔，兼容用逗号分隔的情况
                if "," in share_urls and "\n" not in share_urls:
                    share_urls = "\n".join(
                        [x.strip() for x in share_urls.split(",") if x.strip()]
                    )
            else:
                share_urls = None

            cfg = {
                "cookies": cookies,
                "share_urls": share_urls,
                "save_dir": save_dir or "/AutoTransfer",
                "wechat_webhook": wechat_webhook,
                # 全局高级参数
                "folder_filter": global_folder_filter,
                "regex_pattern": global_regex_pattern,
                "regex_replace": global_regex_replace,
            }

            # 基本校验，与环境变量方式一致
            if not cfg["cookies"]:
                raise ValueError("配置文件缺少 cookies (cookies/BAIDU_COOKIES)")
            if not cfg["share_urls"]:
                raise ValueError("配置文件缺少 share_urls (share_urls/SHARE_URLS)")
            return cfg
    except Exception as e:
        logger = get_logger()
        logger.warning(f"读取本地配置文件失败，回退到环境变量: {e}")
    # 回退到环境变量
    return get_env_config()


def check_network_connectivity():
    """检查网络连通性"""
    try:
        import requests

        try:
            logger = get_logger()
        except Exception:
            logger = None

        # 检查是否在GitHub Actions环境
        if os.getenv("GITHUB_ACTIONS") == "true":
            msg = "检测到GitHub Actions环境，正在检查网络连通性..."
            if logger:
                logger.info(msg)
            else:
                print(msg)

            # 检查基本网络
            try:
                response = requests.get("https://www.baidu.com", timeout=10)
                if response.status_code == 200:
                    msg = "✅ 百度主站连通正常"
                    if logger:
                        logger.info(msg)
                    else:
                        print(msg)
                else:
                    msg = f"⚠️ 百度主站连通异常: HTTP {response.status_code}"
                    if logger:
                        logger.warning(msg)
                    else:
                        print(msg)
            except Exception as e:
                msg = f"❌ 百度主站连通失败: {str(e)}"
                if logger:
                    logger.error(msg)
                else:
                    print(msg)

            # 检查百度网盘API
            try:
                response = requests.get("https://pan.baidu.com", timeout=10)
                if response.status_code == 200:
                    msg = "✅ 百度网盘连通正常"
                    if logger:
                        logger.info(msg)
                    else:
                        print(msg)
                else:
                    msg = f"⚠️ 百度网盘连通异常: HTTP {response.status_code}"
                    if logger:
                        logger.warning(msg)
                    else:
                        print(msg)
            except Exception as e:
                msg = f"❌ 百度网盘连通失败: {str(e)}"
                if logger:
                    logger.error(msg)
                else:
                    print(msg)
                msg2 = "提示: GitHub Actions环境可能存在网络访问限制"
                if logger:
                    logger.info(msg2)
                else:
                    print(msg2)

    except ImportError:
        try:
            logger = get_logger()
            logger.debug("网络检查跳过: requests库不可用")
        except Exception:
            print("网络检查跳过: requests库不可用")
    except Exception as e:
        try:
            logger = get_logger()
            logger.error(f"网络检查异常: {str(e)}")
        except Exception:
            print(f"网络检查异常: {str(e)}")


def progress_callback(level, message):
    """进度回调函数 - 实时输出进度信息"""
    print(f"[{(level or 'INFO').upper()}] {message}")
        

def main():
    """主函数"""
    setup_logging()
    logger = get_logger()
    log_startup()

    # 检查网络连通性
    check_network_connectivity()

    config = None
    notifier = None

    try:
        # 获取配置（优先本地 config.json）
        config = get_config()
        log_config_loaded(config)
        # 修复f-string中不能使用反斜杠的问题
        newline = "\n"
        share_count = (
            len(config["share_urls"].strip().split(newline))
            if config["share_urls"]
            else 0
        )
        logger.info(
            f"  企业微信通知: {'已配置' if config['wechat_webhook'] else '未配置'}"
        )

        # 初始化企业微信通知器
        if config["wechat_webhook"]:
            notifier = WeChatNotifier(config["wechat_webhook"])
            logger.info("企业微信通知器初始化成功")

        # 初始化存储客户端
        logger.info("初始化百度网盘客户端...")
        storage = BaiduStorage(config["cookies"], config["wechat_webhook"])

        if not storage.is_valid():
            raise Exception("百度网盘客户端初始化失败，请检查cookies是否有效")

        # 获取网盘信息
        quota_info = storage.get_quota_info()
        if quota_info:
            logger.info(
                f"网盘空间: {quota_info['used_gb']}GB / {quota_info['total_gb']}GB"
            )

        # 执行转存
        logger.info("开始执行批量转存任务...")

        # 检查 share_urls 是否为对象数组（高级配置）
        share_urls = config["share_urls"]
        global_folder_filter = config.get("folder_filter")
        global_regex_pattern = config.get("regex_pattern")
        global_regex_replace = config.get("regex_replace")

        if (
            isinstance(share_urls, list)
            and len(share_urls) > 0
            and isinstance(share_urls[0], dict)
        ):
            # 高级配置模式：直接传递配置对象数组
            # 为每个配置添加默认值（如果未指定）
            for share_config in share_urls:
                if "save_dir" not in share_config or not share_config["save_dir"]:
                    share_config["save_dir"] = config["save_dir"]
                # 应用全局高级参数（如果链接配置中没有指定）
                if global_folder_filter and "folder_filter" not in share_config:
                    share_config["folder_filter"] = global_folder_filter
                if global_regex_pattern and "regex_pattern" not in share_config:
                    share_config["regex_pattern"] = global_regex_pattern
                if (
                    global_regex_replace is not None
                    and "regex_replace" not in share_config
                ):
                    share_config["regex_replace"] = global_regex_replace
            result = storage.transfer_multiple_shares(
                share_configs=share_urls,
                progress_callback=progress_callback,
            )
        else:
            # 文本模式：从文本解析分享链接，然后转换为配置对象数组
            # 如果设置了全局高级参数，需要转换为对象数组格式
            text_content = (
                share_urls
                if isinstance(share_urls, str)
                else "\n".join(share_urls) if isinstance(share_urls, list) else ""
            )
            parsed_configs = storage.parse_share_links_from_text(
                text_content, config["save_dir"]
            )

            # 如果有全局高级参数，应用它们
            if (
                global_folder_filter
                or global_regex_pattern
                or global_regex_replace is not None
            ):
                for share_config in parsed_configs:
                    if global_folder_filter and "folder_filter" not in share_config:
                        share_config["folder_filter"] = global_folder_filter
                    if global_regex_pattern and "regex_pattern" not in share_config:
                        share_config["regex_pattern"] = global_regex_pattern
                    if (
                        global_regex_replace is not None
                        and "regex_replace" not in share_config
                    ):
                        share_config["regex_replace"] = global_regex_replace
                # 使用对象数组模式
                result = storage.transfer_multiple_shares(
                    share_configs=parsed_configs,
                    progress_callback=progress_callback,
                )
            else:
                # 没有全局高级参数，使用文本模式
                result = storage.transfer_shares_from_text(
                    text=text_content,
                    default_save_dir=config["save_dir"],
                    progress_callback=progress_callback,
                )

        # 处理结果
        if result["success"]:
            if result.get("skipped"):
                logger.info(
                    f"✅ 任务完成: {result.get('message', result.get('summary', '转存完成'))}"
                )
            else:
                # 批量转存的结果可能包含多个文件
                if "results" in result:
                    # 显示整体结果
                    logger.info(f"🎉 批量转存成功: {result['summary']}")
                    successful_results = [
                        r
                        for r in result["results"]
                        if r.get("success") and not r.get("skipped")
                    ]
                    all_transferred_files = []
                    for res in successful_results:
                        if "transferred_files" in res:
                            all_transferred_files.extend(res["transferred_files"])

                    if all_transferred_files:
                        logger.info(f"转存文件列表 ({len(all_transferred_files)}个):")
                        for i, file in enumerate(
                            all_transferred_files[:10], 1
                        ):  # 只显示前10个
                            logger.info(f"  {i}. {file}")
                        if len(all_transferred_files) > 10:
                            logger.info(
                                f"  ... 还有 {len(all_transferred_files) - 10} 个文件"
                            )
                else:
                    # 单个转存的结果
                    transferred_files = result.get("transferred_files", [])
                    logger.info(
                        f"🎉 转存成功: {result.get('message', result.get('summary', '转存成功'))}"
                    )
                    if transferred_files:
                        logger.info(f"转存文件列表 ({len(transferred_files)}个):")
                        for i, file in enumerate(
                            transferred_files[:10], 1
                        ):  # 只显示前10个
                            logger.info(f"  {i}. {file}")
                        if len(transferred_files) > 10:
                            logger.info(
                                f"  ... 还有 {len(transferred_files) - 10} 个文件"
                            )
        else:
            error_msg = result.get("error", result.get("summary", "未知错误"))
            logger.error(f"❌ 转存失败: {error_msg}")

        # 发送企业微信通知（聚合发送策略：仅在任务结束发送一次总结）
        if notifier:
            logger.info("发送企业微信通知...")
            notification_sent = notifier.send_transfer_result(result, config)
            if not notification_sent:
                logger.warning("企业微信通知发送失败")

        # 如果转存失败，退出程序
        if not result["success"]:
            # 非成功结果也统一走 finally，通知在结尾统一发送
            sys.exit(1)

    except Exception as e:
        # 不在 ErrorCollector 作用域内，直接发送错误通知
        handle_error_and_notify(e, "主任务执行失败", notifier, config, collect=False)
        sys.exit(1)

    finally:
        log_shutdown()


if __name__ == "__main__":
    main()
