# 配置文件使用指南

## 快速开始

### 1. 复制配置模板
```bash
cp config.template.json config.json
```

### 2. 编辑配置文件
编辑 `config.json`，填入以下必需信息：

```json
{
  "cookies": "你的Cookies",
  "share_urls": [
    "https://pan.baidu.com/s/xxxxx?pwd=xxxx /保存目录"
  ],
  "save_dir": "/AutoTransfer",
  "wechat_webhook": ""
}
```

### 3. 运行程序
```bash
python transfer_runner.py
```

---

## 配置字段详解

### 必需字段

#### `cookies` (字符串) ⭐
百度网盘的认证凭证，格式为 cookie 键值对。

**如何获取：**
```bash
# 自动获取（推荐）
python save_baidu_cookies.py

# 手动获取：
# 1. 浏览器打开 https://pan.baidu.com
# 2. 登录账户
# 3. 按 F12 打开开发者工具，进入 Application/Cookies
# 4. 复制所有 Cookie 内容
```

**示例：**
```
BDUSS=xxx; STOKEN=yyy; BDUSS_BFESS=zzz; ...
```

**注意：**
- 必须至少包含 `BDUSS` 和 `STOKEN` 两个值
- Cookies 会过期，需定期更新
- 不要在公开的仓库中暴露 Cookies

---

#### `share_urls` (数组或字符串) ⭐
要转存的分享链接列表。

**支持的格式：**

1️⃣ **数组 + 内联目录（推荐）**
```json
"share_urls": [
  "https://pan.baidu.com/s/1Dy3hgtnhlStv1wDcM71ayA?pwd=f9c7 /我的文件/视频",
  "https://pan.baidu.com/s/1TfYiX1zfQBoMIfDDZNXwrA?pwd=4nxa /我的文件/文档"
]
```

2️⃣ **仅链接（使用默认目录）**
```json
"share_urls": [
  "https://pan.baidu.com/s/1Dy3hgtnhlStv1wDcM71ayA?pwd=f9c7",
  "https://pan.baidu.com/s/1TfYiX1zfQBoMIfDDZNXwrA?pwd=4nxa"
]
```

3️⃣ **高级配置（对象数组）**
```json
"share_urls": [
  {
    "share_url": "https://pan.baidu.com/s/1Dy3hgtnhlStv1wDcM71ayA",
    "pwd": "f9c7",
    "save_dir": "/视频",
    "regex_pattern": "\\.(mp4|mkv)$",
    "folder_filter": "高清"
  }
]
```

4️⃣ **多行字符串**
```json
"share_urls": "https://pan.baidu.com/s/1Dy3hgtnhlStv1wDcM71ayA?pwd=f9c7 /文件夹1\nhttps://pan.baidu.com/s/1TfYiX1zfQBoMIfDDZNXwrA?pwd=4nxa /文件夹2"
```

**路径说明：**
- 以 `/` 开头，如 `/AutoTransfer/视频`
- 支持中文路径
- 不指定时使用 `save_dir` 的值

---

### 可选字段

#### `save_dir` (字符串)
默认保存目录。当分享链接后没有指定目录时使用。

- **默认值：** `/AutoTransfer`
- **示例：** `/我的网盘/自动转存`

```json
"save_dir": "/自动转存"
```

---

#### `wechat_webhook` (字符串)
企业微信机器人 webhook URL，用于转存完成后发送通知。

**获取方法：**
1. 打开企业微信
2. 在任意群聊中添加群机器人
3. 复制生成的 webhook URL

**示例：**
```json
"wechat_webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxxx"
```

**不需要通知？**
```json
"wechat_webhook": ""
```

---

#### `regex_pattern` (字符串)
【全局配置】文件过滤规则（正则表达式）。只有匹配的文件才会被转存。

**示例：**

| 需求 | 正则表达式 |
|-----|----------|
| 只转存视频 | `\.(mp4\|mkv\|avi)$` |
| 只转存 PDF | `\.(pdf)$` |
| 转存 2024 年文件 | `2024` |
| 转存高清文件 | `\[高清\]\|1080p\|4K` |
| 忽略系统文件 | `^(?!\.).*$` |

**示例配置：**
```json
"regex_pattern": "\\.(mp4|mkv|avi)$"
```

**不需要过滤？** 删除此字段或留空

---

#### `regex_replace` (字符串)
【全局配置】与 `regex_pattern` 搭配，用于重命名文件。

**示例：**
```json
"regex_pattern": "^(\\d{4})-(.*)\\.pdf$",
"regex_replace": "$1/$2.pdf"
```
效果：`2024-财务报表.pdf` → `2024/财务报表.pdf`

---

#### `folder_filter` (字符串或数组)
【全局配置】文件夹过滤规则。指定只转存某些文件夹。

**格式 1 - 单个模式（字符串）：**
```json
"folder_filter": "Python|JavaScript|编程"
```
只转存名称包含这些关键词的文件夹。

**格式 2 - 多个模式（数组）：**
```json
"folder_filter": ["计算机", "数学", "物理"]
```
任一匹配即可。

