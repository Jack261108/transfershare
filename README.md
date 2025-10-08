# 百度网盘自动转存 GitHub Actions

这个项目使用 GitHub Actions 自动执行百度网盘分享链接的转存任务，每两小时运行一次。

## 功能特点

- ✅ 自动转存百度网盘分享链接中的文件
- ✅ 支持密码保护的分享链接
- ✅ 支持批量转存多个分享链接
- ✅ 支持带密码参数的分享链接格式
- ✅ 支持在链接后指定保存目录
- ✅ 自动去重，跳过已存在的文件
- ✅ 详细的执行日志和进度跟踪
- ✅ 每两小时自动执行
- ✅ 支持手动触发
- ✅ 企业微信机器人通知

## 设置步骤

### 1. Fork 此仓库

点击右上角的 "Fork" 按钮，将此仓库复制到您的 GitHub 账户。

### 2. 设置 Secrets

在您 fork 的仓库中，进入 `Settings` → `Secrets and variables` → `Actions`，添加以下 Secrets：

#### 必需的 Secrets：

- **`BAIDU_COOKIES`** (必需): 百度网盘的 cookies
  ```
  BDUSS=your_bduss_value; STOKEN=your_stoken_value
  ```

- **`SHARE_URLS`** (必需): 批量转存的分享链接文本
  ```
  https://pan.baidu.com/s/1NXEVkmQFfTeB9gvgBYdX0A?pwd=f9c7
  https://pan.baidu.com/s/1example2?pwd=5678 /保存目录/子文件夹
  https://pan.baidu.com/s/1example3?pwd=abcd /我的文件/资料
  ```

#### 可选的 Secrets：



- **`SAVE_DIR`**: 保存目录，默认为 `/AutoTransfer`
  ```
  /MyFiles/Downloads
  ```

- **`WECHAT_WEBHOOK`**: 企业微信机器人 Webhook 地址（可选）
  ```
  https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxxx
  ```

### 3. 获取百度网盘 Cookies

1. 登录百度网盘网页版 (pan.baidu.com)
2. 打开浏览器开发者工具 (F12)
3. 进入 `Application` → `Cookies` → `https://pan.baidu.com`
4. 找到 `BDUSS` 和 `STOKEN` 的值
5. 按格式 `BDUSS=xxx; STOKEN=xxx` 组合

### 4. 获取企业微信机器人 Webhook（可选）

1. 登录企业微信管理后台
2. 进入“应用管理”→“自建”→“群机器人”
3. 创建新的机器人或选择现有机器人
4. 获取 Webhook 地址，格式如：
   ```
   https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxxx
   ```
5. 将机器人添加到需要接收通知的群聊中

### 5. 启用 GitHub Actions

1. 进入您 fork 的仓库
2. 点击 `Actions` 标签
3. 如果看到提示，点击 "I understand my workflows, go ahead and enable them"
4. 找到 "Baidu Transfer Task" 工作流并启用

## 使用方法

### 自动执行

工作流会每两小时自动运行一次（UTC时间的偶数小时）。

### 手动执行

1. 进入 `Actions` 标签
2. 选择 "Baidu Transfer Task" 工作流
3. 点击 "Run workflow" 按钮
4. 选择分支（通常是 main）
5. 点击绿色的 "Run workflow" 按钮

### 测试企业微信通知

在本地测试企业微信通知功能：

```bash
# 设置环境变量
export WECHAT_WEBHOOK="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxxx"

# 运行测试脚本
python test_wechat.py
```

### 查看执行结果

1. 在 `Actions` 标签中查看工作流运行状态
2. 点击具体的运行记录查看详细日志
3. 如果有错误，可以在日志中查看详细信息
4. 如果配置了企业微信机器人，会自动收到执行结果通知

## 分享链接格式说明

本项目仅支持带密码参数的百度网盘分享链接格式：

### 链接格式

```
https://pan.baidu.com/s/xxxxxxxxxx?pwd=xxxx
```

### 使用方法

在 `SHARE_URLS` 中填入分享链接，每行一个：

```
https://pan.baidu.com/s/1NXEVkmQFfTeB9gvgBYdX0A?pwd=f9c7
https://pan.baidu.com/s/1example2?pwd=5678 /保存目录/子文件夹
https://pan.baidu.com/s/1example3?pwd=abcd /我的文件/资料
```

### 保存目录指定

可以在链接后面空格分隔指定保存目录：
- 如果不指定保存目录，将使用默认的 `SAVE_DIR` 变量值
- 如果指定了保存目录，必须以 `/` 开头
- 保存目录会自动创建（如果不存在）

### 本地使用示例

查看 `example_simple_format.py` 文件了解如何在本地使用：

```bash
# 设置环境变量
export BAIDU_COOKIES="BDUSS=xxx; STOKEN=xxx"

# 运行示例
python example_simple_format.py
```


## 故障排除

### 1. Cookies 无效
- 错误信息: "cookies 无效" 或 "客户端初始化失败"
- 解决方法: 重新获取百度网盘的 cookies 并更新 BAIDU_COOKIES

### 2. 分享链接格式错误
- 错误信息: "格式不支持" 或 "链接解析失败"
- 解决方法: 检查链接是否为 https://pan.baidu.com/s/xxxxx?pwd=xxxx 格式

### 3. 分享链接失效
- 错误信息: "分享链接已失效" 或 "error_code: 145"
- 解决方法: 检查分享链接是否还有效，更新 SHARE_URL

### 4. 提取码错误
- 错误信息: "提取码输入错误" 或 "error_code: 200025"
- 解决方法: 检查并更新 SHARE_PASSWORD

### 5. 频率限制
- 错误信息: "error_code: -65" 或 "触发频率限制"
- 解决方法: 等待一段时间后重新运行，或调整执行频率

### 6. 企业微信通知问题
- 错误信息: "企业微信通知发送失败"
- 解决方法: 
  - 检查 WECHAT_WEBHOOK 是否正确
  - 确认机器人已加入目标群聊
  - 使用 `python test_wechat.py` 测试通知功能

## 日志说明

每次执行都会生成详细的日志文件，包含：
- 执行时间和配置信息
- 文件扫描和对比过程
- 转存操作的详细结果
- 错误信息（如果有）

日志会作为 Artifacts 上传，保留 7 天。

## 注意事项

1. **链接格式**: 仅支持 https://pan.baidu.com/s/xxxxx?pwd=xxxx 格式的分享链接
2. **Cookies 安全**: 请妖善保管您的百度网盘 cookies，不要泄露给他人
3. **执行频率**: 建议不要设置过高的执行频率，以免触发百度的频率限制
4. **存储空间**: 请确保您的百度网盘有足够的存储空间
5. **分享链接**: 请确保分享链接的有效性和合法性

## 许可证

本项目采用 MIT 许可证。

## 贡献

欢迎提交 Issue 和 Pull Request！