"""聊天室 JSON API 路由。"""
import os
import time

from flask import jsonify, request, send_from_directory

from .. import attachments, auth, messages, permissions, plugin_manager, state
from ..state import logger
from . import make_blueprint

bp = make_blueprint('chat')


@bp.route('/chattss', methods=['POST'])
def chats():
    username = auth.authenticate_request()
    if not username:
        return auth.json_error('认证数据错误', 401)
    auth.touch_presence(username)
    state_value = messages.mute_state(username)
    payload = auth.request_payload()
    raw_limit = payload.get('limit')
    if raw_limit is None:
        raw_limit = request.args.get('limit')
    message_list, has_more = messages.get_message_page(
        limit=raw_limit,
        before_id=payload.get('before') or request.args.get('before'),
        after_id=payload.get('after') or request.args.get('after'),
    )
    payload = {
        'ok': True,
        'messages': message_list,
        'has_more': has_more,
        'total': messages.message_count(),
        'current_user': username,
        'is_admin': permissions.is_admin(username),
        'permissions': permissions.expanded_permissions(username),
        'muted': state_value['muted'],
        'muted_until': state_value['muted_until'],
        'server_time': time.time(),
    }
    plugin_manager.emit('chat_data', payload=payload, username=username)
    return jsonify(payload)


@bp.route('/chatts_file', methods=['POST'])
def chat_file():
    username = auth.authenticate_request()
    if not username:
        return auth.json_error('认证数据错误', 401)
    try:
        messages.ensure_not_muted(username)
    except messages.MuteError as exc:
        return auth.json_error('您已被禁言', 403, muted_until=exc.muted_until)

    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        return auth.json_error('没有选择文件', 400)
    upload_dir, original_name = attachments.safe_upload_path(uploaded.filename)
    if not upload_dir:
        return auth.json_error('文件名无效', 400)

    name, extension = os.path.splitext(original_name)
    final_name = original_name
    counter = 1
    while os.path.exists(os.path.join(upload_dir, final_name)):
        final_name = '%s (%s)%s' % (name, counter, extension)
        counter += 1
    file_path = os.path.join(upload_dir, final_name)
    uploaded.save(file_path)

    extension_name = extension.lower().lstrip('.')
    if extension_name in attachments.IMAGE_EXTENSIONS:
        message_type, prefix = 'image', '::img::'
    elif extension_name in attachments.AUDIO_EXTENSIONS:
        message_type, prefix = 'audio', '::wav::'
    else:
        message_type, prefix = 'file', '::file::'
    payload = auth.request_payload()
    try:
        message = messages.add_chat(
            username,
            prefix + final_name,
            messages.get_current_time(),
            reply_to=payload.get('reply_to'),
            message_type=message_type,
            check_mute=False,
            extra={'file_hash': attachments.hash_file(file_path),
                   'file_size': os.path.getsize(file_path)},
        )
    except Exception:
        try:
            os.remove(file_path)
        except FileNotFoundError:
            pass
        raise
    if message is None:
        try:
            os.remove(file_path)
        except FileNotFoundError:
            pass
        return auth.json_error('消息被插件拦截', 400)
    return jsonify({'ok': True, 'update': auth.request_token(), 'message': message})


@bp.route('/get_online', methods=['GET', 'POST'])
def get_online():
    username = auth.authenticate_request()
    if not username:
        return auth.json_error('认证数据错误', 401)
    auth.touch_presence(username)
    online = [entry['username'] for entry in state.loginings if entry['username'] != username]
    return ','.join(online)


@bp.route('/username-list', methods=['GET'])
def online_list():
    return '||'.join(state.usernames)


