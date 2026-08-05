"""聊天室命令注册表。

- 命令通过 register_command 注册，附带所需权限点（权限检查见 permissions）。
- dispatch 无权限/未知命令时返回 None，由调用方作为普通消息发送。
"""
import time
import uuid

from . import messages, permissions, plugin_manager, state, users

COMMANDS = {}


def register_command(name, permission='admin', description=''):
    """装饰器：注册聊天命令。permission 为执行该命令所需的权限点。"""
    def decorator(fn):
        COMMANDS[name] = {'fn': fn, 'permission': permission, 'description': description}
        return fn
    return decorator


def dispatch(username, command_str, d_time):
    parts = command_str[9:].split()
    if not parts:
        return None
    command = parts[0]
    entry = COMMANDS.get(command)
    if entry is None:
        return None
    if not permissions.can_execute_command(username, entry['permission']):
        return None
    return entry['fn'](username, parts, d_time, command_str)


def post_raw_message(username, command_str, d_time):
    """将无法识别/无权限的命令作为普通消息发送。"""
    document = {
        'id': uuid.uuid4().hex,
        'chat': command_str,
        'content': command_str,
        'user': username,
        'color': users.get_user_color(username),
        'time': d_time,
        'created_at': time.time(),
        'type': 'text',
        'recalled': False,
        'reply_to': None,
    }
    if not plugin_manager.emit('message_send', document=document, username=username):
        return None
    state.database.insert_one(document)
    return messages.serialize_message(document)


@register_command('clear', permission='chat.clear', description='清空所有聊天记录')
def cmd_clear(username, parts, d_time, command_str):
    state.database.delete_many({})
    return messages.add_system_message('管理员清除了聊天记录')


@register_command('change_color', permission='chat.change_color',
                  description='修改用户颜色：change_color 用户名 颜色')
def cmd_change_color(username, parts, d_time, command_str):
    if len(parts) < 3:
        return None
    target_user, new_color = parts[1], parts[2]
    if target_user in state.usernames:
        users.set_user_color(target_user, new_color)
        state.logger.info('管理员将用户 %s 的颜色改为 %s', target_user, new_color)
        return messages.add_system_message('管理员已更新 %s 的头像颜色' % target_user)
    return None


@register_command('delete', permission='chat.delete',
                  description='删除最后 N 条消息：delete N')
def cmd_delete(username, parts, d_time, command_str):
    if len(parts) < 2:
        return None
    try:
        count = int(parts[1])
    except ValueError:
        count = 0
    if count <= 0:
        return None
    docs = list(messages.iter_message_docs())
    ids = [doc['_id'] for doc in docs[-count:] if '_id' in doc]
    if ids:
        state.database.delete_many({'_id': {'$in': ids}})
    return messages.add_system_message('管理员删除了最后 %s 条消息' % count)
