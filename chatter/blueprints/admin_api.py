"""管理面板 JSON API（全部接口需登录且具备对应 admin.* 权限）。"""
import json
import os
import random
import string

from flask import jsonify, request

from .. import auth, config, messages, permissions, plugin_manager, state, traffic, users
from ..state import logger
from . import make_blueprint

bp = make_blueprint('admin_api')


def _require(permission):
    """返回 (username, error_response)；无权限时 error_response 非 None。"""
    username = auth.authenticate_request()
    if not username:
        return None, auth.json_error('认证数据错误', 401)
    if not permissions.has_permission(username, permission):
        return None, auth.json_error('没有管理权限', 403)
    return username, None


# ---------------- 用户 ----------------

@bp.route('/admin/api/users', methods=['GET'])
def api_users():
    actor, error = _require('admin.users')
    if error:
        return error
    user_groups = state.settings.get('user_groups') or {}
    return jsonify({
        'ok': True,
        'users': [{
            'username': name,
            'color': users.get_user_color(name),
            'group': user_groups.get(name, state.settings.get('default_group', 'user')),
            'is_admin': permissions.is_admin(name),
        } for name in state.usernames],
    })


@bp.route('/admin/api/users/rename', methods=['POST'])
def api_user_rename():
    actor, error = _require('admin.users')
    if error:
        return error
    payload = auth.request_payload()
    old_name = (payload.get('username') or '').strip()
    new_name = (payload.get('new_name') or '').strip()
    if not old_name or not new_name:
        return auth.json_error('参数不完整', 400)
    if old_name == actor:
        return auth.json_error('不能修改自己的用户名', 400)
    if new_name == 'system':
        return auth.json_error('该用户名被系统保留', 400)
    if not users.rename_user(old_name, new_name):
        return auth.json_error('用户不存在或新用户名已存在', 400)
    user_groups = state.settings.get('user_groups') or {}
    if old_name in user_groups:
        user_groups[new_name] = user_groups.pop(old_name)
        cfg = config.load_config()
        cfg['user_groups'] = user_groups
        config.save_config(cfg)
        config.load_settings()
    sessions = auth.load_sessions()
    if old_name in sessions:
        sessions[new_name] = sessions.pop(old_name)
        auth.save_sessions(sessions)
    return jsonify({'ok': True})


@bp.route('/admin/api/users/password', methods=['POST'])
def api_user_password():
    actor, error = _require('admin.users')
    if error:
        return error
    payload = auth.request_payload()
    username = (payload.get('username') or '').strip()
    new_password = payload.get('new_password') or ''
    if not username or not new_password:
        return auth.json_error('参数不完整', 400)
    from werkzeug.security import generate_password_hash
    if not users.change_password(username, generate_password_hash(new_password)):
        return auth.json_error('用户不存在', 404)
    return jsonify({'ok': True})


@bp.route('/admin/api/users/color', methods=['POST'])
def api_user_color():
    actor, error = _require('admin.users')
    if error:
        return error
    payload = auth.request_payload()
    username = (payload.get('username') or '').strip()
    color = (payload.get('color') or '').strip()
    if not username or not color:
        return auth.json_error('参数不完整', 400)
    if not users.set_user_color(username, color):
        return auth.json_error('用户不存在', 404)
    return jsonify({'ok': True})


@bp.route('/admin/api/users/delete', methods=['POST'])
def api_user_delete():
    actor, error = _require('admin.users')
    if error:
        return error
    payload = auth.request_payload()
    username = (payload.get('username') or '').strip()
    if not username:
        return auth.json_error('参数不完整', 400)
    if username == actor:
        return auth.json_error('不能删除自己', 400)
    if username in state.admins:
        return auth.json_error('管理员用户不能被删除，请先从管理员列表移除', 400)
    if not users.delete_user(username):
        return auth.json_error('用户不存在', 404)
    sessions = auth.load_sessions()
    sessions.pop(username, None)
    auth.save_sessions(sessions)
    try:
        state.mutes.delete_many({'username': username})
    except Exception:
        pass
    user_groups = state.settings.get('user_groups') or {}
    if username in user_groups:
        user_groups.pop(username, None)
        cfg = config.load_config()
        cfg['user_groups'] = user_groups
        config.save_config(cfg)
        config.load_settings()
    logger.info('管理员 %s 删除了用户 %s', actor, username)
    return jsonify({'ok': True})


