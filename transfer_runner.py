#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
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
from config_utils import load_runtime_config


def check_network_connectivity():
    """检查网络连通性"""
    try:
        import requests

        try:
            logger = get_logger()
        except Exception:
            logger = None

        if os.getenv("GITHUB_ACTIONS") == "true":
            msg = "检测到GitHub Actions环境，正在检查网络连通性..."
            if logger:
                logger.info(msg)
            else:
                print(msg)

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

    check_network_connectivity()

    config = None
    notifier = None
    run_success = False

    try:
        config = load_runtime_config()
        if config.get("config_source") == "file":
            logger.info(f"检测到本地配置文件: {config['config_path']}，优先使用本地配置")
        elif config.get("config_load_warning"):
            logger.warning(
                f"读取本地配置文件失败，回退到环境变量: {config['config_load_warning']}"
            )

        log_config_loaded(config)
        logger.info(
            f"  企业微信通知: {'已配置' if config['wechat_webhook'] else '未配置'}"
        )

        if config["wechat_webhook"]:
            notifier = WeChatNotifier(config["wechat_webhook"])
            logger.info("企业微信通知器初始化成功")

        logger.info("初始化百度网盘客户端...")
        storage = BaiduStorage(config["cookies"], config["wechat_webhook"])

        if not storage.is_valid():
            raise Exception("百度网盘客户端初始化失败，请检查cookies是否有效")

        quota_info = storage.get_quota_info()
        if quota_info:
            logger.info(
                f"网盘空间: {quota_info['used_gb']}GB / {quota_info['total_gb']}GB"
            )

        logger.info("开始执行批量转存任务...")
        result = storage.transfer_multiple_shares(
            share_configs=config["share_configs"],
            progress_callback=progress_callback,
        )

        if result["success"]:
            if result.get("skipped"):
                logger.info(
                    f"✅ 任务完成: {result.get('message', result.get('summary', '转存完成'))}"
                )
            else:
                if "results" in result:
                    logger.info(f"🎉 批量转存成功: {result['summary']}")
                    successful_results = [
                        item
                        for item in result["results"]
                        if item.get("success") and not item.get("skipped")
                    ]
                    all_transferred_files = []
                    for res in successful_results:
                        if "transferred_files" in res:
                            all_transferred_files.extend(res["transferred_files"])

                    if all_transferred_files:
                        logger.info(f"转存文件列表 ({len(all_transferred_files)}个):")
                        for index, file in enumerate(all_transferred_files[:10], 1):
                            logger.info(f"  {index}. {file}")
                        if len(all_transferred_files) > 10:
                            logger.info(
                                f"  ... 还有 {len(all_transferred_files) - 10} 个文件"
                            )
                else:
                    transferred_files = result.get("transferred_files", [])
                    logger.info(
                        f"🎉 转存成功: {result.get('message', result.get('summary', '转存成功'))}"
                    )
                    if transferred_files:
                        logger.info(f"转存文件列表 ({len(transferred_files)}个):")
                        for index, file in enumerate(transferred_files[:10], 1):
                            logger.info(f"  {index}. {file}")
                        if len(transferred_files) > 10:
                            logger.info(
                                f"  ... 还有 {len(transferred_files) - 10} 个文件"
                            )
        else:
            error_msg = result.get("error", result.get("summary", "未知错误"))
            logger.error(f"❌ 转存失败: {error_msg}")

        if notifier:
            logger.info("发送企业微信通知...")
            notification_sent = notifier.send_transfer_result(result, config)
            if not notification_sent:
                logger.warning("企业微信通知发送失败")

        if not result["success"]:
            sys.exit(1)

        run_success = True

    except Exception as e:
        handle_error_and_notify(e, "主任务执行失败", notifier, config, collect=False)
        sys.exit(1)

    finally:
        log_shutdown(success=run_success)


if __name__ == "__main__":
    main()
