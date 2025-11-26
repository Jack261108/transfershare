#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置文件验证工具
检查 config.json 是否有效，并提供诊断信息
"""

import json
import os
import sys
import re
from pathlib import Path


class ConfigValidator:
    """配置文件验证器"""

    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.config = None
        self.errors = []
        self.warnings = []
        self.info_messages = []

    def load_config(self):
        """加载配置文件"""
        if not os.path.exists(self.config_path):
            self.errors.append(f"❌ 配置文件不存在: {self.config_path}")
            return False

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
            self.info_messages.append(f"✅ 成功加载配置文件: {self.config_path}")
            return True
        except json.JSONDecodeError as e:
            self.errors.append(f"❌ JSON 格式错误: {str(e)}")
            return False
        except Exception as e:
            self.errors.append(f"❌ 读取文件失败: {str(e)}")
            return False

    def validate_cookies(self):
        """验证 Cookies"""
        cookies = self.config.get("cookies") or self.config.get("BAIDU_COOKIES")

        if not cookies:
            self.errors.append("❌ 缺少 cookies 字段 (cookies 或 BAIDU_COOKIES)")
            return False

        if not isinstance(cookies, str):
            self.errors.append(
                f"❌ cookies 必须是字符串，当前类型: {type(cookies).__name__}"
            )
            return False

        # 检查必需的 Cookie 值
        if "BDUSS" not in cookies:
            self.errors.append("❌ Cookies 中缺少 BDUSS")
            return False

        if "STOKEN" not in cookies:
            self.errors.append("❌ Cookies 中缺少 STOKEN")
            return False

        # 统计 Cookie 个数
        cookie_count = len([x for x in cookies.split(";") if "=" in x])
        self.info_messages.append(f"✅ Cookies 有效 (包含 {cookie_count} 个值)")
        return True

    def validate_share_urls(self):
        """验证分享链接"""
        share_urls = self.config.get("share_urls") or self.config.get("SHARE_URLS")

        if not share_urls:
            self.errors.append("❌ 缺少 share_urls 字段 (share_urls 或 SHARE_URLS)")
            return False

        urls = []

        # 处理不同格式
        if isinstance(share_urls, list):
            urls = share_urls
        elif isinstance(share_urls, str):
            # 多行或逗号分隔
            if "," in share_urls:
                urls = [x.strip() for x in share_urls.split(",") if x.strip()]
            else:
                urls = [x.strip() for x in share_urls.split("\n") if x.strip()]
        else:
            self.errors.append(
                f"❌ share_urls 格式错误，应为列表或字符串，当前类型: {type(share_urls).__name__}"
            )
            return False

        if not urls:
            self.errors.append("❌ share_urls 为空")
            return False

        # 验证每个 URL
        valid_urls = 0
        for idx, url in enumerate(urls, 1):
            if isinstance(url, dict):
                # 对象格式
                if "share_url" not in url:
                    self.errors.append(f"❌ 第 {idx} 个链接缺少 share_url 字段")
                    continue
                url_str = url.get("share_url", "")
            else:
                url_str = str(url)

            # 提取链接部分（去掉目录）
            url_match = re.search(r"https://pan\.baidu\.com/s/[A-Za-z0-9_-]+", url_str)
            if url_match:
                valid_urls += 1
            else:
                self.warnings.append(
                    f"⚠️  第 {idx} 个链接格式可能不正确: {url_str[:50]}..."
                )

        if valid_urls == 0:
            self.errors.append("❌ 没有找到有效的分享链接")
            return False

        self.info_messages.append(
            f"✅ 分享链接有效 (共 {len(urls)} 个，其中 {valid_urls} 个有效)"
        )
        return True

    def validate_save_dir(self):
        """验证保存目录"""
        save_dir = self.config.get("save_dir") or self.config.get(
            "SAVE_DIR", "/AutoTransfer"
        )

        if not save_dir:
            self.warnings.append("⚠️  未指定保存目录，将使用默认值: /AutoTransfer")
            return True

        if not isinstance(save_dir, str):
            self.errors.append(
                f"❌ save_dir 必须是字符串，当前类型: {type(save_dir).__name__}"
            )
            return False

        if not save_dir.startswith("/"):
            self.warnings.append(f"⚠️  保存目录不以 / 开头，可能导致问题: {save_dir}")

        self.info_messages.append(f"✅ 保存目录有效: {save_dir}")
        return True

    def validate_wechat_webhook(self):
        """验证企业微信 Webhook"""
        webhook = self.config.get("wechat_webhook") or self.config.get("WECHAT_WEBHOOK")

        if not webhook:
            self.info_messages.append("ℹ️  未配置企业微信通知 (可选，不影响转存)")
            return True

        if not isinstance(webhook, str):
            self.errors.append(
                f"❌ wechat_webhook 必须是字符串，当前类型: {type(webhook).__name__}"
            )
            return False

        if "qyapi.weixin.qq.com" not in webhook:
            self.warnings.append("⚠️  企业微信 Webhook 格式可能不正确")
            return False

        self.info_messages.append("✅ 企业微信 Webhook 有效")
        return True

    def validate_regex_patterns(self):
        """验证正则表达式"""
        regex_pattern = self.config.get("regex_pattern")
        regex_replace = self.config.get("regex_replace")

        if not regex_pattern:
            self.info_messages.append("ℹ️  未设置文件过滤规则 (可选)")
            return True

        # 验证 regex_pattern
        try:
            re.compile(regex_pattern)
            self.info_messages.append(f"✅ 正则过滤规则有效: {regex_pattern}")
        except re.error as e:
            self.errors.append(f"❌ 正则表达式错误: {str(e)}")
            return False

        # 验证 regex_replace
        if regex_replace:
            try:
                # 简单测试
                test_str = "test_file.mp4"
                re.sub(regex_pattern, regex_replace, test_str)
                self.info_messages.append(f"✅ 正则替换规则有效: {regex_replace}")
            except Exception as e:
                self.warnings.append(f"⚠️  正则替换规则可能有问题: {str(e)}")

        return True

    def validate_folder_filter(self):
        """验证文件夹过滤规则"""
        folder_filter = self.config.get("folder_filter")

        if not folder_filter:
            self.info_messages.append("ℹ️  未设置文件夹过滤规则 (可选)")
            return True

        if isinstance(folder_filter, str):
            try:
                re.compile(folder_filter)
                self.info_messages.append(f"✅ 文件夹过滤规则有效: {folder_filter}")
            except re.error as e:
                self.errors.append(f"❌ 文件夹过滤规则错误: {str(e)}")
                return False
        elif isinstance(folder_filter, list):
            for idx, pattern in enumerate(folder_filter, 1):
                try:
                    re.compile(pattern)
                except re.error as e:
                    self.errors.append(f"❌ 第 {idx} 个文件夹过滤规则错误: {str(e)}")
                    return False
            self.info_messages.append(
                f"✅ 文件夹过滤规则有效 (共 {len(folder_filter)} 个)"
            )
        else:
            self.errors.append(
                f"❌ folder_filter 类型错误，应为字符串或列表，当前类型: {type(folder_filter).__name__}"
            )
            return False

        return True

    def validate_all(self):
        """执行所有验证"""
        if not self.load_config():
            return False

        # 执行所有验证
        results = [
            self.validate_cookies(),
            self.validate_share_urls(),
            self.validate_save_dir(),
            self.validate_wechat_webhook(),
            self.validate_regex_patterns(),
            self.validate_folder_filter(),
        ]

        return all(results)

    def print_report(self):
        """打印验证报告"""
        print("\n" + "=" * 60)
        print("📋 配置文件验证报告")
        print("=" * 60)

        # 信息消息
        if self.info_messages:
            print("\n📌 信息:")
            for msg in self.info_messages:
                print(f"  {msg}")

        # 警告信息
        if self.warnings:
            print("\n⚠️  警告:")
            for msg in self.warnings:
                print(f"  {msg}")

        # 错误信息
        if self.errors:
            print("\n❌ 错误:")
            for msg in self.errors:
                print(f"  {msg}")

        # 总结
        print("\n" + "-" * 60)
        if not self.errors:
            print("✅ 配置文件验证通过！")
            if self.warnings:
                print(f"⚠️  有 {len(self.warnings)} 个警告，建议检查")
            print("\n现在可以运行: python transfer_runner.py")
            return True
        else:
            print(f"❌ 配置文件验证失败 ({len(self.errors)} 个错误)")
            print("\n请修正错误后重试")
            return False

    def print_config_summary(self):
        """打印配置摘要"""
        if not self.config:
            return

        print("\n" + "=" * 60)
        print("📝 配置摘要")
        print("=" * 60)

        # Cookies 摘要
        cookies = self.config.get("cookies") or self.config.get("BAIDU_COOKIES", "")
        if cookies:
            cookie_count = len([x for x in cookies.split(";") if "=" in x])
            print(f"• Cookies: {cookie_count} 个值")

        # 分享链接摘要
        share_urls = self.config.get("share_urls") or self.config.get("SHARE_URLS", "")
        if isinstance(share_urls, list):
            print(f"• 分享链接: {len(share_urls)} 个")
        elif isinstance(share_urls, str):
            urls = [
                x.strip()
                for x in (
                    share_urls.split(",")
                    if "," in share_urls
                    else share_urls.split("\n")
                )
                if x.strip()
            ]
            print(f"• 分享链接: {len(urls)} 个")

        # 保存目录
        save_dir = self.config.get("save_dir") or self.config.get(
            "SAVE_DIR", "/AutoTransfer"
        )
        print(f"• 保存目录: {save_dir}")

        # 企业微信通知
        webhook = self.config.get("wechat_webhook") or self.config.get("WECHAT_WEBHOOK")
        print(f"• 企业微信通知: {'已配置' if webhook else '未配置'}")

        # 文件过滤
        regex = self.config.get("regex_pattern")
        print(f"• 文件过滤: {'已配置' if regex else '未配置'}")

        # 文件夹过滤
        folder_filter = self.config.get("folder_filter")
        print(f"• 文件夹过滤: {'已配置' if folder_filter else '未配置'}")


def main():
    """主函数"""
    validator = ConfigValidator()

    # 执行验证
    is_valid = validator.validate_all()

    # 打印报告
    validator.print_report()

    # 如果验证通过，打印配置摘要
    if is_valid:
        validator.print_config_summary()

    print("\n" + "=" * 60 + "\n")

    # 返回退出码
    return 0 if is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