@bp.route('/admin/api/users/group', methods=['POST'])
def api_user_group():
    actor, error = _require('admin.groups')
    if error:
        return error
    payload = auth.request_payload()
    username = (payload.get('username') or '').strip()
    group = (payload.get('group') or '').strip()
    groups = state.settings.get('permission_groups') or {}
    if username not in state.usernames:
        return auth.json_error('用户不存在', 404)
    if group and group not in groups:
        return auth.json_error('权限组不存在', 404)
    cfg = config.load_config()
    user_groups = dict(state.settings.get('user_groups') or {})
    if group and group != state.settings.get('default_group'):
        user_groups[username] = group
    else:
        user_groups.pop(username, None)
    cfg['user_groups'] = user_groups
    config.save_config(cfg)
    config.load_settings()
    return jsonify({'ok': True})


@bp.route('/admin/api/invites', methods=['POST'])
def api_invites():
    actor, error = _require('admin.users')
    if error:
        return error
    payload = auth.request_payload()
    try:
        count = int(payload.get('count', 1))
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(count, 50))
    existing = set(state.read_lines('invite_code.txt'))
    generated = []
    for _ in range(count):
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        existing.add(code)
        generated.append(code)
    with open(os.path.join(state.DATA_DIR, 'invite_code.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(existing)) + '\n')
    return jsonify({'ok': True, 'codes': generated})


# ---------------- 权限组 ----------------

@bp.route('/admin/api/groups', methods=['GET'])
def api_groups():
    actor, error = _require('admin.groups')
    if error:
        return error
    return jsonify({
        'ok': True,
        'groups': permissions.all_groups(),
        'points': permissions.all_permission_points(),
        'default_group': state.settings.get('default_group', 'user'),
    })


@bp.route('/admin/api/groups/save', methods=['POST'])
def api_groups_save():
    actor, error = _require('admin.groups')
    if error:
        return error
    payload = auth.request_payload()
    groups = payload.get('groups')
    if not isinstance(groups, dict):
        return auth.json_error('参数错误', 400)
    cleaned = {}
    for name, perms in groups.items():
        name = str(name).strip()
        if not name:
            continue
        if isinstance(perms, str):
            perms = [perms]
        cleaned[name] = [str(p).strip() for p in (perms or []) if str(p).strip()]
    if 'admin' in cleaned and '*' not in cleaned['admin']:
        cleaned['admin'] = ['*']
    cfg = config.load_config()
    cfg['permission_groups'] = cleaned
    config.save_config(cfg)
    config.load_settings()
    return jsonify({'ok': True})


@bp.route('/admin/api/groups/default', methods=['POST'])
def api_groups_default():
    actor, error = _require('admin.groups')
    if error:
        return error
    payload = auth.request_payload()
    group = (payload.get('group') or '').strip()
    if group and group not in permissions.all_groups():
        return auth.json_error('权限组不存在', 404)
    cfg = config.load_config()
    cfg['default_group'] = group or 'user'
    config.save_config(cfg)
    config.load_settings()
    return jsonify({'ok': True})


# ---------------- 插件 ----------------

@bp.route('/admin/api/plugins', methods=['GET'])
def api_plugins():
    actor, error = _require('admin.plugins')
    if error:
        return error
    return jsonify({'ok': True, 'plugins': plugin_manager.list_plugins()})


@bp.route('/admin/api/plugins/<name>/toggle', methods=['POST'])
def api_plugin_toggle(name):
    actor, error = _require('admin.plugins')
    if error:
        return error
    payload = auth.request_payload()
    enabled = bool(payload.get('enabled'))
    plugin_manager.set_enabled(name, enabled)
    logger.info('管理员 %s 将插件 %s 设为 %s', actor, name, '启用' if enabled else '禁用')
    return jsonify({'ok': True, 'enabled': enabled})


@bp.route('/admin/api/plugins/reload', methods=['POST'])
def api_plugins_reload():
    actor, error = _require('admin.plugins')
    if error:
        return error
    plugin_manager.reload_plugins(state.app)
    return jsonify({'ok': True})


@bp.route('/admin/api/plugins/<name>/config', methods=['GET', 'POST'])
def api_plugin_config(name):
    actor, error = _require('admin.plugins')
    if error:
        return error
    ctx = plugin_manager._by_name.get(name)
    if ctx is None:
        return auth.json_error('插件未加载', 404)
    if request.method == 'GET':
        return jsonify({'ok': True, 'config': ctx.get_config()})
    payload = auth.request_payload()
    config_data = payload.get('config')
    if not isinstance(config_data, dict):
        return auth.json_error('配置必须是 JSON 对象', 400)
    with open(ctx.config_path(), 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)
    return jsonify({'ok': True, 'config': config_data})


# ---------------- 流量 ----------------

@bp.route('/admin/api/traffic', methods=['GET'])
def api_traffic():
    actor, error = _require('admin.traffic')
    if error:
        return error
    return jsonify({'ok': True, 'traffic': traffic.summary()})


# ---------------- 数据库 ----------------

@bp.route('/admin/api/database/stats', methods=['GET'])
def api_database_stats():
    actor, error = _require('admin.database')
    if error:
        return error
    try:
        message_count = state.database.count_documents({})
    except Exception as exc:
        return auth.json_error('数据库不可用: %s' % exc, 500)
    try:
        collections = [c['name'] for c in state.db.list_collections()]
    except Exception:
        try:
            collections = state.db.list_collection_names()
        except Exception:
            collections = [state.database.name or 'chatter']
    try:
        db_stats = state.db.command('dbstats')
    except Exception:
        db_stats = {}
    return jsonify({
        'ok': True,
        'stats': {
            'message_count': message_count,
            'collections': collections,
            'db_stats': db_stats,
        },
    })


@bp.route('/admin/api/database/messages', methods=['GET'])
def api_database_messages():
    actor, error = _require('admin.database')
    if error:
        return error
    username = request.args.get('user') or ''
    limit = request.args.get('limit', '20')
    try:
        limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        limit = 20
    query = {'user': username} if username else {}
    docs = list(state.database.find(query).sort('_id', -1).limit(limit))
    docs.reverse()
    return jsonify({'ok': True, 'messages': [messages.serialize_message(d, i) for i, d in enumerate(docs)]})


@bp.route('/admin/api/database/delete-user', methods=['POST'])
def api_database_delete_user():
    actor, error = _require('admin.database')
    if error:
        return error
    payload = auth.request_payload()
    username = (payload.get('username') or '').strip()
    if not username:
        return auth.json_error('参数不完整', 400)
    result = state.database.delete_many({'user': username})
    messages.add_system_message('管理员清除了用户 %s 的全部消息' % username)
    return jsonify({'ok': True, 'deleted': result.deleted_count})


@bp.route('/admin/api/database/clear', methods=['POST'])
def api_database_clear():
    actor, error = _require('admin.database')
    if error:
        return error
    state.database.delete_many({})
    messages.add_system_message('管理员清除了聊天记录')
    return jsonify({'ok': True})


# ---------------- 快捷工具 ----------------

_TOOL_LINK_LIMIT = 50


def _clean_tool_links(value):
    if not isinstance(value, list):
        return None
    cleaned = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or '').strip()
        url = str(item.get('url') or '').strip()
        if not title or not url:
            continue
        if len(cleaned) >= _TOOL_LINK_LIMIT:
            break
        cleaned.append({'title': title[:100], 'url': url[:500]})
    return cleaned


@bp.route('/admin/api/tool-links', methods=['GET'])
def api_tool_links():
    actor, error = _require('admin.tools')
    if error:
        return error
    return jsonify({'ok': True, 'links': state.settings.get('custom_tool_links') or []})


@bp.route('/admin/api/tool-links', methods=['POST'])
def api_tool_links_save():
    actor, error = _require('admin.tools')
    if error:
        return error
    payload = auth.request_payload()
    cleaned = _clean_tool_links(payload.get('links'))
    if cleaned is None:
        return auth.json_error('links 必须是数组', 400)
    cfg = config.load_config()
    cfg['custom_tool_links'] = cleaned
    config.save_config(cfg)
    config.load_settings()
    logger.info('管理员 %s 更新了快捷工具链接（%d 条）', actor, len(cleaned))
    return jsonify({'ok': True, 'links': cleaned})


# ---------------- 设置 ----------------

_SETTINGS_KEYS = ('site_title', 'server_ip', 'port', 'poll_interval',
                  'mute_default_seconds', 'base_path', 'admins')


@bp.route('/admin/api/settings', methods=['GET'])
def api_settings():
    actor, error = _require('admin.settings')
    if error:
        return error
    visible = {key: state.settings.get(key) for key in _SETTINGS_KEYS}
    visible['base_path'] = state.base_path
    return jsonify({'ok': True, 'settings': visible})


@bp.route('/admin/api/settings', methods=['POST'])
def api_settings_save():
    actor, error = _require('admin.settings')
    if error:
        return error
    payload = auth.request_payload()
    changes = payload.get('settings')
    if not isinstance(changes, dict):
        return auth.json_error('参数错误', 400)
    cfg = config.load_config()
    for key in _SETTINGS_KEYS:
        if key not in changes:
            continue
        value = changes[key]
        if key == 'admins':
            if not isinstance(value, list):
                continue
            value = [str(v).strip() for v in value if str(v).strip()]
            if actor not in value and not any(permissions.is_admin(u) for u in value):
                continue  # 不允许把自己移除出管理员列表
        elif key == 'base_path':
            value = str(value or '').strip().rstrip('/')
        elif key in ('port', 'poll_interval', 'mute_default_seconds'):
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
        else:
            value = str(value or '')
        cfg[key] = value
    config.save_config(cfg)
    config.load_settings()
    return jsonify({'ok': True, 'settings': {
        key: state.settings.get(key) for key in _SETTINGS_KEYS}})