@bp.route('/chatts-new', methods=['POST', 'GET'])
def chat_new():
    username = auth.authenticate_request()
    if not username:
        return auth.json_error('认证数据错误', 401)
    payload = auth.request_payload()
    value = payload.get('upload_value', '')
    if value is None:
        value = ''
    value = str(value)
    if not value:
        return auth.json_error('消息不能为空', 400)
    message_type = 'emoji' if value.startswith('::emoji::') else 'text'
    try:
        message = messages.add_chat(username, value, messages.get_current_time(),
                                    reply_to=payload.get('reply_to'),
                                    message_type=message_type)
    except messages.MuteError as exc:
        return auth.json_error('您已被禁言', 403, muted_until=exc.muted_until)
    if message is None:
        return auth.json_error('消息被插件拦截', 400)
    return jsonify({'ok': True, 'update': auth.request_token(), 'message': message})


@bp.route('/api/messages/<message_id>/recall', methods=['POST'])
@bp.route('/api/recall', methods=['POST'])
@bp.route('/chatts-recall', methods=['POST'])
@bp.route('/recall', methods=['POST'])
def recall_message(message_id=None):
    username = auth.authenticate_request()
    if not username:
        return auth.json_error('认证数据错误', 401)
    if message_id is None:
        payload = auth.request_payload()
        message_id = payload.get('id') or payload.get('message_id')
    document, error_message = messages.message_for_recall(message_id, username)
    if error_message:
        return auth.json_error(error_message, 403 if '只能' in error_message else 404)
    update = {'$set': {'recalled': True, 'recalled_at': time.time()}}
    if document.get('_id') is not None:
        state.database.update_one({'_id': document['_id']}, update)
    elif document.get('id'):
        state.database.update_one({'id': document['id']}, update)
    attachments.delete_attachment(document)
    plugin_manager.emit('message_recall', message_id=str(message_id), username=username)
    return jsonify({'ok': True, 'id': str(message_id)})


def _mute_target_from_request():
    payload = auth.request_payload()
    target = (payload.get('target') or payload.get('username') or '').strip()
    duration_value = payload.get('duration', 60)
    try:
        duration = int(duration_value)
    except (TypeError, ValueError):
        duration = 60
    return target, duration


@bp.route('/api/mute', methods=['POST'])
@bp.route('/chat/mute', methods=['POST'])
@bp.route('/mute', methods=['POST'])
def mute_user():
    actor = auth.authenticate_request()
    if not actor:
        return auth.json_error('认证数据错误', 401)
    if not permissions.has_permission(actor, 'moderation.mute'):
        return auth.json_error('没有禁言权限', 403)
    target, duration = _mute_target_from_request()
    if target not in state.usernames:
        return auth.json_error('用户不存在', 404)
    if permissions.is_admin(target):
        return auth.json_error('管理员不能被禁言', 403)
    if duration < messages.MUTE_MIN_SECONDS or duration > messages.MUTE_MAX_SECONDS:
        return auth.json_error('禁言时长必须为 1-86400 秒', 400)
    existing = messages.get_mute_record(target)
    if existing:
        return auth.json_error('该用户已经处于禁言状态', 409, muted_until=float(existing['muted_until']))
    muted_until = time.time() + duration
    state.mutes.update_one(
        {'username': target},
        {'$set': {'username': target, 'muted_until': muted_until,
                  'muted_by': actor, 'created_at': time.time()}},
        upsert=True,
    )
    messages.add_system_message('%s 将 %s 禁言 %s 秒' % (actor, target, duration))
    return jsonify({'ok': True, 'username': target, 'muted_until': muted_until})


@bp.route('/api/unmute', methods=['POST'])
@bp.route('/chat/unmute', methods=['POST'])
@bp.route('/unmute', methods=['POST'])
def unmute_user():
    actor = auth.authenticate_request()
    if not actor:
        return auth.json_error('认证数据错误', 401)
    if not permissions.has_permission(actor, 'moderation.unmute'):
        return auth.json_error('没有解除禁言权限', 403)
    target, _ = _mute_target_from_request()
    if target not in state.usernames:
        return auth.json_error('用户不存在', 404)
    record = messages.get_mute_record(target)
    if not record:
        return auth.json_error('该用户当前未被禁言', 404)
    state.mutes.delete_one({'_id': record['_id']})
    messages.add_system_message('%s 解除了 %s 的禁言' % (actor, target))
    return jsonify({'ok': True, 'username': target, 'muted_until': 0})


