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
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        cfg_path = os.path.join(base_dir, "config.json")
        if os.path.isfile(cfg_path):
            print(f"检测到本地配置文件: {cfg_path}，优先使用本地配置")
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 兼容字段名，提供默认值
            cookies = data.get("cookies") or data.get("BAIDU_COOKIES")
            share_urls = data.get("share_urls") or data.get("SHARE_URLS")
            save_dir = data.get("save_dir") or data.get("SAVE_DIR", "/AutoTransfer")
            wechat_webhook = data.get("wechat_webhook") or data.get("WECHAT_WEBHOOK")

            # 允许 share_urls 为列表或字符串（多行/逗号分隔）
            if isinstance(share_urls, list):
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
            }

            # 基本校验，与环境变量方式一致
            if not cfg["cookies"]:
                raise ValueError("配置文件缺少 cookies (cookies/BAIDU_COOKIES)")
            if not cfg["share_urls"]:
                raise ValueError("配置文件缺少 share_urls (share_urls/SHARE_URLS)")
            return cfg
    except Exception as e:
        print(f"读取本地配置文件失败，回退到环境变量: {e}")
    # 回退到环境变量
    return get_env_config()


def check_network_connectivity():
    """检查网络连通性"""
    try:
        import requests

        # 检查是否在GitHub Actions环境
        if os.getenv("GITHUB_ACTIONS") == "true":
            print("检测到GitHub Actions环境，正在检查网络连通性...")

            # 检查基本网络
            try:
                response = requests.get("https://www.baidu.com", timeout=10)
                if response.status_code == 200:
                    print("✅ 百度主站连通正常")
                else:
                    print(f"⚠️ 百度主站连通异常: HTTP {response.status_code}")
            except Exception as e:
                print(f"❌ 百度主站连通失败: {str(object=e)}")

            # 检查百度网盘API
            try:
                response = requests.get("https://pan.baidu.com", timeout=10)
                if response.status_code == 200:
                    print("✅ 百度网盘连通正常")
                else:
                    print(f"⚠️ 百度网盘连通异常: HTTP {response.status_code}")
            except Exception as e:
                print(f"❌ 百度网盘连通失败: {str(e)}")
                print("提示: GitHub Actions环境可能存在网络访问限制")

    except ImportError:
        print("网络检查跳过: requests库不可用")
    except Exception as e:
        print(f"网络检查异常: {str(e)}")


def progress_callback(level, message):
    """进度回调函数"""
    # 简化输出，不使用日志系统
    if level == "error":
        print(f"错误: {message}")
    elif level == "warning":
        print(f"警告: {message}")
    elif level == "success":
        print(f"成功: {message}")
    else:
        print(f"信息: {message}")


def main():
    """主函数"""
    print("=" * 60)
    print("百度网盘自动转存任务开始")
    print(
        f"执行时间: {datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')}"
    )
    print("=" * 60)

    # 检查网络连通性
    check_network_connectivity()

    config = None
    notifier = None

    try:
        # 获取配置（优先本地 config.json）
        config = get_config()
        print("配置信息:")
        # 修复f-string中不能使用反斜杠的问题
        newline = "\n"
        share_count = (
            len(config["share_urls"].strip().split(newline))
            if config["share_urls"]
            else 0
        )
        print(f"  分享链接数量: {share_count} 个")
        print(f"  保存目录: {config['save_dir']}")
        print(f"  企业微信通知: {'已配置' if config['wechat_webhook'] else '未配置'}")

        # 初始化企业微信通知器
        if config["wechat_webhook"]:
            notifier = WeChatNotifier(config["wechat_webhook"])
            print("企业微信通知器初始化成功")

        # 初始化存储客户端
        print("初始化百度网盘客户端...")
        storage = BaiduStorage(config["cookies"], config["wechat_webhook"])

        if not storage.is_valid():
            raise Exception("百度网盘客户端初始化失败，请检查cookies是否有效")

        # 获取网盘信息
        quota_info = storage.get_quota_info()
        if quota_info:
            print(f"网盘空间: {quota_info['used_gb']}GB / {quota_info['total_gb']}GB")

        # 执行转存
        print("开始执行批量转存任务...")
        result = storage.transfer_shares_from_text(
            text=config["share_urls"],
            default_save_dir=config["save_dir"],
            progress_callback=progress_callback,
        )

        # 处理结果
        if result["success"]:
            if result.get("skipped"):
                print(
                    f"✅ 任务完成: {result.get('message', result.get('summary', '转存完成'))}"
                )
            else:
                # 批量转存的结果可能包含多个文件
                if "results" in result:
                    # 显示整体结果
                    print(f"🎉 批量转存成功: {result['summary']}")
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
                        print(f"转存文件列表 ({len(all_transferred_files)}个):")
                        for i, file in enumerate(
                            all_transferred_files[:10], 1
                        ):  # 只显示前10个
                            print(f"  {i}. {file}")
                        if len(all_transferred_files) > 10:
                            print(
                                f"  ... 还有 {len(all_transferred_files) - 10} 个文件"
                            )
                else:
                    # 单个转存的结果
                    transferred_files = result.get("transferred_files", [])
                    print(
                        f"🎉 转存成功: {result.get('message', result.get('summary', '转存成功'))}"
                    )
                    if transferred_files:
                        print(f"转存文件列表 ({len(transferred_files)}个):")
                        for i, file in enumerate(
                            transferred_files[:10], 1
                        ):  # 只显示前10个
                            print(f"  {i}. {file}")
                        if len(transferred_files) > 10:
                            print(f"  ... 还有 {len(transferred_files) - 10} 个文件")
        else:
            error_msg = result.get("error", result.get("summary", "未知错误"))
            print(f"❌ 转存失败: {error_msg}")

        # 发送企业微信通知（聚合发送策略：仅在任务结束发送一次总结）
        if notifier:
            print("发送企业微信通知...")
            notification_sent = notifier.send_transfer_result(result, config)
            if not notification_sent:
                print("企业微信通知发送失败")

        # 如果转存失败，退出程序
        if not result["success"]:
            # 非成功结果也统一走 finally，通知在结尾统一发送
            sys.exit(1)

    except Exception as e:
        handle_error_and_notify(e, "主任务执行失败", notifier, config, collect=True)
        sys.exit(1)

    finally:
        print("=" * 60)
        print("百度网盘自动转存任务结束")
        print(
            f"结束时间: {datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print("=" * 60)


if __name__ == "__main__":
    main()
