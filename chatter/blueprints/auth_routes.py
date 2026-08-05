"""认证与页面路由：登录、登出、注册、错误页、聊天室主页。"""
from flask import redirect, render_template, request, url_for

from .. import auth, messages, permissions, plugin_manager, state, users
from ..state import logger
from . import make_blueprint

bp = make_blueprint('auth')


@bp.route('/')
def normal():
    return render_template('login.html', registered=request.args.get('registered'))


@bp.route('/logout')
def logout():
    username = auth.authenticate_token(auth.request_token())
    if username:
        auth.remove_login(username)
        plugin_manager.emit('logout', username=username)
    return redirect(url_for('auth.normal'))


@bp.route('/error')
def error():
    return render_template('login_error.html')


@bp.route('/chatts', methods=['GET', 'POST'])
def chat():
    users.reload_users()
    sessions = auth.load_sessions()
    token = request.args.get('update')
    username = auth.authenticate_token(token) if token else None
    password = None
    session_login = bool(username)
    if username:
        password = state.passwords[state.usernames.index(username)] if username in state.usernames else None
    else:
        candidate = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        username = candidate if candidate in state.usernames else None

    if not username or username not in state.usernames:
        return redirect(url_for('auth.error'))
    if session_login:
        valid_password = True
    else:
        from werkzeug.security import check_password_hash
        try:
            valid_password = check_password_hash(state.passwords[state.usernames.index(username)], password)
        except (IndexError, ValueError, TypeError):
            valid_password = False
    if not valid_password:
        return redirect(url_for('auth.error'))

    e_update = token if token and token == sessions.get(username) else auth.save_login(username)
    logger.info('用户：%s 登入聊天室', username)
    plugin_manager.emit('login', username=username)
    return render_template(
        'chat.html',
        text=str(request.args.get('text') or ''),
        username=username,
        update=e_update,
        self_ip=state.server_ip,
        jump_ip='http://' + state.server_ip + state.base_path + '/chatts?update=' + str(e_update),
        is_admin=permissions.is_admin(username),
        permissions=permissions.expanded_permissions(username),
        mute_until=messages.mute_state(username)['muted_until'],
    )


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    invite_code = request.form.get('invite_code', '').strip()
    color = request.form.get('color', '#808080').strip()
    if not username or not password or not invite_code:
        return render_template('register.html', error='所有字段都必须填写', username=username,
                               color=color, invite_code=invite_code)

    existing_users = state.read_lines('usernames.list')
    if username in existing_users:
        return render_template('register.html', error='用户名已存在，请选择其他名称',
                               username=username, color=color, invite_code=invite_code)
    if username == 'system':
        return render_template('register.html', error='该用户名被系统保留，请选择其他名称',
                               username=username, color=color, invite_code=invite_code)

    codes = state.read_lines('invite_code.txt')
    if invite_code not in codes:
        return render_template('register.html', error='无效的邀请码',
                               username=username, color=color, invite_code=invite_code)

    codes.remove(invite_code)
    import os
    with open(os.path.join(state.DATA_DIR, 'invite_code.txt'), 'w', encoding='utf-8') as stream:
        stream.write('\n'.join(codes) + ('\n' if codes else ''))
    from werkzeug.security import generate_password_hash
    users.append_user(username, generate_password_hash(password), color)
    users.reload_users()
    logger.info('新用户注册：%s，颜色：%s', username, color)
    plugin_manager.emit('register', username=username)
    return redirect(url_for('auth.normal', registered='true'))