@bp.route('/api/cpp-preview', methods=['GET', 'POST'])
@bp.route('/cpp-preview', methods=['GET', 'POST'])
@bp.route('/chat/cpp-preview', methods=['GET', 'POST'])
def cpp_preview():
    username = auth.authenticate_request()
    if not username:
        return auth.json_error('认证数据错误', 401)
    payload = auth.request_payload()
    filename = payload.get('filename') or request.args.get('filename')
    path = attachments.cpp_path(filename)
    if not path or not os.path.isfile(path):
        return auth.json_error('文件不存在或不是 .cpp 文件', 404)
    if os.path.getsize(path) > attachments.CPP_PREVIEW_LIMIT:
        return auth.json_error('文件超过 1MB', 413)
    try:
        with open(path, 'rb') as stream:
            content, encoding = attachments.decode_cpp(stream.read(), label=os.path.basename(path))
    except Exception as exc:
        logger.warning('C++ 文件预览解析失败：%s（%s）', os.path.basename(path), exc)
        return auth.json_error('文件解析失败', 500)
    logger.info('C++ 文件预览：%s（编码 %s）', os.path.basename(path), encoding)
    return jsonify({'ok': True, 'filename': os.path.basename(path),
                    'content': content, 'encoding': encoding})


@bp.route('/chat/emoji/list/<username>', methods=['GET'])
def emoji_list(username):
    actor = auth.authenticate_request()
    if actor != username and not permissions.is_admin(actor or ''):
        return auth.json_error('没有权限', 403)
    directory = attachments.emoji_directory(username)
    if not directory or not os.path.isdir(directory):
        return jsonify([])
    return jsonify(sorted(name for name in os.listdir(directory)
                          if os.path.isfile(os.path.join(directory, name))))


@bp.route('/chat/emoji/static/<username>/<filename>', methods=['GET'])
def emoji_static(username, filename):
    directory = attachments.emoji_directory(username)
    safe = attachments.safe_filename(filename)
    if not directory or not safe or safe != filename:
        return auth.json_error('文件不存在', 404)
    return send_from_directory(directory, safe)


@bp.route('/chat/emoji/upload', methods=['POST'])
def emoji_upload():
    actor = auth.authenticate_request()
    if not actor:
        return auth.json_error('认证数据错误', 401)
    try:
        messages.ensure_not_muted(actor)
    except messages.MuteError as exc:
        return auth.json_error('您已被禁言', 403, muted_until=exc.muted_until)
    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        return auth.json_error('没有选择文件', 400)
    directory = attachments.emoji_directory(actor)
    if not directory:
        return auth.json_error('用户名无效', 400)
    os.makedirs(directory, exist_ok=True)
    filename = attachments.safe_filename(uploaded.filename)
    if not filename:
        return auth.json_error('文件名无效', 400)
    uploaded.save(os.path.join(directory, filename))
    return jsonify({'success': True, 'filename': filename})


@bp.route('/chat/emoji/delete', methods=['POST'])
def emoji_delete():
    actor = auth.authenticate_request()
    if not actor:
        return auth.json_error('认证数据错误', 401)
    payload = auth.request_payload()
    target = payload.get('username') or actor
    if target != actor and not permissions.is_admin(actor):
        return auth.json_error('没有权限', 403)
    directory = attachments.emoji_directory(target)
    filename = attachments.safe_filename(payload.get('filename', ''))
    if not directory or not filename:
        return auth.json_error('文件名无效', 400)
    path = os.path.join(directory, filename)
    if not os.path.isfile(path):
        return auth.json_error('文件不存在', 404)
    os.remove(path)
    return jsonify({'success': True})
