"""权限组与权限检查。

权限点：
- message.send / message.recall.any
- chat.clear / chat.delete / chat.change_color
- moderation.mute / moderation.unmute
- admin.panel / admin.users / admin.groups / admin.plugins
- admin.traffic / admin.database / admin.settings
- plugins.<插件名>.<动作>（插件自定义）

权限组配置位于 config.json 的 permission_groups（组名 -> 权限列表，支持通配符，如 "*"、chat.*），
user_groups 保存用户 -> 组名映射，default_group 为默认组。
admins 配置列表中的用户自动拥有 admin 组的全部权限。
"""
from . import config, state


def _group_of(username):
    groups = state.settings.get('user_groups') or {}
    return groups.get(username) or state.settings.get('default_group') or 'user'


def _group_permissions(group):
    groups = state.settings.get('permission_groups') or {}
    return list(groups.get(group) or [])


def user_permissions(username):
    """返回用户所在权限组的权限列表（含通配符展开）。"""
    if username in state.admins:
        return ['*']
    return _group_permissions(_group_of(username))


def expanded_permissions(username):
    """展开通配符，返回用户实际拥有的具体权限点列表（供前端判断/展示）。"""
    if username in state.admins:
        return all_permission_points()
    rules = _group_permissions(_group_of(username))
    if '*' in rules:
        return all_permission_points()
    result = set()
    for rule in rules:
        if rule.endswith('.*'):
            prefix = rule[:-1]
            for point in all_permission_points():
                if point.startswith(prefix):
                    result.add(point)
        else:
            result.add(rule)
    return sorted(result)


def _permission_matches(rule, permission):
    if rule == '*' or rule == permission:
        return True
    if rule.endswith('.*'):
        prefix = rule[:-1]
        return permission.startswith(prefix)
    return False


def group_grants(group, permission):
    """判断权限组是否授予某权限点（含通配符）。"""
    for rule in _group_permissions(group):
        if _permission_matches(rule, permission):
            return True
    return False


def has_permission(username, permission):
    if permission == '*' or username in state.admins:
        return True
    for rule in _group_permissions(_group_of(username)):
        if _permission_matches(rule, permission):
            return True
    return False


def can_execute_command(username, permission):
    if not permission:
        return True
    return has_permission(username, permission)


def is_admin(username):
    """向后兼容的管理员判断（管理员列表或 admin 权限组）。"""
    if username in state.admins:
        return True
    return 'admin' in (state.settings.get('permission_groups') or {}) and \
        _group_of(username) == 'admin'


def all_groups():
    return state.settings.get('permission_groups') or {}


def all_permission_points():
    """已知权限点（供管理面板展示）。"""
    base = [
        'message.send', 'message.recall.any',
        'chat.clear', 'chat.delete', 'chat.change_color',
        'moderation.mute', 'moderation.unmute',
        'admin.panel', 'admin.users', 'admin.groups', 'admin.plugins',
        'admin.traffic', 'admin.database', 'admin.settings', 'admin.tools',
    ]
    from . import commands
    for entry in commands.COMMANDS.values():
        if entry.get('permission') and entry['permission'] not in base:
            base.append(entry['permission'])
    from . import plugin_manager
    for permission in plugin_manager.known_permissions():
        if permission not in base:
            base.append(permission)
    return sorted(base)
