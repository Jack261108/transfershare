from baidupcs_py.baidupcs import BaiduPCSApi
from baidupcs_py.baidupcs.errors import BaiduPCSError
from loguru import logger
import json
import os
import time
import re
import posixpath
from threading import Lock

class BaiduStorage:
    def __init__(self, cookies):
        self._client_lock = Lock()
        self.client = None
        self._init_client(cookies)
        self.last_request_time = 0
        self.min_request_interval = 2
        
    def _init_client(self, cookies):
        """初始化客户端"""
        with self._client_lock:
            try:
                cookies_dict = self._parse_cookies(cookies)
                if not self._validate_cookies(cookies_dict):
                    logger.error("cookies 无效")
                    return False
                    
                # 使用重试机制初始化客户端
                for retry in range(3):
                    try:
                        self.client = BaiduPCSApi(cookies=cookies_dict)
                        # 验证客户端
                        quota = self.client.quota()
                        total_gb = round(quota[0] / (1024**3), 2)
                        used_gb = round(quota[1] / (1024**3), 2)
                        logger.info(f"客户端初始化成功，网盘总空间: {total_gb}GB, 已使用: {used_gb}GB")
                        return True
                    except Exception as e:
                        if retry < 2:
                            logger.warning(f"客户端初始化失败，等待重试: {str(e)}")
                            time.sleep(3)
                        else:
                            logger.error(f"客户端初始化失败: {str(e)}")
                            return False
                            
            except Exception as e:
                logger.error(f"初始化客户端失败: {str(e)}")
                return False
            
    def _validate_cookies(self, cookies):
        """验证cookies是否有效
        Args:
            cookies: cookies字典
        Returns:
            bool: 是否有效
        """
        try:
            required_cookies = ['BDUSS', 'STOKEN']
            missing = [c for c in required_cookies if c not in cookies]
            if missing:
                logger.error(f'缺少必要的 cookies: {missing}')
                return False
            return True
        except Exception as e:
            logger.error(f"验证cookies失败: {str(e)}")
            return False
            
    def _parse_cookies(self, cookies_str):
        """解析 cookies 字符串为字典
        Args:
            cookies_str: cookies 字符串，格式如 'key1=value1; key2=value2'
        Returns:
            dict: cookies 字典
        """
        cookies = {}
        if not cookies_str:
            return cookies
            
        items = cookies_str.split(';')
        for item in items:
            if not item.strip():
                continue
            if '=' not in item:
                continue
            key, value = item.split('=', 1)
            cookies[key.strip()] = value.strip()
        return cookies

    def get_quota_info(self):
        """获取网盘配额信息"""
        try:
            if not self.client:
                return None
                
            quota_info = self.client.quota()
            if isinstance(quota_info, (tuple, list)):
                quota = {
                    'total': quota_info[0],
                    'used': quota_info[1],
                    'total_gb': round(quota_info[0] / (1024**3), 2),
                    'used_gb': round(quota_info[1] / (1024**3), 2)
                }
            else:
                quota = quota_info
                
            return quota
        except Exception as e:
            logger.error(f"获取配额信息失败: {str(e)}")
            return None
            
    def is_valid(self):
        """检查存储是否可用"""
        try:
            if not self.client:
                return False
                
            # 尝试获取配额信息来验证客户端是否有效
            quota_info = self.get_quota_info()
            return bool(quota_info)
                
        except Exception as e:
            logger.error(f"检查存储状态失败: {str(e)}")
            return False

    def _normalize_path(self, path, file_only=False):
        """标准化路径
        Args:
            path: 原始路径
            file_only: 是否只返回文件名
        Returns:
            str: 标准化后的路径
        """
        try:
            # 统一使用正斜杠，去除多余斜杠
            path = path.replace('\\', '/').strip('/')
            
            if file_only:
                # 只返回文件名
                return path.split('/')[-1]
            
            # 确保目录以 / 开头
            if not path.startswith('/'):
                path = '/' + path
            return path
        except Exception as e:
            logger.error(f"标准化路径失败: {str(e)}")
            return path

    def _ensure_dir_exists(self, path):
        """确保目录存在，如果不存在则创建
        Args:
            path: 目录路径
        Returns:
            bool: 是否成功
        """
        try:
            path = self._normalize_path(path)
            
            # 检查目录是否存在
            try:
                self.client.list(path)
                logger.debug(f"目录已存在: {path}")
                return True
            except Exception as e:
                if 'error_code: 31066' in str(e):  # 目录不存在
                    logger.info(f"目录不存在，开始创建: {path}")
                    try:
                        self.client.makedir(path)
                        logger.success(f"创建目录成功: {path}")
                        return True
                    except Exception as create_e:
                        if 'error_code: 31062' in str(create_e):  # 文件名非法
                            logger.error(f"目录名非法: {path}")
                        elif 'file already exists' in str(create_e).lower():
                            # 并发创建时可能发生
                            logger.debug(f"目录已存在（可能是并发创建）: {path}")
                            return True
                        elif 'no such file or directory' in str(create_e).lower():
                            # 需要创建父目录
                            parent_dir = os.path.dirname(path)
                            if parent_dir and parent_dir != '/':
                                logger.info(f"需要先创建父目录: {parent_dir}")
                                if self._ensure_dir_exists(parent_dir):
                                    # 父目录创建成功，重试创建当前目录
                                    return self._ensure_dir_exists(path)
                                else:
                                    logger.error(f"创建父目录失败: {parent_dir}")
                                    return False
                            logger.error(f"无法创建目录，父目录不存在: {path}")
                            return False
                        else:
                            logger.error(f"创建目录失败: {path}, 错误: {str(create_e)}")
                            return False
                else:
                    logger.error(f"检查目录失败: {path}, 错误: {str(e)}")
                    return False
                    
        except Exception as e:
            logger.error(f"确保目录存在时发生错误: {path}, 错误: {str(e)}")
            return False

    def _parse_share_error(self, error_str):
        """解析分享链接相关的错误信息，返回用户友好的错误消息
        Args:
            error_str: 原始错误信息字符串
        Returns:
            str: 用户友好的错误信息
        """
        try:
            # 检查错误码115（分享文件禁止分享）
            if 'error_code: 115' in error_str:
                return '分享链接已失效（文件禁止分享）'
            
            # 检查错误码145或errno: 145（分享链接失效）
            if 'error_code: 145' in error_str or "'errno': 145" in error_str:
                return '分享链接已失效'
            
            # 检查错误码200025（提取码错误）
            if 'error_code: 200025' in error_str or "'errno': 200025" in error_str:
                return '提取码输入错误，请检查提取码'
            
            # 检查其他常见分享错误
            if 'share' in error_str.lower() and 'not found' in error_str.lower():
                return '分享链接不存在或已失效'
                
            if 'password' in error_str.lower() and 'wrong' in error_str.lower():
                return '提取码错误'
                
            # 如果包含复杂的JSON错误信息，尝试简化
            if '{' in error_str and 'errno' in error_str:
                # 尝试提取错误码
                import re
                errno_match = re.search(r"'errno':\s*(\d+)", error_str)
                if errno_match:
                    errno = int(errno_match.group(1))
                    if errno == 145:
                        return '分享链接已失效'
                    elif errno == 200025:
                        return '提取码输入错误，请检查提取码'
                    elif errno == 115:
                        return '分享链接已失效（文件禁止分享）'
                    else:
                        return f'分享链接访问失败（错误码：{errno}）'
            
            # 如果没有匹配到特定错误，返回简化后的原始错误
            # 移除复杂的JSON信息
            if len(error_str) > 200 and '{' in error_str:
                return '分享链接访问失败，请检查链接和提取码'
            
            return error_str
            
        except Exception as e:
            logger.debug(f"解析分享错误信息失败: {str(e)}")
            return '分享链接访问失败，请检查链接和提取码'

    def _apply_regex_rules(self, file_path, regex_pattern=None, regex_replace=None):
        """应用正则处理规则
        Args:
            file_path: 原始文件路径
            regex_pattern: 正则表达式模式
            regex_replace: 替换字符串
        Returns:
            tuple: (should_transfer, final_path)
                should_transfer: 是否应该转存（False表示被过滤掉）
                final_path: 处理后的文件路径
        """
        try:
            if not regex_pattern:
                # 没有规则，直接返回原文件
                return True, file_path
            
            try:
                # 1. 尝试匹配
                match = re.search(regex_pattern, file_path)
                if not match:
                    # 匹配失败 = 文件被过滤掉
                    logger.debug(f"文件被正则规则过滤: {file_path} (规则: {regex_pattern})")
                    return False, file_path
                
                # 2. 匹配成功，检查是否需要重命名
                if regex_replace and regex_replace.strip():
                    # 有替换内容，执行重命名
                    new_path = re.sub(regex_pattern, regex_replace, file_path)
                    if new_path != file_path:
                        logger.debug(f"正则重命名: {file_path} -> {new_path}")
                        return True, new_path
                
                # 3. 匹配成功但无重命名，返回原路径
                return True, file_path
                
            except re.error as e:
                logger.warning(f"正则表达式错误: {regex_pattern}, 错误: {str(e)}")
                # 正则错误时不过滤，返回原文件
                return True, file_path
            
        except Exception as e:
            logger.error(f"应用正则规则时出错: {str(e)}")
            # 出错时返回原始路径，不影响正常流程
            return True, file_path

    def list_local_files(self, dir_path):
        """获取本地目录中的所有文件列表"""
        try:
            logger.debug(f"开始获取本地目录 {dir_path} 的文件列表")
            files = []
            
            # 检查目录是否存在
            try:
                # 尝试列出目录内容来检查是否存在
                self.client.list(dir_path)
            except Exception as e:
                if "No such file or directory" in str(e) or "-9" in str(e):
                    logger.info(f"本地目录 {dir_path} 不存在，将在转存时创建")
                    return []
                else:
                    logger.error(f"检查目录 {dir_path} 时出错: {str(e)}")
            
            def _list_dir(path):
                try:
                    content = self.client.list(path)
                    
                    for item in content:
                        if item.is_file:
                            # 只保留文件名进行对比
                            file_name = os.path.basename(item.path)
                            files.append(file_name)
                            logger.debug(f"记录本地文件: {file_name}")
                        elif item.is_dir:
                            _list_dir(item.path)
                            
                except Exception as e:
                    logger.error(f"列出目录 {path} 失败: {str(e)}")
                    raise
                    
            _list_dir(dir_path)
            
            # 有序展示文件列表
            if files:
                display_files = files[:20] if len(files) > 20 else files
                logger.info(f"本地目录 {dir_path} 扫描完成，找到 {len(files)} 个文件: {display_files}")
                if len(files) > 20:
                    logger.debug(f"... 还有 {len(files) - 20} 个文件未在日志中显示 ...")
            else:
                logger.info(f"本地目录 {dir_path} 扫描完成，未找到任何文件")
                
            return files
            
        except Exception as e:
            logger.error(f"获取本地文件列表失败: {str(e)}")
            return []
            
    def _extract_file_info(self, file_dict):
        """从文件字典中提取文件信息
        Args:
            file_dict: 文件信息字典
        Returns:
            dict: 标准化的文件信息
        """
        try:
            if isinstance(file_dict, dict):
                # 如果没有 server_filename，从路径中提取
                server_filename = file_dict.get('server_filename', '')
                if not server_filename and file_dict.get('path'):
                    server_filename = file_dict['path'].split('/')[-1]
                    
                return {
                    'server_filename': server_filename,
                    'fs_id': file_dict.get('fs_id', ''),
                    'path': file_dict.get('path', ''),
                    'size': file_dict.get('size', 0),
                    'isdir': file_dict.get('isdir', 0)
                }
            return None
        except Exception as e:
            logger.error(f"提取文件信息失败: {str(e)}")
            return None

    def _list_shared_dir_files(self, path, uk, share_id, bdstoken):
        """递归获取共享目录下的所有文件
        Args:
            path: 目录路径
            uk: 用户uk
            share_id: 分享ID
            bdstoken: token
        Returns:
            list: 文件列表
        """
        files = []
        try:
            # 分页获取所有文件
            page = 1
            page_size = 100
            all_sub_files = []
            
            while True:
                sub_paths = self.client.list_shared_paths(
                    path.path,
                    uk,
                    share_id,
                    bdstoken,
                    page=page,
                    size=page_size
                )
                
                if isinstance(sub_paths, list):
                    sub_files = sub_paths
                elif isinstance(sub_paths, dict):
                    sub_files = sub_paths.get('list', [])
                else:
                    logger.error(f"子目录内容格式错误: {type(sub_paths)}")
                    break
                
                if not sub_files:
                    # 没有更多文件了
                    break
                
                all_sub_files.extend(sub_files)
                
                # 如果当前页文件数少于页大小，说明已经是最后一页
                if len(sub_files) < page_size:
                    break
                
                page += 1
            
            logger.info(f"目录 {path.path} 共获取到 {len(all_sub_files)} 个文件/子目录")
            
            sub_files = all_sub_files
                
            for sub_file in sub_files:
                if hasattr(sub_file, '_asdict'):
                    sub_file_dict = sub_file._asdict()
                else:
                    sub_file_dict = sub_file if isinstance(sub_file, dict) else {}
                    
                # 如果是目录，递归获取
                if sub_file.is_dir:
                    logger.info(f"递归处理子目录: {sub_file.path}")
                    sub_dir_files = self._list_shared_dir_files(sub_file, uk, share_id, bdstoken)
                    files.extend(sub_dir_files)
                else:
                    # 如果是文件，添加到列表
                    file_info = self._extract_file_info(sub_file_dict)
                    if file_info:
                        # 去掉路径中的 sharelink 部分
                        file_info['path'] = re.sub(r'^/sharelink\d*-\d+/?', '', sub_file.path)
                        # 去掉开头的斜杠
                        file_info['path'] = file_info['path'].lstrip('/')
                        files.append(file_info)
                        logger.debug(f"记录共享文件: {file_info}")
                
        except Exception as e:
            logger.error(f"获取目录 {path.path} 内容失败: {str(e)}")
            
        return files

    def transfer_multiple_shares(self, share_configs, progress_callback=None):
        """
        批量转存多个分享链接
        Args:
            share_configs: 分享配置列表，每个配置包含:
                {
                    'share_url': str,      # 分享链接
                    'pwd': str,            # 提取码（可选）
                    'save_dir': str,       # 保存目录（可选）
                    'regex_pattern': str,  # 正则表达式（可选）
                    'regex_replace': str   # 正则替换（可选）
                }
            progress_callback: 进度回调函数
        Returns:
            dict: {
                'success': bool,          # 是否有成功的转存
                'total_count': int,       # 总链接数
                'success_count': int,     # 成功转存的链接数
                'failed_count': int,      # 失败的链接数
                'skipped_count': int,     # 跳过的链接数（无新文件）
                'results': list,          # 每个链接的详细结果
                'summary': str            # 总结信息
            }
        """
        try:
            if not share_configs or not isinstance(share_configs, list):
                return {
                    'success': False,
                    'error': '分享配置列表不能为空或格式错误',
                    'total_count': 0,
                    'success_count': 0,
                    'failed_count': 0,
                    'skipped_count': 0,
                    'results': []
                }
            
            total_count = len(share_configs)
            success_count = 0
            failed_count = 0
            skipped_count = 0
            results = []
            
            logger.info(f"=== 开始批量转存操作，共 {total_count} 个分享链接 ===")
            if progress_callback:
                progress_callback('info', f'开始批量转存，共 {total_count} 个分享链接')
            
            for index, config in enumerate(share_configs, 1):
                try:
                    # 验证配置
                    if not isinstance(config, dict) or 'share_url' not in config:
                        error_msg = f'第 {index} 个配置格式错误：缺少分享链接'
                        logger.error(error_msg)
                        results.append({
                            'index': index,
                            'share_url': config.get('share_url', '未知'),
                            'success': False,
                            'error': error_msg
                        })
                        failed_count += 1
                        continue
                    
                    share_url = config['share_url']
                    pwd = config.get('pwd')
                    save_dir = config.get('save_dir')
                    regex_pattern = config.get('regex_pattern')
                    regex_replace = config.get('regex_replace')
                    
                    logger.info(f"\n--- 处理第 {index}/{total_count} 个分享链接 ---")
                    logger.info(f"分享链接: {share_url}")
                    if pwd:
                        logger.info(f"提取码: {pwd}")
                    if save_dir:
                        logger.info(f"保存目录: {save_dir}")
                    
                    if progress_callback:
                        progress_callback('info', f'【{index}/{total_count}】处理分享链接: {share_url}')
                    
                    # 调用单个转存方法
                    result = self.transfer_share(
                        share_url=share_url,
                        pwd=pwd,
                        save_dir=save_dir,
                        progress_callback=progress_callback,
                        regex_pattern=regex_pattern,
                        regex_replace=regex_replace
                    )
                    
                    # 记录结果
                    result_record = {
                        'index': index,
                        'share_url': share_url,
                        'save_dir': save_dir,
                        'success': result.get('success', False),
                    }
                    
                    if result.get('success'):
                        if result.get('skipped'):
                            # 跳过（无新文件）
                            skipped_count += 1
                            result_record['skipped'] = True
                            result_record['message'] = result.get('message', '没有新文件需要转存')
                            logger.info(f"第 {index} 个链接转存跳过: {result.get('message')}")
                            if progress_callback:
                                progress_callback('info', f'【{index}/{total_count}】跳过: {result.get("message")}')
                        else:
                            # 成功
                            success_count += 1
                            result_record['message'] = result.get('message', '转存成功')
                            result_record['transferred_files'] = result.get('transferred_files', [])
                            logger.success(f"第 {index} 个链接转存成功: {result.get('message')}")
                            if progress_callback:
                                progress_callback('success', f'【{index}/{total_count}】成功: {result.get("message")}')
                    else:
                        # 失败
                        failed_count += 1
                        result_record['error'] = result.get('error', '未知错误')
                        logger.error(f"第 {index} 个链接转存失败: {result.get('error')}")
                        if progress_callback:
                            progress_callback('error', f'【{index}/{total_count}】失败: {result.get("error")}')
                    
                    results.append(result_record)
                    
                    # 链接间添加延迟，避免API限制
                    if index < total_count:
                        logger.debug("等待2秒后处理下一个链接...")
                        time.sleep(2)
                    
                except Exception as e:
                    error_msg = f'处理第 {index} 个分享链接时发生异常: {str(e)}'
                    logger.error(error_msg)
                    results.append({
                        'index': index,
                        'share_url': config.get('share_url', '未知'),
                        'success': False,
                        'error': error_msg
                    })
                    failed_count += 1
                    if progress_callback:
                        progress_callback('error', f'【{index}/{total_count}】异常: {str(e)}')
            
            # 生成总结信息
            summary_parts = []
            if success_count > 0:
                summary_parts.append(f'成功 {success_count} 个')
            if skipped_count > 0:
                summary_parts.append(f'跳过 {skipped_count} 个')
            if failed_count > 0:
                summary_parts.append(f'失败 {failed_count} 个')
            
            summary = f'批量转存完成：共 {total_count} 个链接，' + '、'.join(summary_parts)
            
            logger.info(f"\n=== 批量转存操作完成 ===")
            logger.info(summary)
            
            if progress_callback:
                if success_count > 0 or skipped_count > 0:
                    progress_callback('success', summary)
                else:
                    progress_callback('error', summary)
            
            return {
                'success': success_count > 0 or skipped_count > 0,
                'total_count': total_count,
                'success_count': success_count,
                'failed_count': failed_count,
                'skipped_count': skipped_count,
                'results': results,
                'summary': summary
            }
            
        except Exception as e:
            error_msg = f'批量转存操作失败: {str(e)}'
            logger.error(error_msg)
            if progress_callback:
                progress_callback('error', error_msg)
            return {
                'success': False,
                'error': error_msg,
                'total_count': len(share_configs) if share_configs else 0,
                'success_count': 0,
                'failed_count': 0,
                'skipped_count': 0,
                'results': []
            }

    def parse_share_links_from_text(self, text, default_save_dir=None):
        """
        从文本中解析分享链接，只支持 https://pan.baidu.com/s/xxxxx?pwd=xxxx 格式
        支持每个链接后面指定保存目录
        格式示例：
        https://pan.baidu.com/s/1NXEVkmQFfTeB9gvgBYdX0A?pwd=f9c7 /保存目录1
        https://pan.baidu.com/s/1example123?pwd=1234 /保存目录2
        
        Args:
            text: 包含分享链接的文本
            default_save_dir: 默认保存目录（当链接后没有指定目录时使用）
        Returns:
            list: 分享配置列表
        """
        try:
            share_configs = []
            
            # 只匹配带pwd参数的链接格式
            url_pattern = r'https://pan\.baidu\.com/s/[A-Za-z0-9_-]+\?pwd=[A-Za-z0-9]{4}'
            
            # 按行分割文本
            lines = text.strip().split('\n')
            
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line:
                    continue
                
                # 查找分享链接
                match = re.search(url_pattern, line)
                if not match:
                    continue
                
                url_with_pwd = match.group(0)
                
                # 分离URL和密码
                try:
                    share_url, pwd_part = url_with_pwd.split('?pwd=')
                    pwd = pwd_part[:4]  # 取前4位作为密码
                except ValueError:
                    logger.warning(f"第{line_num}行链接格式错误: {line}")
                    continue
                
                # 查找保存目录（在链接后面）
                save_dir = None
                
                # 尝试从同一行中提取目录
                remaining_text = line[match.end():].strip()
                if remaining_text and remaining_text.startswith('/'):
                    # 找到第一个空格或行尾作为目录结束
                    save_dir = remaining_text.split()[0]
                    logger.debug(f"从同一行提取到目录: {save_dir}")
                
                # 如果同一行没有目录，尝试查找下一行
                if not save_dir and line_num < len(lines):
                    next_line = lines[line_num].strip()
                    if next_line and next_line.startswith('/') and not re.search(url_pattern, next_line):
                        save_dir = next_line.split()[0]
                        logger.debug(f"从下一行提取到目录: {save_dir}")
                
                # 如果没有指定目录，使用默认目录
                if not save_dir:
                    save_dir = default_save_dir
                
                # 构建配置
                config = {
                    'share_url': share_url,
                    'pwd': pwd,
                    'line_number': line_num
                }
                
                if save_dir:
                    config['save_dir'] = save_dir
                
                share_configs.append(config)
                logger.debug(f"解析到分享链接（第{line_num}行）: {share_url}, 密码: {pwd}, 保存目录: {save_dir or '默认'}")
            
            logger.info(f"从文本中解析到 {len(share_configs)} 个分享链接")
            return share_configs
            
        except Exception as e:
            logger.error(f"解析分享链接失败: {str(e)}")
            return []

    def _generate_share_save_dir(self, share_url, base_dir=None, line_num=1):
        """
        为分享链接生成独立的保存目录
        Args:
            share_url: 分享链接
            base_dir: 基础目录
            line_num: 行号（用于备用命名）
        Returns:
            str: 生成的保存目录路径
        """
        try:
            # 设置默认基础目录
            if not base_dir:
                base_dir = '/AutoTransfer'
            
            # 从分享链接中提取标识符
            share_id = None
            
            # 处理不同格式的链接
            if '/s/' in share_url:
                # https://pan.baidu.com/s/1xxxxxxx 格式
                share_id = share_url.split('/s/')[-1]
                # 去除可能的参数
                if '?' in share_id:
                    share_id = share_id.split('?')[0]
            elif 'shareid=' in share_url:
                # https://pan.baidu.com/share/link?shareid=xxx&uk=xxx 格式
                import re
                match = re.search(r'shareid=(\d+)', share_url)
                if match:
                    share_id = match.group(1)
            
            if not share_id:
                # 如果无法提取标识符，使用行号
                share_id = f'share_{line_num}'
            
            # 限制标识符长度，避免目录名过长
            if len(share_id) > 20:
                share_id = share_id[:20]
            
            # 生成目录路径
            save_dir = f"{base_dir.rstrip('/')}/share_{share_id}"
            
            # 确保路径以 / 开头
            if not save_dir.startswith('/'):
                save_dir = '/' + save_dir
            
            logger.debug(f"为分享链接生成目录: {share_url} -> {save_dir}")
            return save_dir
            
        except Exception as e:
            logger.warning(f"生成保存目录失败: {str(e)}，使用默认目录")
            fallback_dir = f"{base_dir or '/AutoTransfer'}/share_{line_num}"
            if not fallback_dir.startswith('/'):
                fallback_dir = '/' + fallback_dir
            return fallback_dir

    def _generate_share_save_dir_by_name(self, share_url, pwd=None, base_dir=None, line_num=1):
        """
        根据分享文件名生成保存目录（需要访问网络）
        Args:
            share_url: 分享链接
            pwd: 提取码
            base_dir: 基础目录
            line_num: 行号（用于备用命名）
        Returns:
            str: 生成的保存目录路径
        """
        try:
            # 设置默认基础目录
            if not base_dir:
                base_dir = '/AutoTransfer'
            
            # 尝试获取分享文件的名称
            if self.client and self.is_valid():
                folder_info = self.get_share_folder_name(share_url, pwd)
                if folder_info.get('success') and folder_info.get('folder_name'):
                    folder_name = folder_info['folder_name']
                    # 清理文件名中的非法字符
                    folder_name = re.sub(r'[<>:"/\\|?*]', '_', folder_name)
                    # 限制文件名长度
                    if len(folder_name) > 50:
                        folder_name = folder_name[:50]
                    
                    save_dir = f"{base_dir.rstrip('/')}/{folder_name}"
                    logger.debug(f"根据分享文件名生成目录: {folder_name} -> {save_dir}")
                else:
                    # 获取文件名失败，使用默认方式
                    logger.debug(f"获取分享文件名失败，使用默认方式")
                    save_dir = self._generate_share_save_dir(share_url, base_dir, line_num)
            else:
                # 客户端不可用，使用默认方式
                save_dir = self._generate_share_save_dir(share_url, base_dir, line_num)
            
            # 确保路径以 / 开头
            if not save_dir.startswith('/'):
                save_dir = '/' + save_dir
            
            return save_dir
            
        except Exception as e:
            logger.warning(f"根据分享文件名生成目录失败: {str(e)}，使用默认方式")
            return self._generate_share_save_dir(share_url, base_dir, line_num)

    def _generate_custom_save_dir(self, share_url, pwd=None, base_dir=None, line_num=1, share_index=1,
                                 naming_strategy='id', custom_template=None, current_date=None, current_time=None):
        """
        根据指定策略生成自定义保存目录
        Args:
            share_url: 分享链接
            pwd: 提取码
            base_dir: 基础目录
            line_num: 行号
            share_index: 序号（从1开始）
            naming_strategy: 命名策略
            custom_template: 自定义模板
            current_date: 当前日期
            current_time: 当前时间
        Returns:
            str: 生成的保存目录路径
        """
        try:
            # 设置默认基础目录
            if not base_dir:
                base_dir = '/AutoTransfer'
            
            folder_name = None
            
            # 根据不同策略生成文件夹名称
            if naming_strategy == 'custom' and custom_template:
                # 自定义模板模式
                folder_name = self._apply_custom_template(
                    custom_template, share_url, pwd, line_num, share_index, current_date, current_time
                )
                
            elif naming_strategy == 'name':
                # 基于分享文件名
                if self.client and self.is_valid():
                    folder_info = self.get_share_folder_name(share_url, pwd)
                    if folder_info.get('success') and folder_info.get('folder_name'):
                        name = folder_info['folder_name']
                        # 清理文件名中的非法字符
                        name = re.sub(r'[<>:"/\\|?*]', '_', name)
                        # 限制文件名长度
                        if len(name) > 50:
                            name = name[:50]
                        folder_name = name
                        logger.debug(f"根据分享文件名生成目录: {name}")
                    else:
                        logger.debug(f"获取分享文件名失败，降级为ID模式")
                        folder_name = self._extract_share_id(share_url, line_num)
                else:
                    logger.debug(f"客户端不可用，降级为ID模式")
                    folder_name = self._extract_share_id(share_url, line_num)
                    
            elif naming_strategy == 'index':
                # 基于序号
                folder_name = f"Resource_{share_index:02d}"
                
            elif naming_strategy == 'line':
                # 基于行号
                folder_name = f"Line_{line_num:02d}"
                
            else:  # 默认为 'id'
                # 基于分享链接ID
                folder_name = self._extract_share_id(share_url, line_num)
            
            # 如果没有生成成功，使用备用方案
            if not folder_name:
                folder_name = f"share_{share_index}"
            
            # 生成完整路径
            save_dir = f"{base_dir.rstrip('/')}/{folder_name}"
            
            # 确保路径以 / 开头
            if not save_dir.startswith('/'):
                save_dir = '/' + save_dir
            
            logger.debug(f"使用{naming_strategy}策略生成目录: {share_url} -> {save_dir}")
            return save_dir
            
        except Exception as e:
            logger.warning(f"生成自定义保存目录失败: {str(e)}，使用默认方式")
            return self._generate_share_save_dir(share_url, base_dir, line_num)
    
    def _extract_share_id(self, share_url, line_num=1):
        """
        从分享链接中提取ID
        Args:
            share_url: 分享链接
            line_num: 行号（备用）
        Returns:
            str: 提取的ID或备用名称
        """
        try:
            share_id = None
            
            # 处理不同格式的链接
            if '/s/' in share_url:
                # https://pan.baidu.com/s/1xxxxxxx 格式
                share_id = share_url.split('/s/')[-1]
                # 去除可能的参数
                if '?' in share_id:
                    share_id = share_id.split('?')[0]
            elif 'shareid=' in share_url:
                # https://pan.baidu.com/share/link?shareid=xxx&uk=xxx 格式
                match = re.search(r'shareid=(\d+)', share_url)
                if match:
                    share_id = match.group(1)
            
            if not share_id:
                # 如果无法提取标识符，使用行号
                share_id = f'line_{line_num}'
            
            # 限制标识符长度，避免目录名过长
            if len(share_id) > 20:
                share_id = share_id[:20]
            
            return f"share_{share_id}"
            
        except Exception as e:
            logger.debug(f"提取分享链ID失败: {str(e)}")
            return f"share_{line_num}"
    
    def _apply_custom_template(self, template, share_url, pwd, line_num, share_index, current_date, current_time):
        """
        应用自定义模板
        Args:
            template: 模板字符串
            share_url: 分享链接
            pwd: 提取码
            line_num: 行号
            share_index: 序号
            current_date: 当前日期
            current_time: 当前时间
        Returns:
            str: 应用模板后的字符串
        """
        try:
            # 提取分享链接ID
            share_id = self._extract_share_id(share_url, line_num).replace('share_', '')
            
            # 尝试获取分享文件名
            share_name = 'unknown'
            if self.client and self.is_valid():
                try:
                    folder_info = self.get_share_folder_name(share_url, pwd)
                    if folder_info.get('success') and folder_info.get('folder_name'):
                        share_name = folder_info['folder_name']
                        # 清理文件名中的非法字符
                        share_name = re.sub(r'[<>:"/\\|?*]', '_', share_name)
                        if len(share_name) > 30:
                            share_name = share_name[:30]
                except Exception:
                    pass
            
            # 定义可用的变量
            variables = {
                'id': share_id,
                'line': line_num,
                'index': share_index, 
                'name': share_name,
                'date': current_date or '',
                'time': current_time or '',
                'pwd': pwd or ''
            }
            
            # 应用模板替换
            result = template
            for key, value in variables.items():
                # 支持格式化，如 {index:02d}
                pattern = r'\{' + key + r'(?::[^}]+)?\}'
                if re.search(pattern, result):
                    try:
                        # 尝试使用Python格式化
                        temp_template = result
                        for match in re.finditer(pattern, result):
                            placeholder = match.group(0)
                            try:
                                formatted_value = placeholder.format(**{key: value})
                                temp_template = temp_template.replace(placeholder, str(formatted_value))
                            except (ValueError, KeyError):
                                # 如果格式化失败，使用原始值
                                temp_template = temp_template.replace(placeholder, str(value))
                        result = temp_template
                    except Exception:
                        # 简单替换
                        result = result.replace(f'{{{key}}}', str(value))
            
            # 清理文件名中的非法字符
            result = re.sub(r'[<>:"/\\|?*]', '_', result)
            
            # 限制长度
            if len(result) > 100:
                result = result[:100]
            
            logger.debug(f"应用自定义模板: {template} -> {result}")
            return result
            
        except Exception as e:
            logger.warning(f"应用自定义模板失败: {str(e)}，使用备用名称")
            return f"custom_{share_index}"

    def transfer_shares_from_text(self, text, default_save_dir=None, progress_callback=None):
        """
        从文本中解析并批量转存分享链接
        只支持 https://pan.baidu.com/s/xxxxx?pwd=xxxx 格式
        Args:
            text: 包含分享链接的文本
            default_save_dir: 默认保存目录
            progress_callback: 进度回调函数
        Returns:
            dict: 批量转存结果
        """
        try:
            logger.info("开始从文本中解析分享链接...")
            if progress_callback:
                progress_callback('info', '解析文本中的分享链接...')
            
            # 解析分享链接
            share_configs = self.parse_share_links_from_text(text, default_save_dir)
            
            if not share_configs:
                error_msg = '文本中未找到有效的分享链接，请确保使用 https://pan.baidu.com/s/xxxxx?pwd=xxxx 格式'
                logger.warning(error_msg)
                if progress_callback:
                    progress_callback('warning', error_msg)
                return {
                    'success': False,
                    'error': error_msg,
                    'total_count': 0,
                    'success_count': 0,
                    'failed_count': 0,
                    'skipped_count': 0,
                    'results': []
                }
            
            logger.info(f"解析完成，共找到 {len(share_configs)} 个分享链接")
            if progress_callback:
                progress_callback('success', f'解析完成，找到 {len(share_configs)} 个分享链接')
            
            # 执行批量转存
            return self.transfer_multiple_shares(share_configs, progress_callback)
            
        except Exception as e:
            error_msg = f'从文本转存失败: {str(e)}'
            logger.error(error_msg)
            if progress_callback:
                progress_callback('error', error_msg)
            return {
                'success': False,
                'error': error_msg,
                'total_count': 0,
                'success_count': 0,
                'failed_count': 0,
                'skipped_count': 0,
                'results': []
            }

    def transfer_share(self, share_url, pwd=None, save_dir=None, progress_callback=None, 
                      regex_pattern=None, regex_replace=None):
        """转存分享文件
        Args:
            share_url: 分享链接
            pwd: 提取码
            save_dir: 保存目录
            progress_callback: 进度回调函数
            regex_pattern: 正则表达式模式（用于文件过滤和重命名）
            regex_replace: 正则替换字符串
        Returns:
            dict: {
                'success': bool,  # 是否成功
                'message': str,   # 成功时的消息
                'error': str,     # 失败时的错误信息
                'skipped': bool,  # 是否跳过（没有新文件）
                'transferred_files': list  # 成功转存的文件列表
            }
        """
        try:
            # 规范化保存路径
            if save_dir and not save_dir.startswith('/'):
                save_dir = '/' + save_dir
            
            # 步骤1：访问分享链接并获取文件列表
            logger.info(f"正在访问分享链接: {share_url}")
            if progress_callback:
                progress_callback('info', f'【步骤1/4】访问分享链接: {share_url}')
            
            try:
                # 访问分享链接
                if pwd:
                    logger.info(f"使用密码 {pwd} 访问分享链接")
                    if progress_callback:
                        progress_callback('info', f'使用密码访问分享链接')
                
                self.client.access_shared(share_url, pwd)
                
                # 步骤1.1：获取分享文件列表并记录
                logger.info("获取分享文件列表...")
                shared_paths = self.client.shared_paths(shared_url=share_url)
                if not shared_paths:
                    logger.error("获取分享文件列表失败")
                    if progress_callback:
                        progress_callback('error', '获取分享文件列表失败')
                    return {'success': False, 'error': '获取分享文件列表失败'}
                
                # 记录分享文件信息
                logger.info(f"成功获取分享文件列表，共 {len(shared_paths)} 项")
                
                # 获取分享信息
                uk = shared_paths[0].uk
                share_id = shared_paths[0].share_id
                bdstoken = shared_paths[0].bdstoken
                
                # 记录共享文件详情
                shared_files_info = []
                for path in shared_paths:
                    if path.is_dir:
                        logger.info(f"记录共享文件夹: {path.path}")
                        # 获取文件夹内容
                        folder_files = self._list_shared_dir_files(path, uk, share_id, bdstoken)
                        for file_info in folder_files:
                            shared_files_info.append(file_info)
                            logger.debug(f"记录共享文件: {file_info['path']}")
                    else:
                        logger.debug(f"记录共享文件: {path.path}")
                        shared_files_info.append({
                            'server_filename': os.path.basename(path.path),
                            'fs_id': path.fs_id,
                            'path': path.path,
                            'size': path.size,
                            'isdir': 0
                        })
                
                logger.info(f"共记录 {len(shared_files_info)} 个共享文件")
                if progress_callback:
                    progress_callback('info', f'获取到 {len(shared_files_info)} 个共享文件')
                
                # 步骤2：扫描本地目录中的文件
                logger.info(f"【步骤2/4】扫描本地目录: {save_dir}")
                if progress_callback:
                    progress_callback('info', f'【步骤2/4】扫描本地目录: {save_dir}')
                
                # 获取本地文件列表
                local_files = []
                if save_dir:
                    local_files = self.list_local_files(save_dir)
                    if progress_callback:
                        progress_callback('info', f'本地目录中有 {len(local_files)} 个文件')
                
                # 步骤3：准备转存（对比文件、准备目录）
                target_dir = save_dir
                is_single_folder = (
                    len(shared_paths) == 1 
                    and shared_paths[0].is_dir
                )
                
                logger.info(f"【步骤3/4】准备转存: 对比文件和准备目录")
                if progress_callback:
                    progress_callback('info', f'【步骤3/4】准备转存: 对比文件和准备目录')
                
                # 步骤3.1：对比文件，确定需要转存的文件
                logger.info("开始对比共享文件和本地文件...")
                transfer_list = []  # 存储(fs_id, dir_path, clean_path, final_path, need_rename)元组
                
                # 使用之前收集的共享文件信息进行对比
                for file_info in shared_files_info:
                    clean_path = file_info['path']
                    if is_single_folder and '/' in clean_path:
                        clean_path = '/'.join(clean_path.split('/')[1:])
                    
                    # 应用正则规则
                    should_transfer = True
                    final_path = clean_path
                    
                    if regex_pattern:
                        should_transfer, final_path = self._apply_regex_rules(
                            clean_path, regex_pattern, regex_replace)
                        if not should_transfer:
                            logger.debug(f"文件被正则过滤掉: {clean_path}")
                            if progress_callback:
                                progress_callback('info', f'文件被正则过滤掉: {clean_path}')
                            continue
                    
                    # 去重检查逻辑
                    clean_normalized = self._normalize_path(clean_path, file_only=True)
                    final_normalized = self._normalize_path(final_path, file_only=True)
                    
                    # 检查文件是否已存在
                    if final_normalized in local_files:
                        logger.debug(f"文件已存在，跳过: {final_path}")
                        if progress_callback:
                            progress_callback('info', f'文件已存在，跳过: {final_path}')
                        continue
                    
                    # 转存到原始路径的目录
                    if target_dir is not None and clean_path is not None:
                        target_path = posixpath.join(target_dir, clean_path)
                        dir_path = posixpath.dirname(target_path).replace('\\', '/')
                        need_rename = (final_path != clean_path)
                        transfer_list.append((file_info['fs_id'], dir_path, clean_path, final_path, need_rename))
                        
                        # 日志显示重命名信息
                        if need_rename:
                            logger.info(f"需要转存文件: {clean_path} -> {final_path}")
                            if progress_callback:
                                progress_callback('info', f'需要转存文件: {clean_path} -> {final_path}')
                        else:
                            logger.info(f"需要转存文件: {final_path}")
                            if progress_callback:
                                progress_callback('info', f'需要转存文件: {final_path}')
                
                # 检查是否有需要转存的文件
                if not transfer_list:
                    if progress_callback:
                        progress_callback('info', '没有找到需要处理的文件')
                    return {'success': True, 'skipped': True, 'message': '没有新文件需要转存'}
                
                if progress_callback:
                    progress_callback('info', f'找到 {len(transfer_list)} 个新文件需要转存')
                
                # 步骤3.2：创建所有必要的目录
                logger.info("确保所有目标目录存在")
                created_dirs = set()
                for _, dir_path, _, _, _ in transfer_list:
                    if dir_path not in created_dirs:
                        logger.info(f"检查目录: {dir_path}")
                        if not self._ensure_dir_exists(dir_path):
                            logger.error(f"创建目录失败: {dir_path}")
                            if progress_callback:
                                progress_callback('error', f'创建目录失败: {dir_path}')
                            return {'success': False, 'error': f'创建目录失败: {dir_path}'}
                        created_dirs.add(dir_path)
                
                # 步骤4：执行文件转存
                logger.info(f"=== 【步骤4/4】开始执行转存操作 ===")
                logger.info(f"共需转存 {len(transfer_list)} 个文件")
                if progress_callback:
                    progress_callback('info', f'【步骤4/4】开始执行转存操作，共 {len(transfer_list)} 个文件')
                
                # 按目录分组进行转存
                success_count = 0
                grouped_transfers = {}
                for fs_id, dir_path, _, _, _ in transfer_list:
                    grouped_transfers.setdefault(dir_path, []).append(fs_id)
                
                total_files = len(transfer_list)
                
                # 对每个目录进行批量转存
                logger.info(f"按目录分组进行转存，共 {len(grouped_transfers)} 个目录组")
                for dir_path, fs_ids in grouped_transfers.items():
                    # 确保目录路径使用正斜杠
                    dir_path = dir_path.replace('\\', '/')
                    if progress_callback:
                        progress_callback('info', f'转存到目录 {dir_path} ({len(fs_ids)} 个文件)')
                    
                    try:
                        logger.info(f"开始执行转存操作: 正在将 {len(fs_ids)} 个文件转存到 {dir_path}")
                        # 确保客户端和参数都有效
                        if self.client and uk is not None and share_id is not None and bdstoken is not None:
                            self.client.transfer_shared_paths(
                                remotedir=dir_path,
                                fs_ids=fs_ids,
                                uk=int(uk),
                                share_id=int(share_id),
                                bdstoken=str(bdstoken),
                                shared_url=share_url
                            )
                        else:
                            error_msg = "转存失败: 客户端或参数无效"
                            logger.error(error_msg)
                            raise ValueError(error_msg)
                        success_count += len(fs_ids)
                        logger.success(f"转存操作成功完成: {len(fs_ids)} 个文件已转存到 {dir_path}")
                        if progress_callback:
                            progress_callback('success', f'成功转存到 {dir_path}')
                    except Exception as e:
                        if "error_code: -65" in str(e):  # 频率限制
                            if progress_callback:
                                progress_callback('warning', '触发频率限制，等待10秒后重试...')
                            logger.warning(f"转存操作受到频率限制，等待10秒后重试: {dir_path}")
                            time.sleep(10)
                            try:
                                logger.info(f"重试转存操作: 正在将 {len(fs_ids)} 个文件转存到 {dir_path}")
                                if self.client and uk is not None and share_id is not None and bdstoken is not None:
                                    self.client.transfer_shared_paths(
                                        remotedir=dir_path,
                                        fs_ids=fs_ids,
                                        uk=int(uk),
                                        share_id=int(share_id),
                                        bdstoken=str(bdstoken),
                                        shared_url=share_url
                                    )
                                else:
                                    error_msg = "重试转存失败: 客户端或参数无效"
                                    logger.error(error_msg)
                                    raise ValueError(error_msg)
                                success_count += len(fs_ids)
                                logger.success(f"重试转存成功: {len(fs_ids)} 个文件已转存到 {dir_path}")
                                if progress_callback:
                                    progress_callback('success', f'重试成功: {dir_path}')
                            except Exception as retry_e:
                                logger.error(f"重试转存失败: {dir_path} - {str(retry_e)}")
                                if progress_callback:
                                    progress_callback('error', f'转存失败: {dir_path} - {str(retry_e)}')
                                return {'success': False, 'error': f'转存失败: {dir_path} - {str(retry_e)}'}
                        else:
                            logger.error(f"转存操作失败: {dir_path} - {str(e)}")
                            if progress_callback:
                                progress_callback('error', f'转存失败: {dir_path} - {str(e)}')
                            return {'success': False, 'error': f'转存失败: {dir_path} - {str(e)}'}
                    
                    time.sleep(1)  # 避免频率限制
                
                # 步骤5：执行重命名操作（如果需要）
                logger.info("=== 【步骤5/5】检查是否需要重命名文件 ===")
                renamed_files = []
                
                for fs_id, dir_path, clean_path, final_path, need_rename in transfer_list:
                    if need_rename:
                        try:
                            # 构建转存后的完整路径（原始文件名）
                            original_full_path = posixpath.join(dir_path, os.path.basename(clean_path))
                            # 构建重命名后的完整路径
                            final_full_path = posixpath.join(dir_path, os.path.basename(final_path))
                            
                            logger.info(f"重命名文件: {original_full_path} -> {final_full_path}")
                            if progress_callback:
                                progress_callback('info', f'重命名文件: {os.path.basename(clean_path)} -> {os.path.basename(final_path)}')
                            
                            # 使用baidupcs-py的rename方法（需要完整路径）
                            self.client.rename(original_full_path, final_full_path)
                            
                            logger.success(f"重命名成功: {clean_path} -> {final_path}")
                            renamed_files.append(final_path)
                            
                            # 添加延迟避免API频率限制
                            time.sleep(0.5)
                                
                        except Exception as e:
                            logger.warning(f"重命名失败: {clean_path} -> {final_path}, 错误: {str(e)}")
                            # 重命名失败时使用原文件名
                            renamed_files.append(clean_path)
                    else:
                        renamed_files.append(final_path)
                
                # 转存结果汇总
                logger.info(f"=== 转存操作完成，结果汇总 ===")
                logger.info(f"总文件数: {total_files}")
                logger.info(f"成功转存: {success_count}")
                
                # 根据转存结果返回不同状态
                if success_count == total_files:  # 全部成功
                    logger.success(f"转存全部成功，共 {success_count}/{total_files} 个文件")
                    if progress_callback:
                        progress_callback('success', f'转存完成，成功转存 {success_count}/{total_files} 个文件')
                    return {
                        'success': True,
                        'message': f'成功转存 {success_count}/{total_files} 个文件',
                        'transferred_files': renamed_files
                    }
                elif success_count > 0:  # 部分成功
                    logger.warning(f"转存部分成功，共 {success_count}/{total_files} 个文件")
                    if progress_callback:
                        progress_callback('warning', f'部分转存成功，成功转存 {success_count}/{total_files} 个文件')
                    return {
                        'success': True,
                        'message': f'部分转存成功，成功转存 {success_count}/{total_files} 个文件',
                        'transferred_files': renamed_files[:success_count]
                    }
                else:  # 全部失败
                    if progress_callback:
                        progress_callback('error', '转存失败，没有文件成功转存')
                    return {
                        'success': False,
                        'error': '转存失败，没有文件成功转存'
                    }
                
            except Exception as e:
                error_msg = str(e)
                # 使用新的错误解析函数
                parsed_error = self._parse_share_error(error_msg)
                return {'success': False, 'error': parsed_error}
            
        except Exception as e:
            logger.error(f"转存分享文件失败: {str(e)}")
            parsed_error = self._parse_share_error(str(e))
            return {'success': False, 'error': parsed_error}

    def get_share_folder_name(self, share_url, pwd=None):
        """获取分享链接的主文件夹名称"""
        try:
            logger.info(f"正在获取分享链接信息: {share_url}")
            
            # 访问分享链接
            if pwd:
                logger.info(f"使用密码访问分享链接")
            self.client.access_shared(share_url, pwd)
            
            # 获取分享文件列表
            shared_paths = self.client.shared_paths(shared_url=share_url)
            if not shared_paths:
                return {'success': False, 'error': '获取分享文件列表失败'}
            
            # 获取主文件夹名称
            if len(shared_paths) == 1 and shared_paths[0].is_dir:
                # 如果只有一个文件夹，使用该文件夹名称
                folder_name = os.path.basename(shared_paths[0].path)
                logger.success(f"获取到文件夹名称: {folder_name}")
                return {'success': True, 'folder_name': folder_name}
            else:
                # 如果有多个文件或不是文件夹，使用分享链接的默认名称或第一个项目的名称
                if shared_paths:
                    first_item = shared_paths[0]
                    if first_item.is_dir:
                        folder_name = os.path.basename(first_item.path)
                    else:
                        # 如果第一个是文件，尝试获取文件名（去掉扩展名）
                        folder_name = os.path.splitext(os.path.basename(first_item.path))[0]
                    logger.success(f"获取到名称: {folder_name}")
                    return {'success': True, 'folder_name': folder_name}
                else:
                    return {'success': False, 'error': '分享内容为空'}
                    
        except Exception as e:
            logger.error(f"获取分享信息失败: {str(e)}")
            return {'success': False, 'error': str(e)}

    def list_shared_files(self, share_url, pwd=None):
        """获取分享链接中的文件列表"""
        try:
            logger.info(f"开始获取分享链接 {share_url} 的文件列表")
            if pwd:
                logger.info(f"使用密码 {pwd} 访问分享链接")
                
            logger.debug("开始访问分享链接...")
            self.client.access_shared(share_url, pwd)
            logger.debug("分享链接访问成功")
            
            logger.debug("开始获取文件列表...")
            # 获取根目录文件列表
            files = self.client.shared_paths(shared_url=share_url)
            
            # 用于存储所有文件
            all_files = []
            
            def get_folder_contents():
                """递归获取文件夹内容"""
                for file in files:
                    if hasattr(file, 'is_dir') and file.is_dir:
                        logger.debug(f"进入文件夹: {file.path}")
                        try:
                            # 递归获取子目录内容
                            sub_files = self.client.list_shared_paths(
                                file.path,
                                file.uk,
                                file.share_id,
                                file.bdstoken,
                                page=1,
                                size=100
                            )
                            all_files.extend(sub_files)
                        except Exception as e:
                            logger.error(f"获取文件夹 {file.path} 内容失败: {str(e)}")
                    else:
                        all_files.append(file)
                        
            # 执行递归获取
            get_folder_contents()
            logger.info(f"共找到 {len(all_files)} 个文件")
            return all_files

        except Exception as e:
            logger.error(f"获取分享文件列表失败: {str(e)}")
            logger.error(f"异常类型: {type(e)}")
            logger.error("异常详情:", exc_info=True)
            raise