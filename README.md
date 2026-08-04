# syh's chatter

一个基于 **Flask** 和 **MongoDB** 的轻量级聊天室应用，支持多用户实时交流、文件上传、管理员控制、邀请码注册等功能。  
**新特性**：首次启动时提供 **Web 初始化向导**，无需手动编辑配置文件或数据文件，一切通过界面完成。

![preview](preview.png)

---

## ✨ 功能特性

- 💬 **实时消息**：通过轮询刷新，实现近实时聊天体验
- 🧩 **结构化消息**：JSON 消息 ID、回复引用、软撤回、系统公告与服务端禁言状态
- 👤 **用户系统**：自定义昵称与颜色，密码使用 `werkzeug` 哈希存储
- 📎 **文件上传**：自动识别图片、音频、普通文件，并添加标记（`::img::`、`::wav::`、`::file::`）
- 👑 **管理员命令**：
  - `command: clear` – 清空所有聊天记录
  - `command: delete N` – 删除最后 N 条消息
  - `command: change_color 用户名 新颜色` – 修改指定用户的显示颜色（影响后续消息）
- 🔐 **安全注册**：需要邀请码方可注册，初始邀请码在首次初始化时自动生成并展示
- 👥 **在线列表**：动态显示当前在线用户
- 💾 **MongoDB 持久化**：所有消息存入数据库，重启后数据不丢失（若 MongoDB 不可用，自动降级为内存存储）
- 🎨 **前端友好**：集成 Font Awesome、Highlight.js、jQuery、html2canvas（通过 CDN 引入）

---

## 📦 环境要求

- Python 3.6 及以上
- MongoDB 服务器（本地或远程；生产环境建议启动以持久化消息）
- pip（Python 包管理器）

---

## 🚀 安装与配置

### 1. 克隆项目

```bash
git clone https://github.com/syh100925/syh-s-chatter.git
cd syh-s-chatter
```

### 2. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

> `werkzeug` 提供了密码哈希与安全文件名处理；`charset-normalizer` 仅用于 `.cpp` 文件的在线预览和复制，原始下载仍保持字节不变。若本机暂时没有 MongoDB，服务会使用 `mongomock` 内存回退，重启后消息不会保留。

### 3. 首次运行（自动初始化）

**重要**：从本版本开始，您**不再需要**手动创建 `usernames.list`、`passwords.list`、`colors.list` 或 `invite_code.txt`。  
所有配置和初始数据均可通过 **Web 初始化向导** 完成。

#### 3.1 启动服务

```bash
python server.py
```

默认监听 `0.0.0.0:5000`。如果您希望更改 IP 或端口，可直接修改 `server.py` 末尾的 `app.run` 参数。

#### 3.2 访问初始化页面

打开浏览器访问 `http://<服务器IP>:5000`（若在本机运行，可使用 `127.0.0.1`）。  
首次访问时，系统会自动跳转到 `/init` 初始化页面。

#### 3.3 填写配置信息

在初始化页面中，您需要填写：

- **MongoDB 连接信息**：数据库 IP、端口、用户名（可选）、密码（可选）  
- **服务器地址**：用于生成聊天室的跳转链接（例如 `192.168.1.100:5000`）。页面会自动从浏览器地址栏识别当前主机，您也可以手动修改。
- **管理员账号**：用户名和密码（系统将创建此用户，并赋予管理员权限）
- **初始邀请码数量**：系统将生成指定数量的邀请码，供新用户注册使用

#### 3.4 测试数据库连接（可选）

在填写数据库信息后，点击 **“测试连接”** 按钮，系统会尝试连接 MongoDB 并返回结果。即使连接失败，您仍可以继续提交（此时将使用内存存储，重启后数据丢失）。

#### 3.5 提交初始化

点击 **“初始化系统”** 按钮，系统将：

- 保存数据库配置（`config.json`）
- 创建管理员用户（写入 `usernames.list` 等文件）
- 生成指定数量的邀请码（写入 `invite_code.txt`）
- 初始化数据库集合（自动创建 `chats.values` 和 `chats.mutes`）

#### 3.6 获取邀请码

初始化完成后，页面会显示所有生成的邀请码，**请妥善保存**。  
每个邀请码只能使用一次，用于新用户注册。