**示例：**
```json
"folder_filter": "高级|VIP|精品"
```
只转存名称包含"高级"、"VIP"或"精品"的文件夹。

**注意：** 不匹配的文件夹及其所有子文件夹都会被跳过。

---

## 完整配置示例

### 示例 1 - 简单配置
```json
{
  "cookies": "BDUSS=xxx; STOKEN=yyy",
  "share_urls": [
    "https://pan.baidu.com/s/1abcd1234?pwd=1234 /视频库",
    "https://pan.baidu.com/s/5efgh5678?pwd=5678 /电子书"
  ],
  "save_dir": "/AutoTransfer"
}
```

### 示例 2 - 带通知和过滤
```json
{
  "cookies": "BDUSS=xxx; STOKEN=yyy",
  "share_urls": [
    "https://pan.baidu.com/s/1abcd1234?pwd=1234 /视频",
    "https://pan.baidu.com/s/5efgh5678?pwd=5678 /文档"
  ],
  "save_dir": "/AutoTransfer",
  "wechat_webhook": "https://qyapi.weixin.qq.com/...",
  "regex_pattern": "\\.(mp4|pdf)$",
  "folder_filter": "精品|热门"
}
```

### 示例 3 - 高级配置
```json
{
  "cookies": "BDUSS=xxx; STOKEN=yyy",
  "save_dir": "/AutoTransfer",
  "wechat_webhook": "https://qyapi.weixin.qq.com/...",
  "share_urls": [
    {
      "share_url": "https://pan.baidu.com/s/1abcd1234",
      "pwd": "1234",
      "save_dir": "/视频课程",
      "regex_pattern": "\\.(mp4|mkv)$",
      "folder_filter": "高级班"
    },
    {
      "share_url": "https://pan.baidu.com/s/5efgh5678",
      "pwd": "5678",
      "save_dir": "/考试资料",
      "regex_pattern": "\\.(pdf|doc)$"
    }
  ]
}
```

---

## 环境变量配置

如果不使用 `config.json`，也可以通过环境变量配置（`config.json` 优先级更高）：

```bash
# 设置环境变量
export BAIDU_COOKIES="BDUSS=xxx; STOKEN=yyy"
export SHARE_URLS="https://pan.baidu.com/s/1xxx?pwd=xxx"
export SAVE_DIR="/AutoTransfer"
export WECHAT_WEBHOOK="https://qyapi.weixin.qq.com/..."

# 运行程序
python transfer_runner.py
```

**GitHub Actions 环境：**
1. 打开仓库的 Settings → Secrets and variables → Actions
2. 添加对应的 Secret（推荐使用 `save_baidu_cookies.py --repo owner/repo` 自动添加）

---

## 常见问题

### Q: Cookies 过期了怎么办？
**A:** 运行以下命令重新获取：
```bash
python save_baidu_cookies.py
```

### Q: 如何避免转存重复的文件？
**A:** 程序会自动对比本地文件，如果文件已存在则跳过。

### Q: 如何只转存某些格式的文件？
**A:** 使用 `regex_pattern` 字段：
```json
"regex_pattern": "\\.(mp4|mkv)$"
```

### Q: 如何为不同的链接配置不同的转存规则？
**A:** 使用高级配置模式（对象数组）。

### Q: 如何测试正则表达式是否正确？
**A:** 可以在 [regex101.com](https://regex101.com) 在线测试。

### Q: 转存速度很慢怎么办？
**A:** 
- 确保网络连接良好
- 减少文件数量（使用 `regex_pattern` 或 `folder_filter` 过滤）
- 检查百度网盘是否设置了速率限制

---

## 最佳实践

1. ✅ **定期更新 Cookies**：百度网盘 Cookies 会过期，建议定期更新

2. ✅ **保护敏感信息**：
   - 不要在 GitHub 上提交含有真实 Cookies 的配置文件
   - 使用 `.gitignore` 忽略 `config.json`
   - 在 GitHub Actions 中使用 Secrets

3. ✅ **测试新配置**：
   - 修改正则表达式或过滤规则后，先用一个小的测试链接验证
   - 查看转存日志确认没有遗漏或误删

4. ✅ **合理设置过滤规则**：
   - 如果文件很多，使用 `regex_pattern` 或 `folder_filter` 减少数据量
   - 过滤规则会大幅提升效率

5. ✅ **备份重要配置**：
   - 修改配置前保存备份
   - 可以保留多个配置文件供不同场景使用

---

## 文件列表

| 文件 | 说明 |
|-----|-----|
| `config.json` | 【实际使用】真实配置文件（不提交到 Git） |
| `config.template.json` | 【快速开始】最简配置模板 |
| `config.example.json` | 【参考】完整示例及说明 |

---

## 更新配置后如何使用？

**本地运行：**
```bash
python transfer_runner.py
```

**GitHub Actions 自动运行：**
- 配置会自动读取
- 每 2 小时自动执行一次
- 完成后通过企业微信通知

---

需要帮助？查看 README.md 或提交 Issue。
