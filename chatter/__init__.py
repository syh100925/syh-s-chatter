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
        links = plugin_manager.tool_links()
        for link in (state.settings.get('custom_tool_links') or []):
            title = str(link.get('title') or '').strip()
            url = str(link.get('url') or '').strip()
            if title and url:
                if url.startswith('/') and not url.startswith(state.base_path):
                    url = state.base_path + url
                links.append((title, url))
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
    return app