#### 3.7 开始使用

点击页面上的 **“前往登录”** 按钮，使用管理员账号登录聊天室。

---

### 手动配置（高级用户）

如果您希望绕过初始化向导（例如在无头环境中部署），仍可手动创建所需文件：

- `usernames.list` – 每行一个用户名（**必须包含管理员账户**，初始管理员默认为 `admin`）
- `passwords.list` – 每行一个密码哈希（使用 `werkzeug.security.generate_password_hash` 生成）
- `colors.list` – 每行一个 CSS 颜色值（如 `red`、`#ff0000`）
- `invite_code.txt` – 每行一个邀请码

同时，在 `server.py` 中直接设置 `database_ip`、`database_port` 等变量（不推荐，因为初始化界面更易用）。

---

## ▶️ 启动服务

### 前台运行（调试）

```bash
python server.py
```

默认监听 `0.0.0.0:5000`，访问 `http://<server_ip>:5000` 即可。

### 后台运行（Linux / nohup）

项目提供了脚本：

```bash
# 启动（后台运行）
./start.sh

# 停止（会输出 PID，需手动 kill）
./stop.sh
```

---

## 🛠️ 管理员命令

登录管理员账户后，在聊天输入框中发送以下格式的命令：

- `command: clear` – 清空所有消息
- `command: delete 10` – 删除最后 10 条消息
- `command: change_color 张三 #00ff00` – 将用户“张三”的颜色改为绿色

命令执行成功或失败都会有日志记录（`log.txt`）。

---

## 🎨 自定义与进阶

### 前端样式

- `templates/login.html` – 登录页面样式
- `templates/chat.html` – 聊天主界面样式

可直接编辑 `<style>` 标签内的 CSS。

### 刷新与超时时间

在 `templates/chat.html` 中：

```javascript
setInterval(update, 1 * 1000);          // 消息轮询间隔（毫秒）
setInterval(login, 5 * 60 * 1000);      // 自动登出检查间隔（毫秒）
```

### 文件上传限制

可在 `server.py` 中添加配置：

```python
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 限制为 16MB
```

### 前端库

项目通过 CDN 引入了以下库（无需本地放置）：
- Font Awesome 5
- Highlight.js
- jQuery
- html2canvas

如需离线使用，可将文件放入 `static/` 并修改模板中的引用路径。

---

## 📁 文件上传说明

- 上传的文件保存在 `static/uploads/` 目录。
- 文件名自动去重（若重名则添加 `(1)`、`(2)` 等后缀）。
- 根据扩展名自动添加前缀：
  - 图片（`.jpg`、`.png`、`.jpeg`、`.bmp`）→ `::img::`
  - 音频（`.mp3`、`.wav`、`.flac`）→ `::wav::`
  - 其他文件 → `::file::`
- 前端会根据前缀渲染不同的样式（如图片预览、音频播放器）。

---

## 🗄️ 数据库结构

- 数据库：`chats`
- 集合：`values`（存储消息）和 `mutes`（存储禁言记录）
- 消息文档字段：
  - `id` – 消息唯一标识（UUID）
  - `user` – 发送者
  - `content` – 消息内容（包含标记）
  - `color` – 用户颜色
  - `time` – 显示时间（格式：`年:月:日:时:分`）
  - `created_at` – 创建时间戳（用于撤回时间限制）
  - `type` – 消息类型（`text`、`image`、`audio`、`file`、`emoji`、`system`）
  - `recalled` – 是否已撤回
  - `reply_to` – 回复的消息 ID（可选）

---

## ❓ 常见问题

**Q：首次访问时没有自动跳转到初始化页面？**  
A：请检查是否已存在 `config.json` 或 `usernames.list` 文件（若存在，系统会认为已初始化）。删除这些文件后重新访问即可。

**Q：初始化时提示“所有必填字段不能为空”？**  
A：请确保填写了数据库 IP、端口、管理员用户名和密码。

**Q：登录时提示“认证数据错误”？**  
A：检查初始化时创建的管理员密码是否输入正确，或确认 `usernames.list` 和 `passwords.list` 内容未被篡改。

**Q：注册时提示“无效的邀请码”？**  
A：确保使用的是初始化完成后页面显示的邀请码，注意大小写和空格。每个邀请码只能使用一次。

