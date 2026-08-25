"""管理面板 JSON API（全部接口需登录且具备对应 admin.* 权限）。"""
import json
import os
import random
import string

from flask import jsonify, request

from .. import attachments, auth, config, messages, permissions, plugin_manager, state, traffic, users
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


def _initial_admin():
    """受保护的初始管理员（初始化时创建的第一个管理员，不可被删除或降级）。"""
    return str(config.load_config().get('initial_admin') or '')


# ---------------- 用户 ----------------

@bp.route('/admin/api/users', methods=['GET'])
def api_users():
    actor, error = _require('admin.users')
    if error:
        return error
    user_groups = state.settings.get('user_groups') or {}
    return jsonify({
        'ok': True,
        'actor': actor,
        'initial_admin': _initial_admin(),
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
    cfg = config.load_config()
    if cfg.get('initial_admin') == old_name:
        cfg['initial_admin'] = new_name
        config.save_config(cfg)
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
    target = group or state.settings.get('default_group', 'user')
    if username == _initial_admin() and not permissions.group_grants(target, 'admin.panel'):
        return auth.json_error('初始管理员不可被移出管理员组', 400)
    if username == actor and permissions.is_admin(actor) \
            and not permissions.group_grants(target, 'admin.panel'):
        return auth.json_error('不能移除自己的管理员权限', 400)
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
    return jsonify({'ok': True, 'enabled': enabled, 'loaded': plugin_manager.is_loaded(name)})


@bp.route('/admin/api/plugins/<name>/reload', methods=['POST'])
def api_plugin_reload(name):
    actor, error = _require('admin.plugins')
    if error:
        return error
    ok, message = plugin_manager.reload_plugin(name)
    if not ok:
        return auth.json_error(message or '重载失败', 400)
    logger.info('管理员 %s 热重载了插件 %s', actor, name)
    return jsonify({'ok': True, 'loaded': plugin_manager.is_loaded(name)})


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


# ---------------- 文件上传（static/uploads 管理） ----------------

_UPLOAD_BATCH_LIMIT = 20
_UPLOAD_MAX_SIZE = 200 * 1024 * 1024  # 单文件 200MB 上限，防止超大文件占满磁盘


@bp.route('/admin/api/uploads', methods=['GET'])
def api_uploads_list():
    actor, error = _require('admin.uploads')
    if error:
        return error
    root = os.path.abspath(attachments.upload_dir())
    items = []
    if os.path.isdir(root):
        for entry in os.scandir(root):
            try:
                if not entry.is_file():
                    continue
                stat = entry.stat()
            except OSError:
                continue
            items.append({'name': entry.name, 'size': stat.st_size, 'mtime': int(stat.st_mtime)})
    items.sort(key=lambda item: item['mtime'], reverse=True)
    total_size = sum(item['size'] for item in items)
    return jsonify({
        'ok': True,
        'files': items[:500],
        'total': len(items),
        'total_size': total_size,
    })


@bp.route('/admin/api/uploads/batch', methods=['POST'])
def api_uploads_batch():
    actor, error = _require('admin.uploads')
    if error:
        return error
    files = request.files.getlist('files')
    if not files:
        return auth.json_error('没有选择文件', 400)
    if len(files) > _UPLOAD_BATCH_LIMIT:
        return auth.json_error('单次最多上传 %d 个文件' % _UPLOAD_BATCH_LIMIT, 400)
    os.makedirs(attachments.upload_dir(), exist_ok=True)
    saved, failed = [], []
    for uploaded in files:
        original_name = (uploaded.filename or '').strip() if uploaded is not None else ''
        try:
            if not original_name:
                raise ValueError('空文件')
            upload_path, safe_name = attachments.safe_upload_path(original_name)
            if not upload_path:
                raise ValueError('文件名无效')
            name, extension = os.path.splitext(safe_name)
            final_name = safe_name
            counter = 1
            while os.path.exists(os.path.join(upload_path, final_name)):
                final_name = '%s (%d)%s' % (name, counter, extension)
                counter += 1
            file_path = os.path.join(upload_path, final_name)
            uploaded.save(file_path)
            size = os.path.getsize(file_path)
            if size > _UPLOAD_MAX_SIZE:
                os.remove(file_path)
                raise ValueError('文件超过大小限制（%s）' % format_bytes(_UPLOAD_MAX_SIZE))
            saved.append({'name': final_name, 'size': size})
        except Exception as exc:
            failed.append({'name': original_name, 'error': str(exc)})
    if saved:
        logger.info('管理员 %s 批量上传了 %d 个文件（失败 %d 个）', actor, len(saved), len(failed))
    return jsonify({'ok': True, 'saved': saved, 'failed': failed})


def format_bytes(n):
    value = float(n)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1024 or unit == 'TB':
            return ('%d %s' % (value, unit)) if unit == 'B' else ('%.1f %s' % (value, unit))
        value /= 1024


@bp.route('/admin/api/uploads/delete', methods=['POST'])
def api_uploads_delete():
    actor, error = _require('admin.uploads')
    if error:
        return error
    payload = auth.request_payload()
    name = str(payload.get('name') or '').strip()
    # 拒绝任何带路径成分的名称（含 / \ .. 等），仅允许 uploads 目录顶层的裸文件名
    if not name or os.path.basename(name) != name or name in {'.', '..'} \
            or '/' in name or '\\' in name:
        return auth.json_error('非法路径', 400)
    root = os.path.abspath(attachments.upload_dir())
    target = os.path.abspath(os.path.join(root, name))
    if os.path.dirname(target) != root:
        return auth.json_error('非法路径', 400)
    if not os.path.isfile(target):
        return auth.json_error('文件不存在', 404)
    try:
        os.remove(target)
    except OSError as exc:
        return auth.json_error('删除失败: %s' % exc, 500)
    logger.info('管理员 %s 删除了上传文件 %s', actor, name)
    return jsonify({'ok': True})


# ---------------- 快捷工具 ----------------

_TOOL_LINK_LIMIT = 50


def _clean_tool_links(value):
    """校验并清洗快捷工具条目：{title, url, icon?, enabled?, plugin?, key?}"""
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
        entry = {'title': title[:100], 'url': url[:500]}
        icon = str(item.get('icon') or '').strip()[:32]
        if icon:
            entry['icon'] = icon
        entry['enabled'] = bool(item.get('enabled', True))
        # 插件条目：保留来源标记与稳定匹配键（修改内容不影响匹配）
        if item.get('plugin'):
            plugin = str(item.get('plugin') or '').strip()[:64]
            key = str(item.get('key') or '').strip()[:200]
            if plugin and key:
                entry['plugin'] = plugin
                entry['key'] = key
        cleaned.append(entry)
    return cleaned


@bp.route('/admin/api/tool-links', methods=['GET'])
def api_tool_links():
    actor, error = _require('admin.tools')
    if error:
        return error
    return jsonify({'ok': True, 'links': plugin_manager.tool_links()})


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
    # 删除记录与已存列表合并：前端每次只上报“本次会话”删除的 key，
    # 若直接覆盖会丢失之前删除的插件链接（下次保存即复活）。
    present_keys = {entry['key'] for entry in cleaned if entry.get('key')}
    existing_removed = set(cfg.get('removed_plugin_links') or [])
    submitted_removed = set()
    removed_list = payload.get('removed')
    if isinstance(removed_list, list):
        submitted_removed = {str(k)[:200] for k in removed_list if str(k).strip()}
    cfg['removed_plugin_links'] = sorted(
        (existing_removed | submitted_removed) - present_keys)
    config.save_config(cfg)
    config.load_settings()
    logger.info('管理员 %s 更新了快捷工具链接（%d 条）', actor, len(cleaned))
    return jsonify({'ok': True, 'links': plugin_manager.tool_links()})


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
            initial_admin = str(cfg.get('initial_admin') or '')
            if actor in state.admins and actor not in value:
                continue  # 管理员不能移除自己的权限
            if initial_admin and initial_admin not in value:
                continue  # 初始管理员不可被移除
            if not any(permissions.is_admin(u) for u in value):
                continue  # 至少保留一名管理员
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
