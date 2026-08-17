"""消息读写、系统消息与禁言。"""
import time
import uuid
from datetime import datetime

from . import auth, permissions, plugin_manager, state, users

MUTE_MIN_SECONDS = 1
MUTE_MAX_SECONDS = 86400


class MuteError(Exception):
    def __init__(self, muted_until):
        self.muted_until = muted_until
        super().__init__('您已被禁言')


def get_current_time():
    return time.strftime('%Y:%m:%d:%H:%M', time.localtime())


# ---------------- 禁言 ----------------

def get_mute_record(username):
    record = state.mutes.find_one({'username': username})
    if not record:
        return None
    muted_until = float(record.get('muted_until', 0) or 0)
    if muted_until <= time.time():
        try:
            state.mutes.delete_one({'_id': record['_id']})
        except (KeyError, TypeError):
            state.mutes.delete_one({'username': username})
        return None
    return record


def mute_state(username):
    record = get_mute_record(username)
    until = float(record.get('muted_until', 0)) if record else 0
    return {'muted': until > time.time(), 'muted_until': until}


def ensure_not_muted(username):
    record = get_mute_record(username)
    if record:
        raise MuteError(float(record.get('muted_until', 0)))


# ---------------- 消息序列化 ----------------

def infer_message_type(content, stored_type=None, user=None):
    content = '' if content is None else str(content)
    # 内容标记用于修复早期以 text 类型存储的记录
    if user == 'system' or content == 'clear':
        return 'system'
    if content.startswith('::img::'):
        return 'image'
    if content.startswith('::wav::'):
        return 'audio'
    if content.startswith('::emoji::'):
        return 'emoji'
    if content.startswith('::file::'):
        return 'file'
    if stored_type:
        return str(stored_type)
    return 'text'


def legacy_message_id(doc, index=0):
    if doc.get('id'):
        return str(doc['id'])
    if doc.get('_id') is not None:
        return 'legacy-' + str(doc['_id'])
    return 'legacy-' + str(index)


def parse_legacy_timestamp(value):
    if not value:
        return 0
    try:
        return datetime.strptime(str(value), '%Y:%m:%d:%H:%M').timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0


def serialize_message(doc, index=0):
    content = doc.get('content', doc.get('chat', ''))
    if content is None:
        content = ''
    content = str(content)
    user = str(doc.get('user', ''))
    message_time = str(doc.get('time', ''))
    created_at = doc.get('created_at', doc.get('timestamp', parse_legacy_timestamp(message_time)))
    try:
        created_at = float(created_at or 0)
    except (TypeError, ValueError):
        created_at = 0
    return {
        'id': legacy_message_id(doc, index),
        'user': user,
        'color': doc.get('color') or users.get_user_color(user),
        'time': message_time,
        'timestamp': created_at,
        'content': content,
        'type': infer_message_type(content, doc.get('type'), user),
        'recalled': bool(doc.get('recalled', doc.get('revoked', False))),
        'reply_to': str(doc['reply_to']) if doc.get('reply_to') else None,
        'file_hash': str(doc['file_hash']) if doc.get('file_hash') else None,
        'file_size': doc.get('file_size'),
    }


# ---------------- 消息查询 ----------------

def iter_message_docs():
    return state.database.find().sort('_id', 1)


def get_messages():
    messages = []
    for index, doc in enumerate(iter_message_docs()):
        if not doc.get('user'):
            continue
        messages.append(serialize_message(doc, index))
    return messages


def get_data():
    """Legacy 四列表访问器，为旧集成保留。"""
    messages = get_messages()
    return [
        [message['content'] for message in messages],
        [message['user'] for message in messages],
        [message['color'] for message in messages],
        [message['time'] for message in messages],
    ]


def find_message(message_id):
    message_id = str(message_id or '')
    doc = state.database.find_one({'id': message_id})
    if doc:
        return doc
    for index, candidate in enumerate(iter_message_docs()):
        if legacy_message_id(candidate, index) == message_id:
            return candidate
    return None


# ---------------- 写入 ----------------

def add_system_message(content):
    now = time.time()
    document = {
        'id': uuid.uuid4().hex,
        'chat': content,
        'content': content,
        'user': 'system',
        'color': '#888888',
        'time': get_current_time(),
        'created_at': now,
        'type': 'system',
        'recalled': False,
        'reply_to': None,
    }
    state.database.insert_one(document)
    return serialize_message(document)


def add_chat(username, value, d_time=None, reply_to=None, message_type=None, check_mute=True, extra=None):
    if check_mute:
        ensure_not_muted(username)
    value = '' if value is None else str(value)
    d_time = d_time or get_current_time()
    state.logger.info('用户：%s 上传了信息：%s', username, value)

    if value.startswith('command: '):
        from . import commands  # 延迟导入，避免循环依赖
        info = commands.resolve(username, value, d_time)
        if info['status'] == 'executed' and info['message'] is not None:
            result = info['message']
            result['command'] = {'name': info['name'], 'status': 'executed'}
            return result
        command_info = {'name': info['name'], 'status': info['status']}
    else:
        command_info = None

    if reply_to and not find_message(reply_to):
        reply_to = None

    document = {
        'id': uuid.uuid4().hex,
        'chat': value,
        'content': value,
        'user': username,
        'color': users.get_user_color(username),
        'time': d_time,
        'created_at': time.time(),
        'type': message_type or infer_message_type(value),
        'recalled': False,
        'reply_to': str(reply_to) if reply_to else None,
    }
    if extra:
        document.update(extra)
    if not plugin_manager.emit('message_send', document=document, username=username):
        return None  # 被插件拦截
    state.database.insert_one(document)
    message = serialize_message(document)
    if command_info:
        message['command'] = command_info
    return message


# ---------------- 撤回 ----------------

def message_for_recall(message_id, username):
    document = find_message(message_id)
    if not document:
        return None, '消息不存在'
    message = serialize_message(document)
    if message['type'] == 'system':
        return None, '系统消息不可撤回'
    if message['recalled']:
        return None, '消息已经撤回'
    if not permissions.has_permission(username, 'message.recall.any') and message['user'] != username:
        return None, '只能撤回自己的消息'
    if not permissions.has_permission(username, 'message.recall.any'):
        created_at = message.get('timestamp') or 0
        if not created_at or time.time() - created_at > 120:
            return None, '只能撤回两分钟内的消息'
    return document, None
