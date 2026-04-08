#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置文件验证工具
检查 config.json 是否有效，并提供诊断信息
"""

import json
import sys
from config_utils import load_json_config, validate_runtime_config


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
        try:
            self.config = load_json_config(self.config_path)
            self.info_messages.append(f"✅ 成功加载配置文件: {self.config_path}")
            return True
        except FileNotFoundError as e:
            self.errors.append(f"❌ {str(e)}")
            return False
        except json.JSONDecodeError as e:
            self.errors.append(f"❌ JSON 格式错误: {str(e)}")
            return False
        except Exception as e:
            self.errors.append(f"❌ 读取文件失败: {str(e)}")
            return False

    def validate_all(self):
        """执行所有验证"""
        if not self.load_config():
            return False

        result = validate_runtime_config(self.config)
        self.config = result.get("config", self.config)
        self.errors.extend(result.get("errors", []))
        self.warnings.extend(result.get("warnings", []))
        self.info_messages.extend(result.get("info", []))
        return not self.errors

    def print_report(self):
        """打印验证报告"""
        print("\n" + "=" * 60)
        print("📋 配置文件验证报告")
        print("=" * 60)

        if self.info_messages:
            print("\n📌 信息:")
            for msg in self.info_messages:
                print(f"  {msg}")

        if self.warnings:
            print("\n⚠️  警告:")
            for msg in self.warnings:
                print(f"  {msg}")

        if self.errors:
            print("\n❌ 错误:")
            for msg in self.errors:
                print(f"  {msg}")

        print("\n" + "-" * 60)
        if not self.errors:
            print("✅ 配置文件验证通过！")
            if self.warnings:
                print(f"⚠️  有 {len(self.warnings)} 个警告，建议检查")
            print("\n现在可以运行: python transfer_runner.py")
            return True

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

        cookies = self.config.get("cookies", "")
        if cookies:
            cookie_count = len([item for item in cookies.split(";") if "=" in item])
            print(f"• Cookies: {cookie_count} 个值")

        print(f"• 分享链接: {self.config.get('share_count', 0)} 个")
        print(f"• 保存目录: {self.config.get('save_dir', '/AutoTransfer')}")
        print(
            f"• 企业微信通知: {'已配置' if self.config.get('wechat_webhook') else '未配置'}"
        )
        print(f"• 文件过滤: {'已配置' if self.config.get('regex_pattern') else '未配置'}")
        print(
            f"• 文件夹过滤: {'已配置' if self.config.get('folder_filter') else '未配置'}"
        )


def main():
    """主函数"""
    validator = ConfigValidator()
    is_valid = validator.validate_all()
    validator.print_report()

    if is_valid:
        validator.print_config_summary()

    print("\n" + "=" * 60 + "\n")
    return 0 if is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
