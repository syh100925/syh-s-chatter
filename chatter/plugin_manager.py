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

注意：启用/禁用/重载在运行中即时生效（命令、钩子、CSS/JS 注入、快捷工具链接）；
已注册的蓝图路由因 Flask 限制无法注销，含新蓝图注册的变更需重启服务生效。
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
        self._module_name = None  # sys.modules 中的模块名（停止时清理）

    # ---------------- 注册接口 ----------------

    def register_blueprint(self, blueprint, url_prefix=''):
        """注册新服务（页面/API 路由），挂载到 base_path 前缀下。"""
        self._blueprints.append((blueprint, url_prefix, False))

    def register_blueprint_absolute(self, blueprint, url_prefix=''):
        """注册新服务（页面/API 路由），忽略 base_path，直接挂载到根路径。

        适用于自带绝对 URL 的旧服务（如迁移自旧 server.py 的插件），
        保证 base_path 变更不影响其地址。
        """
        self._blueprints.append((blueprint, url_prefix, True))

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
        ctx._module_name = module.__name__
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


def _register_blueprint(app, blueprint, url_prefix, ctx_name):
    """注册插件蓝图；热重载导致同名蓝图已注册时，换唯一名重试。"""
    try:
        app.register_blueprint(blueprint, url_prefix=url_prefix)
        return True
    except ValueError:
        pass  # 同名蓝图已注册（热重载/热启动时），进入重试
    blueprint.name = '%s_r%d' % (blueprint.name, 2)
    try:
        app.register_blueprint(blueprint, url_prefix=url_prefix)
        return True
    except (AssertionError, ValueError):
        # 应用已处理过首个请求后无法再注册蓝图，命令与钩子仍即时生效
        state.logger.warning('插件 %s 的蓝图无法在运行中注册（需重启服务生效）', ctx_name)
        return False


def _ensure_blueprint_templates(ctx, blueprint):
    """修正插件蓝图的模板目录。

    插件以无点模块名加载（chatter_plugin_<name>_<hex>），Flask 的
    Blueprint(import_name) 据此推断 root_path 会得到不存在的路径；
    且默认 template_folder 为 None，插件 templates/ 目录不会被注册进
    Jinja 搜索路径，render_template 会一直 TemplateNotFound。
    这里在注册前把 root_path 指向插件目录，并显式挂载 templates/。
    """
    template_folder = blueprint.template_folder or 'templates'
    plugin_templates = os.path.join(ctx.directory, template_folder)
    if not os.path.isdir(plugin_templates):
        return
    if blueprint.template_folder is None:
        blueprint.template_folder = template_folder
    current = os.path.join(blueprint.root_path, blueprint.template_folder)
    if not os.path.isdir(current):
        blueprint.root_path = ctx.directory


def register_ctx(ctx, app):
    for blueprint, prefix, absolute in ctx._blueprints:
        _ensure_blueprint_templates(ctx, blueprint)
        if absolute:
            # 绝对注册：忽略 base_path，前缀原样挂载到根路径
            url_prefix = ('/' + prefix.strip('/')).rstrip('/') if prefix else ''
        else:
            url_prefix = state.base_path
            if prefix:
                url_prefix = (url_prefix + '/' + prefix.strip('/')).rstrip('/')
        _register_blueprint(app, blueprint, url_prefix, ctx.name)
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


def stop_plugin(name):
    """热停止插件：卸载命令/钩子/CSS·JS 注入/工具链接，并清理内存中的模块。

    已注册的蓝图路由因 Flask 限制无法注销，仍保持可访问。
    """
    ctx = _by_name.get(name)
    if ctx is None:
        return False
    unload_ctx(ctx)
    if ctx._module_name:
        sys.modules.pop(ctx._module_name, None)
    state.logger.info('插件已停止: %s', name)
    return True


def start_plugin(name):
    """热启动/热加载插件：从磁盘重新加载入口代码并注册。

    对新增的插件文件同样有效（discover 实时扫描插件目录）。
    """
    if name in _by_name:
        return True
    discovered = discover()
    # 快路径：目录名/文件名/清单名匹配
    for plugin in discovered:
        if plugin['name'] != name and plugin['info'].get('name') != name:
            continue
        ctx = load_plugin(plugin)
        if ctx is None:
            state.logger.error('插件启动失败: %s', name)
            return False
        register_ctx(ctx, state.app)
        state.logger.info('插件已启动: %s', name)
        return True
    # 兜底：按元信息名称匹配（单文件插件 PLUGIN_INFO.name 与文件名不同）
    for plugin in discovered:
        ctx = load_plugin(plugin)
        if ctx is None:
            continue
        if ctx.name == name:
            register_ctx(ctx, state.app)
            state.logger.info('插件已启动: %s', name)
            return True
        unload_ctx(ctx)
    state.logger.warning('未找到插件: %s', name)
    return False


def reload_plugin(name):
    """热重载单个插件（重新执行入口代码）。仅对已启用插件生效。"""
    if name in _by_name:
        stop_plugin(name)
    if not is_enabled(name):
        return False, '插件未启用，请先启用'
    if not start_plugin(name):
        return False, '插件加载失败（详见 log.txt）'
    return True, ''


def reload_plugins(app):
    """热重载全部已启用插件。"""
    for ctx in list(_contexts):
        stop_plugin(ctx.name)
    init(app)


def set_enabled(name, enabled):
    """持久化启用状态并即时热启停插件（命令/钩子/注入立即生效）。"""
    cfg = config.load_config()
    states = cfg.setdefault('plugin_states', {})
    states[name] = bool(enabled)
    config.save_config(cfg)
    config.load_settings()
    if enabled:
        start_plugin(name)
    else:
        stop_plugin(name)
    return bool(enabled)


def is_loaded(name):
    return name in _by_name


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
    """返回合并后的快捷工具列表（自定义 + 插件，自动过滤已删除的插件条目）。

    每条为 dict：{key, plugin, title, url, icon, enabled}
    - 自定义条目：无 key/plugin 字段，完全由管理员维护。
    - 插件条目：由 add_tool_link 动态并入（追加到列表末尾），带稳定 key
      （plugin|url）用于匹配；管理员可在设置中修改/禁用/排序/删除，
      删除的 key 记入 config.json 的 removed_plugin_links 不再出现。
    """
    settings = state.settings or {}
    custom = list(settings.get('custom_tool_links') or [])
    removed = set(settings.get('removed_plugin_links') or [])
    seen = set()
    for entry in custom:
        key = entry.get('key')
        if key:
            seen.add(key)
    for ctx in _contexts:
        for title, url in ctx._tool_links:
            key = '%s|%s' % (ctx.name, url)
            if key in removed or key in seen:
                continue
            custom.append({
                'key': key,
                'plugin': ctx.name,
                'title': title,
                'url': url,
                'icon': None,
                'enabled': True,
            })
            seen.add(key)
    return custom


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
