"""config.json 读写与默认设置。"""
import json
import os

from . import state


def config_path():
    return os.path.join(state.DATA_DIR, 'config.json')


def load_config():
    if not os.path.exists(config_path()):
        return {}
    with open(config_path(), 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config(config):
    with open(config_path(), 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def default_settings():
    return {
        'db_ip': '127.0.0.1',
        'db_port': '27017',
        'db_user': '',
        'db_pass': '',
        'server_ip': '',
        'port': 5000,
        'admins': [],
        'base_path': '',
        'site_title': "syh's chatter",
        'poll_interval': 1000,
        'mute_default_seconds': 60,
        # 权限组（Phase 4 启用）
        'permission_groups': {
            'admin': ['*'],
            'moderator': ['message.send', 'message.recall.any',
                          'chat.delete', 'moderation.mute', 'moderation.unmute'],
            'user': ['message.send'],
        },
        'user_groups': {},
        'default_group': 'user',
        # 插件启用状态：{"插件名": true/false}
        'plugin_states': {},
        # 管理面板自定义快捷工具链接：[{"title": "...", "url": "..."}]
        'custom_tool_links': [],
    }


def load_settings():
    """合并 config.json 与默认值，并同步到 state。"""
    cfg = default_settings()
    cfg.update(load_config())
    apply_settings(cfg)
    return cfg


def normalize_base_path(value):
    """规范化挂载前缀：去空白与尾部斜杠，补前导斜杠。空值返回 ''。"""
    value = (value or '').strip().rstrip('/')
    if value and not value.startswith('/'):
        value = '/' + value
    return value


def apply_settings(cfg):
    state.settings = cfg
    state.server_ip = cfg.get('server_ip', '')
    state.base_path = normalize_base_path(cfg.get('base_path'))
    state.admins = list(cfg.get('admins') or [])
