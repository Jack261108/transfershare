#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
from datetime import datetime
from storage import BaiduStorage
from wechat_notifier import WeChatNotifier




def get_env_config():
    """从环境变量获取配置"""
    config = {
        'cookies': os.getenv('BAIDU_COOKIES'),
        'share_urls': os.getenv('SHARE_URLS'),
        'save_dir': os.getenv('SAVE_DIR', '/AutoTransfer'),
        'wechat_webhook': os.getenv('WECHAT_WEBHOOK')
    }
    
    # 检查必需的配置
    if not config['cookies']:
        raise ValueError("BAIDU_COOKIES 环境变量未设置")
    if not config['share_urls']:
        raise ValueError("SHARE_URLS 环境变量未设置")
    
    return config

def progress_callback(level, message):
    """进度回调函数"""
    # 简化输出，不使用日志系统
    if level == 'error':
        print(f"错误: {message}")
    elif level == 'warning':
        print(f"警告: {message}")
    elif level == 'success':
        print(f"成功: {message}")
    else:
        print(f"信息: {message}")

def main():
    """主函数"""
    print("=" * 60)
    print("百度网盘自动转存任务开始")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    config = None
    notifier = None
    
    try:
        # 获取配置
        config = get_env_config()
        print("配置信息:")
        # 修复f-string中不能使用反斜杠的问题
        newline = '\n'
        share_count = len(config['share_urls'].strip().split(newline)) if config['share_urls'] else 0
        print(f"  分享链接数量: {share_count} 个")
        print(f"  保存目录: {config['save_dir']}")
        print(f"  企业微信通知: {'已配置' if config['wechat_webhook'] else '未配置'}")
        
        # 初始化企业微信通知器
        if config['wechat_webhook']:
            notifier = WeChatNotifier(config['wechat_webhook'])
            print("企业微信通知器初始化成功")
        
        # 初始化存储客户端
        print("初始化百度网盘客户端...")
        storage = BaiduStorage(config['cookies'])
        
        if not storage.is_valid():
            raise Exception("百度网盘客户端初始化失败，请检查cookies是否有效")
        
        # 获取网盘信息
        quota_info = storage.get_quota_info()
        if quota_info:
            print(f"网盘空间: {quota_info['used_gb']}GB / {quota_info['total_gb']}GB")
        
        # 执行转存
        print("开始执行批量转存任务...")
        result = storage.transfer_shares_from_text(
            text=config['share_urls'],
            default_save_dir=config['save_dir'],
            progress_callback=progress_callback
        )
        
        # 处理结果
        if result['success']:
            if result.get('skipped'):
                print(f"✅ 任务完成: {result['message']}")
            else:
                transferred_files = result.get('transferred_files', [])
                print(f"🎉 转存成功: {result['message']}")
                if transferred_files:
                    print(f"转存文件列表 ({len(transferred_files)}个):")
                    for i, file in enumerate(transferred_files[:10], 1):  # 只显示前10个
                        print(f"  {i}. {file}")
                    if len(transferred_files) > 10:
                        print(f"  ... 还有 {len(transferred_files) - 10} 个文件")
        else:
            error_msg = result.get('error', '未知错误')
            print(f"❌ 转存失败: {error_msg}")
        
        # 发送企业微信通知
        if notifier:
            print("发送企业微信通知...")
            notification_sent = notifier.send_transfer_result(result, config)
            if not notification_sent:
                print("企业微信通知发送失败")
        
        # 如果转存失败，退出程序
        if not result['success']:
            sys.exit(1)
            
    except Exception as e:
        error_msg = str(e)
        print(f"❌ 任务执行失败: {error_msg}")
        
        # 发送错误通知
        if notifier and config:
            print("发送错误通知到企业微信...")
            notifier.send_error_notification(error_msg, config)
        
        sys.exit(1)
    
    finally:
        print("=" * 60)
        print("百度网盘自动转存任务结束")
        print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

if __name__ == "__main__":
    main()