**Q：上传文件后消息未显示？**  
A：检查 `static/uploads/` 目录是否存在且可写，同时确认文件大小未超过 Flask 限制。

**Q：页面跳转链接无效（如 `http:///...`）？**  
A：请正确设置 `server_ip` 变量（位于 `server.py` 顶部），或使用初始化界面中的“服务器地址”字段配置。

**Q：聊天记录重启后丢失？**  
A：这说明应用未能连接到 MongoDB，而是使用了内存存储。请检查 MongoDB 服务是否运行，以及 `config.json` 中的连接信息是否正确。您可以在初始化页面使用“测试连接”功能进行诊断。

---

## 🧭 Modern IM 客户端

项目现在同时提供旧版兼容入口和现代客户端：

- `/chatts`、`/chattss`、`/chatts-new`、`/chatts_file` 继续服务 LiLan 和 OlivOSAIChatAssassin；旧消息字段、Emoji 路径和附件 URL 保持兼容。
- `/app` 是 React + TypeScript + Vite 构建的现代网页客户端，支持公共聊天室、私聊、Markdown、Reaction、SSE 实时更新、附件上传、纯文本文件预览/语法高亮、消息编辑/撤回和多主题。
- `/api/v2` 提供新客户端和机器人使用的 JSON/SSE API，包含资料、屏蔽、会话置顶/免打扰/归档、搜索、回复、转发、收藏、消息置顶、举报、通知和管理接口。机器人 token 在网页的“机器人 Token”设置中创建，每个用户只保留一个有效 token。
- 大文件可使用 `/api/v2/uploads/init`、`/chunks/<index>`、`/complete` 分片上传；普通附件优先使用 GridFS，旧磁盘附件仍按原文件名读取。
- 机器人使用 `Authorization: Bearer <token>` 访问 `/api/v2/bot/messages`、`/bot/events` 和 `/bot/streams`。流式消息按 `start -> delta -> complete/cancel` 生命周期提交，正文支持 Markdown 和换行。

前端构建需要 Node.js：

```bash
cd frontend
npm install
npm run build
```

生产环境仍只需要运行 Flask/Python；构建结果位于 `frontend/dist`。SSE 部署时需要使用支持长连接的 WSGI 服务，并关闭反向代理缓冲。

### 历史数据检查

迁移前运行只读扫描：

```bash
python migration_scan.py --json
```

扫描发现缺失图片、音频、文件、Emoji、未知字段或异常消息时会返回非零状态码，应该先处理报告再迁移。扫描不会修改 MongoDB 或文件。

普通新附件使用 GridFS；旧 `static/uploads` 文件和 `static/emoji/<用户名>` 目录保持可读。ZIP 只做目录结构预览，文本预览会返回多个编码候选，并在无法识别时回退到 UTF-8。

### 历史数据迁移 smoke test

如果旧版服务器的 MongoDB 和文件目录在另一台机器上，请先将旧版项目根目录（至少包含 `static/uploads`、`static/emoji`、`usernames.list`、`passwords.list`、`colors.list`）复制到可访问的位置，并确保当前机器能连接旧 MongoDB。然后双击：

```text
smoke_test_migration.bat
```

脚本会询问旧版项目根目录和 MongoDB URI。也可以直接运行：

```bash
python migration_smoke_test.py --source C:\old-chat --mongo-uri mongodb://user:password@host:27017/chats
```

它会只读检查消息转换投影、旧 `chat`/`content` 字段、稳定消息 ID、回复引用、图片/音频/普通文件、旧版 Emoji、用户列表、v2 文件元数据和磁盘文件是否存在。错误会让进程返回非零状态码；警告会列出未知字段和未被消息引用的孤立文件，但不会直接阻断。工具不会修改 MongoDB 或源文件，完整报告可用 `--json` 或 `--report report.json` 输出。修改测试器本身后可运行：

```bash
python migration_smoke_test.py --self-test
```

---

## 📄 许可证

本项目仅供学习交流使用，请勿用于非法用途。

---

## 🤝 贡献

欢迎提交 Issue 或 Pull Request 改进本项目。

---

> 若仍有疑问，请查看 `log.txt` 日志文件获取更多调试信息。
