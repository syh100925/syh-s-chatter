# 插件 API 手册

syh's chatter 插件系统允许在不修改核心代码的前提下扩展聊天室能力：新增页面/接口、注册聊天命令、监听消息事件、注入 CSS/JS、向"工具集"弹窗添加链接。

插件目录固定为项目根目录的 `plugins/`。启动时自动发现并加载，启用/禁用与重载可在**管理面板 → 插件**中操作。

---

## 1. 插件格式

### 1.1 文件夹式（推荐）

```
plugins/my_plugin/
├── manifest.json     # 必填：插件元信息
├── main.py           # 入口（可由 manifest.entry 指定其他文件名）
├── config.json       # 可选：插件配置（管理面板可编辑 JSON）
├── templates/        # 可选：供插件蓝图渲染的模板
└── static/           # 可选：插件静态资源
```

`manifest.json` 字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | 插件名（用于启用状态、权限点命名） |
| `entry` | 否 | 入口文件，默认 `main.py` |
| `version` | 否 | 版本号，默认 `0.0.0` |
| `author` | 否 | 作者 |
| `description` | 否 | 描述 |

### 1.2 单文件式

`plugins/<name>.py`，模块级定义 `PLUGIN_INFO` 字典声明元信息：

```python
PLUGIN_INFO = {'name': 'echo', 'version': '0.1.0', 'author': 'syh'}
```

---

## 2. 入口与生命周期

每个插件必须定义入口函数 `on_load(ctx)`（推荐），在加载时被调用一次，接收一个 `PluginContext` 实例：

```python
def on_load(ctx):
    # 通过 ctx 注册能力...
```

`ctx` 常用属性：`name`、`version`、`author`、`description`、`directory`（插件目录绝对路径）、`enabled`（是否启用）。

---

## 3. PluginContext 注册 API

| 方法 | 用途 |
| --- | --- |
| `ctx.register_blueprint(blueprint, url_prefix='')` | 注册 Flask 蓝图（页面/API 路由） |
| `ctx.add_command(name, fn, permission=None, description='')` | 注册聊天命令 `command: <name> ...` |
| `ctx.on(event, handler)` | 注册钩子事件处理器 |
| `ctx.add_css(css)` | 注入 CSS：传原始 CSS 字符串，或插件目录内 `.css` 文件路径 |
| `ctx.add_js(js)` | 注入 JS：传原始 JS 字符串，或插件目录内 `.js` 文件路径 |
| `ctx.add_tool_link(title, url)` | 向聊天室"工具集"弹窗添加链接 |
| `ctx.get_config(key=None, default=None)` | 读取插件 `config.json`（不带 key 返回整个配置） |
| `ctx.set_config(key, value)` | 写入插件 `config.json` 的指定键 |
| `ctx.config_path()` | 插件 `config.json` 的绝对路径 |

> **add_css / add_js 注入规则**：以 `<` 开头的字符串视为完整标签原样保留（如 `<link>`、`<script src=...>`）；以 `.css` / `.js` 结尾的字符串且不是 `<` 开头时，当作插件目录内相对文件路径读取内容；其余内容会被自动包裹进 `<style>` / `<script>` 标签。
>
> **add_tool_link 规则**：以 `/` 开头的站内链接会自动补上 `base_path` 前缀（如配置了 `/chat` 挂载路径时 `/about` 会变成 `/chat/about`）。

### 3.1 聊天命令

`add_command` 的命令函数签名：

```python
def cmd_hello(username, parts, d_time, command_str):
    # username   : 发送命令的用户名
    # parts      : command_str[9:].split() 的结果，parts[0] 为命令名
    # d_time     : 当前时间字符串（HH:MM:SS）
    # command_str: 用户发送的完整消息（以 "command: " 开头）
    return <序列化消息 dict 或 None>
```

- 返回 `messages.add_system_message(...)` 或 `messages.serialize_message(...)` 的字典，该消息会入库并展示给所有用户。
- 返回 `None` 表示命令不成立，原文本会被当作普通消息发送。
- 命令函数抛异常会被调用方捕获并记入日志，不影响其他用户。

