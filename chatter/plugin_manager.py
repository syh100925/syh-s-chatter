"""插件系统：发现、加载、钩子、命令、外观注入。

插件格式（两者都支持）：
1. 文件夹式：plugins/<name>/manifest.json + 入口文件（默认 main.py），
   可包含 templates/、static/ 以及 config.json（插件配置）。
2. 单文件式：plugins/<name>.py，模块级 PLUGIN_INFO 字典声明元信息。

插件入口须定义 on_load(ctx)（推荐），或利用模块级钩子函数。

钩子事件：
- message_send(document, username)：消息入库前，可修改 document，返回 False 拦截
- chat_data(payload)：发送给前端的 /chattss JSON 负载（可原地修改）
- login(username) / logout(username) / register(username)
- message_recall(message_id, username)

注意：注册蓝图/路由的插件，启用状态变化需重启服务生效；
CSS/JS 注入、命令与钩子即时生效。
"""
import importlib.util
import json
import os
import sys
import uuid

from . import commands, config, state

PLUGIN_DIR_NAME = 'plugins'

_contexts = []
_by_name = {}


def plugin_dir():
    # 插件是代码而非数据，固定位于包所在项目根目录的 plugins/ 下
    return os.path.join(state.PROJECT_ROOT, PLUGIN_DIR_NAME)


def known_permissions():
    perms = set()
    for ctx in _contexts:
        for cmd in ctx._commands:
            if cmd.get('permission'):
                perms.add(cmd['permission'])
    return sorted(perms)


