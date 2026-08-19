"""消息读写、系统消息与禁言。"""
import time
import uuid
from datetime import datetime

from . import auth, permissions, plugin_manager, state, users

MUTE_MIN_SECONDS = 1
MUTE_MAX_SECONDS = 86400

DEFAULT_PAGE_LIMIT = 200
MAX_PAGE_LIMIT = 500


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


def message_count():
    return state.database.count_documents({'user': {'$exists': True, '$ne': ''}})


def _to_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def _anchor_cursor(message_id):
    """将公开消息 id 解析为分页游标 (created_at, _id)；找不到返回 None。

    created_at 可能为 None：表示该消息的 created_at 缺失/为空，排序时位于 null 组
    （所有数值之前），由 _position 单独处理。
    """
    message_id = str(message_id or '')
    document = state.database.find_one({'id': message_id})
    if not document and message_id.startswith('legacy-'):
        # 遗留消息的公开 id 由 _id 派生（legacy-<ObjectId>），并不存在对应的 'id' 字段
        try:
            from bson import ObjectId
            document = state.database.find_one({'_id': ObjectId(message_id[len('legacy-'):])})
        except Exception:
            document = None
    if not document or document.get('_id') is None:
        return None
    created_at = document.get('created_at', document.get('timestamp'))
    if created_at is None:
        return None, document['_id']
    return _to_float(created_at), document['_id']


def _tie_docs(created_at, user_query):
    """与 created_at 相同的全部文档（用于补齐同刻消息，_id 比较在 Python 侧完成）。"""
    docs = list(state.database.find(dict(user_query, created_at=created_at)))
    return [doc for doc in docs if doc.get('_id') is not None]


def _position(user_query, created_at, anchor_id):
    """锚点在 (created_at, _id) 复合排序中的绝对位置（其前有多少条消息）。

    排序规则（BSON 顺序）：created_at 缺失/为空的文档（null 组）排在最前，
    null 组内部按 _id 升序；随后才是数值升序。$lt/$gt 不会命中 null 组，
    因此需要单独统计。
    """
    if created_at is None:
        # 锚点本身属于 null 组：位置 = 同组中 _id 更小的文档数
        return sum(1 for doc in state.database.find(dict(user_query, created_at=None))
                   if doc.get('_id') is not None and doc['_id'] < anchor_id)
    null_before = state.database.count_documents(dict(user_query, created_at=None))
    before_ts = state.database.count_documents(
        dict(user_query, created_at={'$lt': created_at}))
    ties_before = sum(1 for doc in _tie_docs(created_at, user_query)
                      if doc['_id'] < anchor_id)
    return null_before + before_ts + ties_before


def get_message_page(limit=None, before_id=None, after_id=None):
    """按游标分页返回升序消息列表。

    - 无任何游标（默认）：返回最近 limit 条；
    - after_id：返回该消息之后（更新）的 limit 条，用于增量轮询；
    - before_id：返回该消息之前（更早）的 limit 条，用于加载更早消息。
    返回 (messages, has_more)，has_more 表示是否还存在比返回页首更早的消息。
    """
    if limit is None:
        limit = DEFAULT_PAGE_LIMIT
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = DEFAULT_PAGE_LIMIT
    limit = max(1, min(limit, MAX_PAGE_LIMIT))

    user_query = {'user': {'$exists': True, '$ne': ''}}
    total = state.database.count_documents(user_query)
    anchor = (_anchor_cursor(after_id) if after_id
              else _anchor_cursor(before_id) if before_id else None)
    if anchor is None:
        skip = max(0, total - limit)
        take = min(limit, total)
        has_more = total > limit
    elif after_id:
        skip = _position(user_query, anchor[0], anchor[1]) + 1
        take = min(limit, max(0, total - skip))
        has_more = skip > 1
    else:  # before_id
        pos = _position(user_query, anchor[0], anchor[1])
        skip = max(0, pos - limit)
        take = min(limit, pos)
        has_more = skip > 0

    if take <= 0:
        # pymongo/mongomock 中 limit(0) 表示“不限制”，会返回全部文档
        return [], has_more

    docs = list(state.database.find(user_query)
                .sort([('created_at', 1), ('_id', 1)])
                .skip(skip).limit(take))

    messages = []
    for index, doc in enumerate(docs):
        if not doc.get('user'):
            continue
        messages.append(serialize_message(doc, skip + index))
    return messages, has_more


def get_messages():
    """返回全部消息（兼容旧调用方；新代码请使用 get_message_page）。"""
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
