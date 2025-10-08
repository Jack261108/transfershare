#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
from datetime import datetime
from storage import BaiduStorage
from wechat_notifier import WeChatNotifier
from loguru import logger

def setup_logging():
    """设置日志配置"""
    # 创建logs目录
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # 配置loguru
    logger.remove()  # 移除默认handler
    
    # 添加控制台输出
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        level="INFO"
    )
    
    # 添加文件输出
    log_file = f"logs/transfer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="7 days"
    )
    
    return log_file

def get_env_config():
    """从环境变量获取配置"""
    config = {
        'cookies': os.getenv('BAIDU_COOKIES'),
        'share_url': os.getenv('SHARE_URL'),
        'share_password': os.getenv('SHARE_PASSWORD'),
        'save_dir': os.getenv('SAVE_DIR', '/AutoTransfer'),
        'wechat_webhook': os.getenv('WECHAT_WEBHOOK')
    }
    
    # 检查必需的配置
    if not config['cookies']:
        raise ValueError("BAIDU_COOKIES 环境变量未设置")
    if not config['share_url']:
        raise ValueError("SHARE_URL 环境变量未设置")
    
    return config

def progress_callback(level, message):
    """进度回调函数"""
    if level == 'error':
        logger.error(message)
    elif level == 'warning':
        logger.warning(message)
    elif level == 'success':
        logger.success(message)
    else:
        logger.info(message)

def main():
    """主函数"""
    log_file = setup_logging()
    logger.info("=" * 60)
    logger.info("百度网盘自动转存任务开始")
    logger.info(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"日志文件: {log_file}")
    logger.info("=" * 60)
    
    config = None
    notifier = None
    
    try:
        # 获取配置
        config = get_env_config()
        logger.info("配置信息:")
        logger.info(f"  分享链接: {config['share_url']}")
        logger.info(f"  保存目录: {config['save_dir']}")
        logger.info(f"  提取码: {'已设置' if config['share_password'] else '无'}")
        logger.info(f"  企业微信通知: {'已配置' if config['wechat_webhook'] else '未配置'}")
        
        # 初始化企业微信通知器
        if config['wechat_webhook']:
            notifier = WeChatNotifier(config['wechat_webhook'])
            logger.info("企业微信通知器初始化成功")
        
        # 初始化存储客户端
        logger.info("初始化百度网盘客户端...")
        storage = BaiduStorage(config['cookies'])
        
        if not storage.is_valid():
            raise Exception("百度网盘客户端初始化失败，请检查cookies是否有效")
        
        # 获取网盘信息
        quota_info = storage.get_quota_info()
        if quota_info:
            logger.info(f"网盘空间: {quota_info['used_gb']}GB / {quota_info['total_gb']}GB")
        
        # 执行转存
        logger.info("开始执行转存任务...")
        result = storage.transfer_share(
            share_url=config['share_url'],
            pwd=config['share_password'],
            save_dir=config['save_dir'],
            progress_callback=progress_callback
        )
        
        # 处理结果
        if result['success']:
            if result.get('skipped'):
                logger.info(f"✅ 任务完成: {result['message']}")
            else:
                transferred_files = result.get('transferred_files', [])
                logger.success(f"🎉 转存成功: {result['message']}")
                if transferred_files:
                    logger.info(f"转存文件列表 ({len(transferred_files)}个):")
                    for i, file in enumerate(transferred_files[:10], 1):  # 只显示前10个
                        logger.info(f"  {i}. {file}")
                    if len(transferred_files) > 10:
                        logger.info(f"  ... 还有 {len(transferred_files) - 10} 个文件")
        else:
            error_msg = result.get('error', '未知错误')
            logger.error(f"❌ 转存失败: {error_msg}")
        
        # 发送企业微信通知
        if notifier:
            logger.info("发送企业微信通知...")
            notification_sent = notifier.send_transfer_result(result, config)
            if not notification_sent:
                logger.warning("企业微信通知发送失败")
        
        # 如果转存失败，退出程序
        if not result['success']:
            sys.exit(1)
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ 任务执行失败: {error_msg}")
        logger.exception("详细错误信息:")
        
        # 发送错误通知
        if notifier and config:
            logger.info("发送错误通知到企业微信...")
            notifier.send_error_notification(error_msg, config)
        
        sys.exit(1)
    
    finally:
        logger.info("=" * 60)
        logger.info("百度网盘自动转存任务结束")
        logger.info(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 60)

if __name__ == "__main__":
    main()