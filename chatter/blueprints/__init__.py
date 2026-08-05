"""蓝图工厂与注册列表。"""
from flask import Blueprint

from .. import state

# 各蓝图共享包内模板目录
TEMPLATE_DIR = state.TEMPLATE_DIR


def make_blueprint(name):
    return Blueprint(name, __name__, template_folder=TEMPLATE_DIR)


def make_static_blueprint():
    """提供项目 static/ 目录的静态蓝图（遵循 base_path 前缀）。"""
    return Blueprint(
        'chatter_static', __name__,
        static_folder=state.STATIC_DIR,
        static_url_path='/static',
    )


from .auth_routes import bp as bp_auth  # noqa: E402
from .chat_routes import bp as bp_chat  # noqa: E402
from .init_routes import bp as bp_init  # noqa: E402
from .admin_page import bp as bp_admin_page  # noqa: E402
from .admin_api import bp as bp_admin_api  # noqa: E402