class PluginContext:
    """插件运行时上下文：插件通过它向系统注册能力。"""

    def __init__(self, name, module, directory, info):
        self.name = name
        self.version = info.get('version', '0.0.0')
        self.author = info.get('author', '')
        self.description = info.get('description', '')
        self.directory = directory
        self.module = module
        self.enabled = True
        self._blueprints = []
        self._commands = []
        self._handlers = {}
        self._css = []
        self._js = []
        self._tool_links = []

    # ---------------- 注册接口 ----------------

    def register_blueprint(self, blueprint, url_prefix=''):
        """注册新服务（页面/API 路由）。"""
        self._blueprints.append((blueprint, url_prefix))

    def add_command(self, name, fn, permission=None, description=''):
        """注册聊天命令：command: <name> ..."""
        self._commands.append({
            'name': name, 'fn': fn, 'permission': permission,
            'description': description or '',
        })

    def on(self, event, handler):
        """注册钩子事件处理器。"""
        self._handlers.setdefault(event, []).append(handler)

    def add_css(self, css):
        """注入 CSS 到聊天室页面头部；可传原始 CSS 字符串或插件目录内文件路径。"""
        self._css.append(css)

    def add_js(self, js):
        """注入 JS 到聊天室页面头部；可传原始 JS 字符串或插件目录内文件路径。"""
        self._js.append(js)

    def add_tool_link(self, title, url):
        """在聊天室"工具集"弹窗中加入链接。"""
        self._tool_links.append((title, url))

    # ---------------- 插件配置 ----------------

    def config_path(self):
        return os.path.join(self.directory, 'config.json')

    def get_config(self, key=None, default=None):
        try:
            with open(self.config_path(), 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = {}
        return cfg.get(key, default) if key is not None else cfg

    def set_config(self, key, value):
        cfg = self.get_config()
        cfg[key] = value
        with open(self.config_path(), 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True


# ---------------- 发现与加载 ----------------

def discover():
    """扫描插件目录，返回插件描述列表。"""
    directory = plugin_dir()
    if not os.path.isdir(directory):
        return []
    found = []
    for entry in sorted(os.listdir(directory)):
        path = os.path.join(directory, entry)
        if os.path.isdir(path):
            manifest = os.path.join(path, 'manifest.json')
            if not os.path.isfile(manifest):
                continue
            try:
                with open(manifest, 'r', encoding='utf-8') as f:
                    info = json.load(f)
            except (json.JSONDecodeError, OSError):
                state.logger.exception('插件 manifest 解析失败: %s', path)
                continue
            entry_file = info.get('entry', 'main.py')
            entry_path = os.path.join(path, entry_file)
            if not os.path.isfile(entry_path):
                entry_path = os.path.join(path, 'main.py')
            if not os.path.isfile(entry_path):
                state.logger.warning('插件缺少入口文件: %s', path)
                continue
            name = info.get('name') or entry
            found.append({
                'name': name, 'kind': 'folder', 'path': entry_path,
                'info': info, 'dir': path,
            })
        elif entry.endswith('.py'):
            found.append({
                'name': entry[:-3], 'kind': 'file', 'path': path,
                'info': {'name': entry[:-3]}, 'dir': directory,
            })
    return found


def _load_module(plugin):
    module_name = 'chatter_plugin_%s_%s' % (plugin['name'], uuid.uuid4().hex[:8])
    spec = importlib.util.spec_from_file_location(module_name, plugin['path'])
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_plugin(plugin):
    """加载单个插件，返回 PluginContext；失败返回 None。"""
    try:
        module = _load_module(plugin)
        info = dict(plugin['info'])
        if plugin['kind'] == 'file':
            module_info = getattr(module, 'PLUGIN_INFO', None)
            if isinstance(module_info, dict):
                info.update(module_info)
        ctx = PluginContext(info.get('name', plugin['name']), module, plugin['dir'], info)
        ctx.enabled = is_enabled(ctx.name)
        on_load = getattr(module, 'on_load', None)
        if on_load:
            on_load(ctx)
        return ctx
    except Exception:
        state.logger.exception('插件加载失败: %s', plugin['path'])
        return None


def is_enabled(name):
    states = state.settings.get('plugin_states') or {}
    return states.get(name, True)


def register_ctx(ctx, app):
    for blueprint, prefix in ctx._blueprints:
        url_prefix = state.base_path
        if prefix:
            url_prefix = (url_prefix + '/' + prefix.strip('/')).rstrip('/')
        try:
            app.register_blueprint(blueprint, url_prefix=url_prefix)
        except AssertionError:
            # 应用已处理过首个请求后无法再注册蓝图，命令与钩子仍即时生效
            state.logger.warning('插件 %s 的蓝图在运行中无法注册（重启生效）', ctx.name)
    for cmd in ctx._commands:
        commands.COMMANDS[cmd['name']] = {
            'fn': cmd['fn'], 'permission': cmd['permission'],
            'description': cmd['description'], 'plugin': ctx.name,
        }
    _contexts.append(ctx)
    _by_name[ctx.name] = ctx


def unload_ctx(ctx):
    for name in [n for n, entry in list(commands.COMMANDS.items()) if entry.get('plugin') == ctx.name]:
        del commands.COMMANDS[name]
    if ctx in _contexts:
        _contexts.remove(ctx)
    _by_name.pop(ctx.name, None)


def init(app):
    """加载所有已启用插件。"""
    for plugin in discover():
        if not is_enabled(plugin['name']):
            continue
        ctx = load_plugin(plugin)
        if ctx is None:
            continue
        register_ctx(ctx, app)


def reload_plugins(app):
    """重载全部插件（管理面板使用）。蓝图类变更仍需重启生效。"""
    for ctx in list(_contexts):
        unload_ctx(ctx)
    init(app)


def set_enabled(name, enabled):
    cfg = config.load_config()
    states = cfg.setdefault('plugin_states', {})
    states[name] = bool(enabled)
    config.save_config(cfg)
    config.load_settings()
    ctx = _by_name.get(name)
    if ctx is not None:
        ctx.enabled = bool(enabled)
    return bool(enabled)


# ---------------- 事件分发 ----------------

def emit(event, **kwargs):
    """事件分发；任一处理器返回 False 视为拦截（返回 False）。"""
    blocked = False
    for ctx in list(_contexts):
        for handler in ctx._handlers.get(event, []):
            try:
                result = handler(**kwargs)
            except Exception:
                state.logger.exception('插件 %s 的 %s 钩子异常', ctx.name, event)
                continue
            if result is False:
                blocked = True
    return not blocked


# ---------------- 前端注入 ----------------

def _read_asset(ctx, item, ext):
    item = str(item).strip()
    if item.endswith(ext) and not item.startswith('<'):
        path = os.path.join(ctx.directory, item)
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()
            except OSError:
                return None
    return item


def _wrap_injection(text, tag):
    """将裸 CSS/JS 代码包裹进 <style>/<script> 标签；已带完整标签的项原样保留。"""
    if text.lstrip().startswith('<'):
        return text
    return '<%s>\n%s\n</%s>' % (tag, text, tag)


def head_injections():
    """返回 {'css': [...], 'js': [...]}，每项已包裹 <style>/<script> 标签。"""
    css_parts = []
    js_parts = []
    for ctx in _contexts:
        for item in ctx._css:
            text = _read_asset(ctx, item, '.css')
            if text:
                css_parts.append(_wrap_injection(text, 'style'))
        for item in ctx._js:
            text = _read_asset(ctx, item, '.js')
            if text:
                js_parts.append(_wrap_injection(text, 'script'))
    return {'css': css_parts, 'js': js_parts}


def tool_links():
    links = []
    for ctx in _contexts:
        for title, url in ctx._tool_links:
            # 以 / 开头的站内链接自动补 base_path 前缀
            if url.startswith('/') and not url.startswith(state.base_path):
                url = state.base_path + url
            links.append((title, url))
    return links


def list_plugins():
    """管理面板用：所有插件（含未启用）的状态信息。"""
    result = []
    for plugin in discover():
        name = plugin['name']
        ctx = _by_name.get(name)
        if ctx is not None:
            result.append({
                'name': ctx.name, 'kind': plugin['kind'], 'version': ctx.version,
                'author': ctx.author, 'description': ctx.description,
                'enabled': ctx.enabled, 'loaded': True,
                'has_config': os.path.isfile(ctx.config_path()),
            })
        else:
            result.append({
                'name': name, 'kind': plugin['kind'],
                'version': plugin['info'].get('version', ''),
                'author': plugin['info'].get('author', ''),
                'description': plugin['info'].get('description', ''),
                'enabled': is_enabled(name), 'loaded': False,
                'has_config': os.path.isfile(os.path.join(plugin['dir'], 'config.json')),
            })
    return result
