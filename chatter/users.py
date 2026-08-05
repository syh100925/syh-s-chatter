"""用户文件存取与颜色。"""
import os

from . import state


def reload_users():
    state.usernames = state.read_lines('usernames.list')
    state.passwords = state.read_lines('passwords.list')
    state.user_colors = state.read_lines('colors.list')


def get_user_color(username):
    try:
        index = state.usernames.index(username)
    except ValueError:
        return '#808080'
    return state.user_colors[index] if index < len(state.user_colors) and state.user_colors[index] else '#808080'


def set_user_color(username, color):
    if username not in state.usernames:
        return False
    index = state.usernames.index(username)
    while len(state.user_colors) <= index:
        state.user_colors.append('#808080')
    state.user_colors[index] = color
    with open(os.path.join(state.DATA_DIR, 'colors.list'), 'w', encoding='utf-8') as stream:
        stream.write('\n'.join(state.user_colors) + '\n')
    return True


def append_user(username, hashed_password, color):
    with open(os.path.join(state.DATA_DIR, 'usernames.list'), 'a', encoding='utf-8') as stream:
        stream.write(username + '\n')
    with open(os.path.join(state.DATA_DIR, 'passwords.list'), 'a', encoding='utf-8') as stream:
        stream.write(hashed_password + '\n')
    with open(os.path.join(state.DATA_DIR, 'colors.list'), 'a', encoding='utf-8') as stream:
        stream.write(color + '\n')
    state.usernames.append(username)
    state.passwords.append(hashed_password)
    state.user_colors.append(color)


def _write_all():
    """将当前内存中的用户数据整体写回文件。"""
    with open(os.path.join(state.DATA_DIR, 'usernames.list'), 'w', encoding='utf-8') as stream:
        stream.write('\n'.join(state.usernames) + ('\n' if state.usernames else ''))
    with open(os.path.join(state.DATA_DIR, 'passwords.list'), 'w', encoding='utf-8') as stream:
        stream.write('\n'.join(state.passwords) + ('\n' if state.passwords else ''))
    with open(os.path.join(state.DATA_DIR, 'colors.list'), 'w', encoding='utf-8') as stream:
        stream.write('\n'.join(state.user_colors) + ('\n' if state.user_colors else ''))


def rename_user(old_name, new_name):
    if old_name not in state.usernames or new_name in state.usernames:
        return False
    index = state.usernames.index(old_name)
    state.usernames[index] = new_name
    _write_all()
    return True


def change_password(username, hashed_password):
    if username not in state.usernames:
        return False
    index = state.usernames.index(username)
    state.passwords[index] = hashed_password
    _write_all()
    return True


def delete_user(username):
    if username not in state.usernames:
        return False
    index = state.usernames.index(username)
    del state.usernames[index]
    del state.passwords[index]
    if index < len(state.user_colors):
        del state.user_colors[index]
    _write_all()
    return True
