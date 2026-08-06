"""syh's chatter —— 可嵌入的 Flask 聊天室应用。

独立运行：
    from chatter import create_app
    app = create_app()

嵌入宿主 Flask 应用（挂载到子路径）：
    from chatter import register_into
    register_into(your_app, base_path='/chat', data_dir='./data')

宿主应用也可通过 werkzeug DispatcherMiddleware 挂载整个 app。
"""
import os

from flask import Flask, redirect, request

from . import config, database, plugin_manager, state, traffic, users
from .blueprints import (TEMPLATE_DIR, bp_admin_api, bp_admin_page, bp_auth,
                         bp_chat, bp_init, make_static_blueprint)


def _register_static(app):
    app.register_blueprint(make_static_blueprint(),
                           url_prefix=state.base_path)


def _register_blueprints(app):
    _register_static(app)
    app.register_blueprint(bp_init, url_prefix=state.base_path)
    app.register_blueprint(bp_auth, url_prefix=state.base_path)
    app.register_blueprint(bp_chat, url_prefix=state.base_path)
    app.register_blueprint(bp_admin_page, url_prefix=state.base_path)
    app.register_blueprint(bp_admin_api, url_prefix=state.base_path)


def register_into(app, settings=None, data_dir=None, base_path=None):
    """将聊天室全部蓝图、钩子与模板注册进宿主 Flask 应用。

    - settings: 配置字典（省略则从 config.json 读取）
    - data_dir: 数据目录（config.json、*.list、log.txt、插件目录），
      默认项目根目录
    - base_path: 挂载路径前缀（如 '/chat'），默认读取 config.json 的 base_path
    """
    state.app = app
    if data_dir:
        state.DATA_DIR = data_dir
    state.setup_logger()

    cfg = config.load_settings() if settings is None else config.apply_settings(dict(settings))
    if base_path is not None:
        cfg['base_path'] = base_path
        config.apply_settings(cfg)

    # 确保会话文件存在
    for filename in ('login_users.txt', 'login_passes.txt'):
        open(os.path.join(state.DATA_DIR, filename), 'a', encoding='utf-8').close()

    database.init_database()
    users.reload_users()

    app.config.update({
        'MAX_CONTENT_LENGTH': 64 * 1024 * 1024,
    })

    _register_blueprints(app)

    # 聊天室页面统一自定义鼠标指针（仅核心聊天室蓝图；插件/宿主页面不受影响）。
    # 用 after_request 注入而非改模板：新增聊天室路由自动生效。
    core_blueprints = ('auth', 'chat', 'init', 'admin_page', 'admin_api')
    cursor_style = ("<style>*{cursor:url('%s/static/cur-default.png'),auto;}</style>"
                    % state.base_path)

    @app.after_request
    def apply_chatroom_cursor(response):
        if response.mimetype == 'text/html' and request.blueprint in core_blueprints:
            html = response.get_data(as_text=True)
            if '<head>' in html:
                html = html.replace('<head>', '<head>' + cursor_style, 1)
            elif '</body>' in html:
                html = html.replace('</body>', cursor_style + '</body>', 1)
            response.set_data(html)
        return response

    @app.before_request
    def check_initialized():
        bp = state.base_path
        static_prefix = bp + '/static'
        if (request.path.startswith(static_prefix)
                or request.path in (bp + '/init', bp + '/init/ping', bp + '/init/status',
                                    '/favicon.ico')):
            return
        if not os.path.exists(config.config_path()) or not os.path.exists(
                os.path.join(state.DATA_DIR, 'usernames.list')):
            return redirect(bp + '/init')
        with open(os.path.join(state.DATA_DIR, 'usernames.list'), 'r', encoding='utf-8') as f:
            if not f.read().strip():
                return redirect(bp + '/init')

    @app.before_request
    def record_traffic():
        traffic.record()

    @app.context_processor
    def inject_globals():
        injections = plugin_manager.head_injections()
        links = []
        for link in plugin_manager.tool_links():
            if not link.get('enabled', True):
                continue
            url = str(link.get('url') or '').strip()
            title = str(link.get('title') or '').strip()
            if not title or not url:
                continue
            # 以 / 开头的地址一律按根路径定位（插件条目同样为绝对注册），
            # 不再自动追加 base_path 前缀；其余地址原样（相对当前页面）
            links.append({
                'title': title,
                'url': url,
                'icon': str(link.get('icon') or '').strip() or None,
            })
        return {
            'base_path': state.base_path,
            'site_title': state.settings.get('site_title', "syh's chatter"),
            'plugin_css': '\n'.join(injections['css']),
            'plugin_js': '\n'.join(injections['js']),
            'tool_links': links,
            'poll_interval': int(state.settings.get('poll_interval', 1000)),
        }

    plugin_manager.init(app)
    return app


def create_app(settings=None, data_dir=None, base_path=None):
    """创建独立的聊天室 Flask 应用。"""
    app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=None)
    register_into(app, settings=settings, data_dir=data_dir, base_path=base_path)
    if state.base_path:
        # 独立运行时，裸根路径重定向到挂载前缀（嵌入宿主应用时不注册此路由）
        @app.route('/')
        def root_redirect():
            return redirect(state.base_path + '/')

        # 裸前缀（无尾斜杠）也重定向到带斜杠路径。
        # 显式注册此路由可避免 Werkzeug 自动 308 跳转生成绝对 URL
        # （反代/HTTPS 场景下会错误带上 :443 等端口），改为相对跳转。
        @app.route(state.base_path)
        def base_path_redirect():
            return redirect(state.base_path + '/')
    return app