`permission` 参数：执行该命令所需的权限点，留空（`None`）表示所有用户可用。自定义权限点建议使用 `plugins.<插件名>.<动作>` 命名空间，例如 `plugins.echo.echo`。自定义权限点会自动出现在**管理面板 → 权限组**的可勾选列表中，也支持通配符（如 `plugins.echo.*`）。

### 3.2 蓝图

```python
from flask import Blueprint

bp = Blueprint('my_pages', __name__)

@bp.route('/plugins/my_plugin/about')
def about():
    return '<h1>插件页面</h1>'

ctx.register_blueprint(bp)   # url_prefix 可选，默认为全局 base_path
```

> **注意**：Flask 在应用处理首个请求后禁止注册新蓝图。运行中通过"重载全部"启用的新蓝图不会生效，需重启服务；聊天命令、钩子、CSS/JS 注入则即时生效。

---

## 4. 钩子事件

通过 `ctx.on(event, handler)` 注册。事件表：

| 事件 | 处理器签名 | 说明 |
| --- | --- | --- |
| `message_send` | `handler(document, username)` | 消息入库前调用；`document` 为待插入的文档（含 `id`/`content`/`user`/`time`/`type`/`reply_to` 等字段），可原地修改；返回 `False` 拦截该消息 |
| `chat_data` | `handler(payload, username)` | 发送给前端的 `/chattss` JSON 负载（`messages`/`permissions`/`muted` 等），可原地修改 |
| `login` | `handler(username)` | 用户登录成功 |
| `logout` | `handler(username)` | 用户登出 |
| `register` | `handler(username)` | 新用户注册成功 |
| `message_recall` | `handler(message_id, username)` | 消息被撤回后 |

**拦截语义**：`plugin_manager.emit(event, **kwargs)` 遍历所有插件的处理器；任一处理器返回 `False` 视为拦截。当前只有 `message_send` 利用该语义（返回 False 则消息不入库）。处理器抛异常不会影响其他插件，异常会被记录到日志。

---

## 5. 示例

### 5.1 echo（单文件式，项目自带）

```python
# plugins/echo.py
PLUGIN_INFO = {'name': 'echo', 'version': '0.1.0', 'author': 'syh'}

def on_load(ctx):
    def cmd_echo(username, parts, d_time, command_str):
        from chatter import messages
        return messages.add_system_message('[echo] ' + command_str[len('command: echo'):].strip())
    ctx.add_command('echo', cmd_echo, permission='plugins.echo.echo')
```

发送 `command: echo 你好`，所有用户都会看到系统消息 `[echo] 你好`。

### 5.2 hello_world（文件夹式，项目自带）

`plugins/hello_world/` 演示了全部主要能力：

- `register_blueprint`：提供 `/plugins/hello_world/about` 页面
- `add_command('hello', ...)`：`command: hello 张三` 产生问候系统消息
- `add_css` / `add_js`：修改聊天室外观、注入脚本
- `add_tool_link`：在"工具集"弹窗添加指向插件页面的链接
- `on('message_send', ...)`：在控制台打印每条新消息

---

## 6. 调试建议

- 插件加载失败不会阻止服务启动，错误会记录到日志（`log.txt` 与控制台）。
- `ctx.add_js("console.log('loaded');")` 可在浏览器控制台验证注入是否生效。
- 管理面板"插件"标签页可查看每个插件的启用状态与加载状态；启用/禁用即时生效，修改代码后点击"重载全部"（蓝图类变更除外）。
- 插件可直接 `from chatter import messages, permissions, state, ...` 访问核心模块，但请勿修改 `state` 中的核心结构。

---

## 7. 已知限制

- 蓝图注册需在首个请求前完成；运行中重载仅对命令/钩子/注入生效。
- 插件目录以项目根目录 `plugins/` 为固定位置（不随 `data_dir` 迁移）。
- 插件代码与主程序同权限运行，请仅加载可信来源的插件。
