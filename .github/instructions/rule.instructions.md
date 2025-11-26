---
applyTo: '**/*.py'
---
Provide project context and coding guidelines that AI should follow when generating code, answering questions, or reviewing changes.

--- .github/instructions/rule.instructions.md
### Python 编码规范
遵循 PEP 8 标准，确保代码风格一致。主要包括但不限于以下几点：
- 使用 4 个空格缩进
- 每行不超过 79 个字符
- 函数和变量命名使用小写字母和下划线（snake
_case）
- 类命名使用驼峰式（CamelCase）
- 保持代码简洁，避免冗余注释
- 代码要高内聚低耦合，模块职责单一，具有良
  的扩展性
- 所有错误调用 `handle_error_and_notify()` 统一处理
- 微信通知器通过 `BaiduStorage` 内部传递，避免循环导入
- 配置字段向后兼容（同时支持 `cookies` 和 `BAIDU_COOKIES`）
- 路径统一使用正斜杠，自动规范化
- 正则表达式使用 raw string (`r"..."`) 防止转义问题
- 不用输出说明文档、文档清单等不必要的文件，除特殊说明外
- 保持代码简洁，避免冗余注释  
- 非代码回答必须使用中文


### 数据流

```
config.json / 环境变量
         ↓
transfer_runner.py (配置解析 & 链接解析)
         ↓
BaiduStorage (核心转存逻辑)
    ├─ 访问分享链接获取文件列表
    ├─ 扫描本地目录（MD5 对比去重）
    ├─ 应用正则过滤/文件夹过滤
    ├─ 创建目录并批量转存
    └─ 重命名（如需）
         ↓
WeChatNotifier (发送结果通知)
         ↓
GitHub Actions 流程完成