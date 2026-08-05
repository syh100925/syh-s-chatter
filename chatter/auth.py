"""会话、token 认证、请求辅助与在线状态。"""
import os
import random
import time

from flask import jsonify, request

from . import state


def _session_paths():
    return (os.path.join(state.DATA_DIR, 'login_users.txt'),
            os.path.join(state.DATA_DIR, 'login_passes.txt'))


def load_sessions():
    users_path, passes_path = _session_paths()
    try:
        with open(users_path, 'r', encoding='utf-8') as stream:
            users = stream.read().splitlines()
        with open(passes_path, 'r', encoding='utf-8') as stream:
            tokens = stream.read().splitlines()
    except FileNotFoundError:
        return {}
    return {user: token for user, token in zip(users, tokens) if user and token}


def save_sessions(sessions):
    users_path, passes_path = _session_paths()
    with open(users_path, 'w', encoding='utf-8') as stream:
        stream.write('\n'.join(sessions.keys()))
    with open(passes_path, 'w', encoding='utf-8') as stream:
        stream.write('\n'.join(str(token) for token in sessions.values()))


def authenticate_token(token, username=None):
    token = '' if token is None else str(token)
    sessions = load_sessions()
    for session_user, session_token in sessions.items():
        if session_token == token and (username is None or session_user == username):
            return session_user
    return None


def request_payload():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else request.form


def request_token():
    payload = request_payload()
    return (request.args.get('update') or payload.get('update')
            or request.headers.get('X-Chat-Token'))


def authenticate_request():
    # token 是权威来源；请求体中的用户名仅为兼容旧客户端保留，
    # 绝不能用来决定执行者身份。
    return authenticate_token(request_token())


def json_error(message, status=400, **extra):
    body = {'ok': False, 'error': message}
    body.update(extra)
    return jsonify(body), status


def touch_presence(username):
    now = time.time()
    state.loginings[:] = [entry for entry in state.loginings if now - entry['time'] <= 10]
    for entry in state.loginings:
        if entry['username'] == username:
            entry['time'] = now
            return
    state.loginings.append({'username': username, 'time': now})


def save_login(username):
    sessions = load_sessions()
    token = str(random.randint(1000000000, 9999999999))
    sessions[username] = token
    save_sessions(sessions)
    touch_presence(username)
    return token


def remove_login(username):
    sessions = load_sessions()
    sessions.pop(username, None)
    save_sessions(sessions)
