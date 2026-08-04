"""Modern JSON/SSE API for the React client and user-owned bot tokens.

The legacy Flask routes remain in server.py. This module deliberately keeps the
new contract separate so old clients never receive new fields or private data.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import mimetypes
import os
import queue
import re
import secrets
import threading
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    request,
    send_file,
    session,
    stream_with_context,
)
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

try:
    import gridfs
    from bson import ObjectId
except ImportError:  # pragma: no cover - pymongo is a runtime dependency
    gridfs = None
    ObjectId = None


PUBLIC_CONVERSATION = 'public'
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_MESSAGE_LENGTH = 64 * 1024
MAX_PREVIEW_BYTES = 4 * 1024 * 1024
MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_METADATA_BYTES = 100 * 1024 * 1024
EDIT_WINDOW_SECONDS = 15 * 60
RECALL_WINDOW_SECONDS = 120
TOKEN_PREFIX = 'hzc_'
MAX_PROFILE_NAME = 80
MAX_PROFILE_STATUS = 160
MAX_PROFILE_BIO = 1_000
MAX_SEARCH_RESULTS = 100
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


def _now() -> float:
    return time.time()


def _json_payload() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload
    return request.form.to_dict(flat=True)


def _error(message: str, status: int = 400, **extra: Any):
    body = {'ok': False, 'error': message}
    body.update(extra)
    return jsonify(body), status


def _as_text(value: Any) -> str:
    if value is None:
        return ''
    return value if isinstance(value, str) else str(value)


def _decode_text_candidates(data: bytes) -> tuple[str, str, list[dict[str, Any]]]:
    try:
        from charset_normalizer import from_bytes
        matches = list(from_bytes(data).results)[:5]
    except Exception:
        matches = []
    candidates: list[dict[str, Any]] = []
    for match in matches:
        encoding = getattr(match, 'encoding', None)
        if encoding:
            candidates.append({
                'encoding': encoding,
                'confidence': getattr(match, 'coherence', 0),
                'content': str(match),
            })
    if not candidates:
        candidates = [{'encoding': 'utf-8', 'confidence': 0, 'content': data.decode('utf-8', errors='replace')}]
    selected = candidates[0]
    encoding = str(selected['encoding'])
    content = str(selected['content'])
    if encoding.lower() in {'big5', 'cp950', 'gbk', 'gb2312', 'gb18030'}:
        try:
            mainland_content = data.decode('gb18030')
            if any('\u4e00' <= character <= '\u9fff' for character in mainland_content):
                content = mainland_content
                encoding = 'gb18030'
        except UnicodeDecodeError:
            pass
    return content, encoding, candidates


def _legacy_timestamp(value: Any) -> float:
    try:
        return datetime.strptime(str(value), '%Y:%m:%d:%H:%M').timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _created_at(document: dict[str, Any]) -> float:
    value = document.get('created_at', document.get('timestamp'))
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return _legacy_timestamp(document.get('time', ''))


def _message_id(document: dict[str, Any], index: int = 0) -> str:
    value = document.get('id')
    if value:
        return str(value)
    object_id = document.get('_id')
    if object_id is not None:
        return 'legacy-' + str(object_id)
    return 'legacy-' + str(index)


def _encode_cursor(created_at: float, message_id: str) -> str:
    raw = json.dumps({'created_at': created_at, 'id': message_id}, separators=(',', ':'))
    return base64.urlsafe_b64encode(raw.encode('utf-8')).decode('ascii').rstrip('=')


def _decode_cursor(value: str | None) -> tuple[float, str] | None:
    if not value:
        return None
    try:
        padded = value + '=' * (-len(value) % 4)
        parsed = json.loads(base64.urlsafe_b64decode(padded).decode('utf-8'))
        return float(parsed['created_at']), str(parsed['id'])
    except (TypeError, ValueError, KeyError, json.JSONDecodeError, binascii.Error, UnicodeDecodeError, OverflowError):
        return None


def _sort_key(document: dict[str, Any], index: int = 0) -> tuple[float, str, int]:
    return (_created_at(document), _message_id(document, index), index)


def _direct_id(first: str, second: str) -> str:
    names = json.dumps(sorted((first, second)), ensure_ascii=True, separators=(',', ':'))
    encoded = base64.urlsafe_b64encode(names.encode('utf-8')).decode('ascii').rstrip('=')
    return 'dm:' + encoded


def _direct_participants(conversation_id: str) -> list[str]:
    if not conversation_id.startswith('dm:'):
        return []
    try:
        padded = conversation_id[3:] + '=' * (-len(conversation_id[3:]) % 4)
        values = json.loads(base64.urlsafe_b64decode(padded).decode('utf-8'))
        return [str(item) for item in values] if isinstance(values, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


class EventHub:
    """Small in-process event bus for the single-node deployment target."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[str, tuple[str, queue.Queue[dict[str, Any]]]] = {}
        self._sequence = 0

    def subscribe(self, username: str) -> tuple[str, queue.Queue[dict[str, Any]]]:
        identifier = uuid.uuid4().hex
        subscriber = queue.Queue(maxsize=128)
        with self._lock:
            self._subscribers[identifier] = (username, subscriber)
        return identifier, subscriber

    def unsubscribe(self, identifier: str) -> None:
        with self._lock:
            self._subscribers.pop(identifier, None)

    def publish(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        conversation_id: str | None = None,
        audience: set[str] | None = None,
        exclude: str | None = None,
    ) -> None:
        with self._lock:
            self._sequence += 1
            event = {
                'id': str(self._sequence),
                'type': event_type,
                'conversation_id': conversation_id,
                'data': data,
            }
            subscribers = list(self._subscribers.values())
        for username, subscriber in subscribers:
            if exclude and username == exclude:
                continue
            if audience is not None and username not in audience:
                continue
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(event)
                except queue.Empty:
                    pass


class V2Service:
    def __init__(self, app, state: dict[str, Any]) -> None:
        self.app = app
        self.state = state
        self.db = state['db']
        self.database = state['database']
        self.profiles = self.db['v2_profiles']
        self.read_cursors = self.db['v2_read_cursors']
        self.hidden_messages = self.db['v2_hidden_messages']
        self.notifications = self.db['v2_notifications']
        self.edits = self.db['v2_message_edits']
        self.preferences = self.db['v2_conversation_preferences']
        self.blocks = self.db['v2_blocks']
        self.bookmarks = self.db['v2_message_bookmarks']
        self.pins = self.db['v2_pinned_messages']
        self.reports = self.db['v2_reports']
        self.bot_tokens = self.db['v2_bot_tokens']
        self.streams = self.db['v2_streams']
        self.files = self.db['v2_file_metadata']
        self.upload_sessions = self.db['v2_upload_sessions']
        self.audit = self.db['v2_audit']
        self.event_hub = EventHub()
        self._memory_files: dict[str, tuple[bytes, dict[str, Any]]] = {}
        self._file_lock = threading.RLock()
        self._gridfs = None
        if gridfs is not None:
            try:
                self._gridfs = gridfs.GridFS(self.db)
            except Exception:
                self._gridfs = None
        self._configure_app()
        self._register_indexes()
        self._register_routes()
        state['set_event_publisher'](self.publish_legacy_event)
        state['set_legacy_file_provider'](self.find_legacy_file)

    def _configure_app(self) -> None:
        app = self.app
        app.secret_key = os.environ.get('CHAT_SECRET_KEY') or secrets.token_hex(32)
        app.config.setdefault('SESSION_COOKIE_HTTPONLY', True)
        app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')
        app.config.setdefault('SESSION_COOKIE_SECURE', os.environ.get('CHAT_COOKIE_SECURE') == '1')
        app.config.setdefault('PERMANENT_SESSION_LIFETIME', 60 * 60 * 24 * 30)

    def _register_indexes(self) -> None:
        for collection, keys in (
            (self.profiles, [('username', 1)]),
            (self.read_cursors, [('username', 1), ('conversation_id', 1)]),
            (self.hidden_messages, [('username', 1), ('message_id', 1)]),
            (self.notifications, [('username', 1), ('created_at', -1)]),
            (self.preferences, [('username', 1), ('conversation_id', 1)]),
            (self.blocks, [('blocker', 1), ('blocked', 1)]),
            (self.bookmarks, [('username', 1), ('message_id', 1)]),
            (self.pins, [('conversation_id', 1), ('message_id', 1)]),
            (self.reports, [('status', 1), ('created_at', -1)]),
            (self.bot_tokens, [('username', 1), ('active', 1), ('token_hash', 1)]),
            (self.streams, [('owner', 1), ('status', 1), ('created_at', -1)]),
            (self.files, [('file_id', 1), ('filename', 1)]),
            (self.upload_sessions, [('upload_id', 1), ('owner', 1), ('status', 1)]),
            (self.audit, [('created_at', -1), ('actor', 1)]),
        ):
            try:
                collection.create_index(keys)
            except Exception:
                pass

    def _register_routes(self) -> None:
        blueprint = Blueprint('api_v2', __name__, url_prefix='/api/v2')

        blueprint.add_url_rule('/auth/login', 'auth_login', self.auth_login, methods=['POST'])
        blueprint.add_url_rule('/auth/logout', 'auth_logout', self.auth_logout, methods=['POST'])
        blueprint.add_url_rule('/auth/me', 'auth_me', self.auth_me, methods=['GET'])
        blueprint.add_url_rule('/profile', 'profile', self.profile, methods=['GET', 'PATCH'])
        blueprint.add_url_rule('/users', 'users', self.users, methods=['GET'])
        blueprint.add_url_rule('/users/<target_username>/block', 'user_block', self.user_block, methods=['POST', 'DELETE'])
        blueprint.add_url_rule('/blocks', 'blocks', self.block_list, methods=['GET'])
        blueprint.add_url_rule('/conversations', 'conversations', self.conversations, methods=['GET'])
        blueprint.add_url_rule('/conversations/direct', 'direct_conversation', self.direct_conversation, methods=['POST'])
        blueprint.add_url_rule('/conversations/<conversation_id>/preferences', 'conversation_preferences', self.conversation_preferences, methods=['GET', 'PATCH'])
        blueprint.add_url_rule('/conversations/<conversation_id>/pins', 'conversation_pins', self.conversation_pins, methods=['GET'])
        blueprint.add_url_rule('/conversations/<conversation_id>/messages', 'messages', self.messages, methods=['GET', 'POST'])
        blueprint.add_url_rule('/search', 'search', self.search, methods=['GET'])
        blueprint.add_url_rule('/messages/<message_id>', 'message', self.message, methods=['PATCH', 'DELETE'])
        blueprint.add_url_rule('/messages/<message_id>/recall', 'message_recall', self.message_recall, methods=['POST'])
        blueprint.add_url_rule('/messages/<message_id>/reactions', 'message_reactions', self.message_reactions, methods=['POST'])
        blueprint.add_url_rule('/messages/<message_id>/forward', 'message_forward', self.message_forward, methods=['POST'])
        blueprint.add_url_rule('/messages/<message_id>/bookmark', 'message_bookmark', self.message_bookmark, methods=['POST', 'DELETE'])
        blueprint.add_url_rule('/bookmarks', 'bookmarks', self.bookmark_list, methods=['GET'])
        blueprint.add_url_rule('/messages/<message_id>/pin', 'message_pin', self.message_pin, methods=['POST', 'DELETE'])
        blueprint.add_url_rule('/messages/<message_id>/reports', 'message_report', self.message_report, methods=['POST'])
        blueprint.add_url_rule('/conversations/<conversation_id>/typing', 'typing', self.typing, methods=['POST'])
        blueprint.add_url_rule('/conversations/<conversation_id>/read', 'read', self.read, methods=['POST'])
        blueprint.add_url_rule('/events', 'events', self.events, methods=['GET'])
        blueprint.add_url_rule('/notifications', 'notifications', self.notification_list, methods=['GET'])
        blueprint.add_url_rule('/notifications/read', 'notifications_read', self.notifications_read, methods=['POST'])
        blueprint.add_url_rule('/emojis', 'emojis', self.emojis, methods=['GET'])
        blueprint.add_url_rule('/emojis', 'emoji_upload', self.emoji_upload, methods=['POST'])
        blueprint.add_url_rule('/emojis/<path:filename>', 'emoji_delete', self.emoji_delete, methods=['DELETE'])
        blueprint.add_url_rule('/uploads', 'uploads', self.uploads, methods=['POST'])
        blueprint.add_url_rule('/uploads/init', 'upload_init', self.upload_init, methods=['POST'])
        blueprint.add_url_rule('/uploads/<upload_id>/chunks/<int:chunk_index>', 'upload_chunk', self.upload_chunk, methods=['PUT', 'POST'])
        blueprint.add_url_rule('/uploads/<upload_id>/complete', 'upload_complete', self.upload_complete, methods=['POST'])
        blueprint.add_url_rule('/uploads/<upload_id>', 'upload_session', self.upload_session, methods=['DELETE'])
        blueprint.add_url_rule('/uploads/<file_id>', 'upload_file', self.upload_file, methods=['GET'])
        blueprint.add_url_rule('/files/<file_id>/preview', 'file_preview', self.file_preview, methods=['GET'])
        blueprint.add_url_rule('/files/legacy-preview', 'legacy_file_preview', self.legacy_file_preview, methods=['GET'])
        blueprint.add_url_rule('/bot/token', 'bot_token', self.bot_token, methods=['POST', 'DELETE'])
        blueprint.add_url_rule('/bot/messages', 'bot_messages', self.bot_messages, methods=['GET', 'POST'])
        blueprint.add_url_rule('/bot/events', 'bot_events', self.bot_events, methods=['GET'])
        blueprint.add_url_rule('/bot/streams', 'bot_stream_start', self.bot_stream_start, methods=['POST'])
        blueprint.add_url_rule('/bot/streams/<stream_id>', 'bot_stream', self.bot_stream, methods=['POST', 'PATCH', 'DELETE'])
        blueprint.add_url_rule('/admin/audit', 'admin_audit', self.admin_audit, methods=['GET'])
        blueprint.add_url_rule('/admin/reports', 'admin_reports', self.admin_reports, methods=['GET', 'PATCH'])
        blueprint.add_url_rule('/admin/users', 'admin_users', self.admin_users, methods=['GET'])
        blueprint.add_url_rule('/admin/users/<target_username>/mute', 'admin_mute', self.admin_mute, methods=['POST', 'DELETE'])
        blueprint.add_url_rule('/admin/purge', 'admin_purge', self.admin_purge, methods=['POST'])
        self.app.register_blueprint(blueprint)

        @self.app.route('/app')
        @self.app.route('/app/<path:filename>')
        def modern_app(filename: str | None = None):
            dist = Path(self.state['base_dir']) / 'frontend' / 'dist'
            requested = dist / filename if filename else dist / 'index.html'
            if filename and requested.is_file() and dist in requested.resolve().parents:
                return send_file(requested)
            index = dist / 'index.html'
            if index.is_file():
                return send_file(index)
            return _error('现代客户端尚未构建，请先运行 npm run build', 503)

    def _user_records(self) -> list[dict[str, str]]:
        return list(self.state['get_users']())

    def _user_exists(self, username: str) -> bool:
        return any(item['username'] == username for item in self._user_records())

    def _password_hash(self, username: str) -> str | None:
        for item in self._user_records():
            if item['username'] == username:
                return item.get('password', '')
        return None

    def _role(self, username: str) -> str:
        if username == 'admin':
            return 'owner'
        if self.state['is_admin'](username):
            return 'admin'
        return 'user'

    def ensure_profile(self, username: str) -> dict[str, Any]:
        color = self.state['get_user_color'](username)
        self.profiles.update_one(
            {'username': username},
            {
                '$setOnInsert': {
                    'username': username,
                    'display_name': username,
                    'color': color,
                    'avatar_url': None,
                    'status': '',
                    'bio': '',
                    'created_at': _now(),
                }
            },
            upsert=True,
        )
        profile = self.profiles.find_one({'username': username}) or {}
        profile.setdefault('display_name', username)
        profile.setdefault('color', color)
        profile.setdefault('avatar_url', None)
        profile.setdefault('status', '')
        profile.setdefault('bio', '')
        profile['role'] = self._role(username)
        profile.pop('_id', None)
        return profile

    def serialize_user(self, username: str) -> dict[str, Any]:
        profile = self.ensure_profile(username)
        return {
            'username': username,
            'display_name': profile.get('display_name') or username,
            'color': profile.get('color') or self.state['get_user_color'](username),
            'avatar_url': profile.get('avatar_url'),
            'status': profile.get('status') or '',
            'bio': profile.get('bio') or '',
            'role': profile.get('role', self._role(username)),
        }

    def _token_user(self) -> str | None:
        authorization = request.headers.get('Authorization', '')
        token = authorization[7:].strip() if authorization.lower().startswith('bearer ') else ''
        if not token:
            token = request.headers.get('X-Chat-API-Key', '').strip()
        if not token:
            return None
        record = self.bot_tokens.find_one({'token_hash': self._hash_token(token), 'active': True})
        if not record:
            return None
        expires_at = float(record.get('expires_at') or 0)
        if expires_at and expires_at <= _now():
            self.bot_tokens.update_one({'_id': record['_id']}, {'$set': {'active': False, 'revoked_at': _now()}})
            return None
        return str(record.get('username'))

    def current_user(self) -> tuple[str | None, bool]:
        token_user = self._token_user()
        if token_user:
            return token_user, True
        username = session.get('v2_user')
        return (str(username), False) if username and self._user_exists(str(username)) else (None, False)

    def require_user(self, *, csrf: bool = False) -> tuple[str | None, bool, Any | None]:
        username, is_token = self.current_user()
        if not username:
            return None, is_token, _error('认证数据错误', 401)
        if csrf and not is_token and request.method in {'POST', 'PATCH', 'DELETE'}:
            expected = session.get('v2_csrf')
            if not expected or request.headers.get('X-CSRF-Token') != expected:
                return None, is_token, _error('CSRF 校验失败', 403)
        self.state['touch_presence'](username)
        return username, is_token, None

    def auth_login(self):
        payload = _json_payload()
        username = _as_text(payload.get('username')).strip()
        password = _as_text(payload.get('password'))
        stored = self._password_hash(username)
        if not username or not stored:
            return _error('用户名或密码错误', 401)
        try:
            valid = check_password_hash(stored, password)
        except (TypeError, ValueError):
            valid = False
        if not valid:
            return _error('用户名或密码错误', 401)
        session.clear()
        session.permanent = True
        session['v2_user'] = username
        session['v2_csrf'] = secrets.token_urlsafe(24)
        return jsonify({'ok': True, 'user': self.serialize_user(username), 'csrf_token': session['v2_csrf']})

    def auth_logout(self):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        session.clear()
        return jsonify({'ok': True, 'user': username})

    def auth_me(self):
        username, is_token, error = self.require_user()
        if error:
            return error
        return jsonify({'ok': True, 'user': self.serialize_user(username), 'token_auth': is_token, 'csrf_token': session.get('v2_csrf')})

    def profile(self):
        username, _, error = self.require_user(csrf=request.method == 'PATCH')
        if error:
            return error
        if request.method == 'GET':
            return jsonify({'ok': True, 'user': self.serialize_user(username)})
        payload = _json_payload()
        updates: dict[str, Any] = {}
        if 'display_name' in payload:
            display_name = _as_text(payload.get('display_name')).strip()
            if not display_name or len(display_name) > MAX_PROFILE_NAME:
                return _error('显示名称长度必须为 1-80 个字符', 400)
            updates['display_name'] = display_name
        if 'status' in payload:
            status = _as_text(payload.get('status')).strip()
            if len(status) > MAX_PROFILE_STATUS:
                return _error('状态长度不能超过 160 个字符', 400)
            updates['status'] = status
        if 'bio' in payload:
            bio = _as_text(payload.get('bio'))
            if len(bio) > MAX_PROFILE_BIO:
                return _error('个人简介长度不能超过 1000 个字符', 400)
            updates['bio'] = bio
        if 'avatar_url' in payload:
            avatar_url = _as_text(payload.get('avatar_url')).strip() or None
            if avatar_url:
                parsed = urlparse(avatar_url)
                if not (avatar_url.startswith('/') and not avatar_url.startswith('//')) and parsed.scheme not in {'http', 'https'}:
                    return _error('头像地址必须是 HTTP(S) 或站内路径', 400)
            updates['avatar_url'] = avatar_url
        if not updates:
            return _error('没有可更新的资料字段', 400)
        updates['updated_at'] = _now()
        self.profiles.update_one({'username': username}, {'$set': updates}, upsert=True)
        return jsonify({'ok': True, 'user': self.serialize_user(username)})

    def users(self):
        username, _, error = self.require_user()
        if error:
            return error
        users = []
        for item in self._user_records():
            target = item['username']
            if target == username:
                continue
            user = self.serialize_user(target)
            user['blocked'] = self._is_blocked(username, target)
            user['blocked_by'] = self._is_blocked(target, username)
            users.append(user)
        return jsonify({'ok': True, 'users': users})

    def _is_blocked(self, blocker: str, blocked: str) -> bool:
        if not blocker or not blocked or blocker == blocked:
            return False
        return bool(self.blocks.find_one({'blocker': blocker, 'blocked': blocked}))

    def _conversation_blocked(self, username: str, conversation_id: str) -> bool:
        for participant in _direct_participants(conversation_id):
            if participant != username and (self._is_blocked(username, participant) or self._is_blocked(participant, username)):
                return True
        return False

    def user_block(self, target_username: str):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        target_username = _as_text(target_username).strip()
        if not self._user_exists(target_username) or target_username == username:
            return _error('用户不存在或不能屏蔽自己', 400)
        if request.method == 'DELETE':
            self.blocks.delete_one({'blocker': username, 'blocked': target_username})
            return jsonify({'ok': True, 'username': target_username, 'blocked': False})
        self.blocks.update_one(
            {'blocker': username, 'blocked': target_username},
            {'$set': {'blocker': username, 'blocked': target_username, 'created_at': _now()}},
            upsert=True,
        )
        return jsonify({'ok': True, 'username': target_username, 'blocked': True})

    def block_list(self):
        username, _, error = self.require_user()
        if error:
            return error
        blocked = [self.serialize_user(str(item['blocked'])) for item in self.blocks.find({'blocker': username}).sort('created_at', -1)]
        return jsonify({'ok': True, 'blocked': blocked})

    def _conversation_allowed(self, username: str, conversation_id: str) -> bool:
        if conversation_id == PUBLIC_CONVERSATION:
            return True
        participants = _direct_participants(conversation_id)
        return len(participants) == 2 and username in participants and all(self._user_exists(item) for item in participants)

    def _conversation_users(self, conversation_id: str) -> set[str]:
        participants = set(_direct_participants(conversation_id))
        if conversation_id == PUBLIC_CONVERSATION:
            return {item['username'] for item in self._user_records()}
        return {
            participant for participant in participants
            if self._user_exists(participant)
            and not any(
                self._is_blocked(participant, other) or self._is_blocked(other, participant)
                for other in participants
                if other != participant
            )
        }

    def _conversation_preference(self, username: str, conversation_id: str) -> dict[str, Any]:
        preference = self.preferences.find_one({'username': username, 'conversation_id': conversation_id}) or {}
        return {
            'pinned': bool(preference.get('pinned', False)),
            'muted': bool(preference.get('muted', False)),
            'archived': bool(preference.get('archived', False)),
            'hidden': bool(preference.get('hidden', False)),
        }

    def conversation_payload(self, username: str, conversation_id: str) -> dict[str, Any]:
        preference = self._conversation_preference(username, conversation_id)
        last = self._find_messages(conversation_id)[-1:]
        if conversation_id == PUBLIC_CONVERSATION:
            return {
                'id': PUBLIC_CONVERSATION,
                'kind': 'public',
                'title': '公共聊天室',
                'participants': [],
                'unread': self._unread_count(username, PUBLIC_CONVERSATION),
                'last_message': self.serialize_message(last[0]) if last else None,
                **preference,
            }
        participants = _direct_participants(conversation_id)
        other = next((item for item in participants if item != username), username)
        return {
            'id': conversation_id,
            'kind': 'direct',
            'title': other,
            'participants': [self.serialize_user(item) for item in participants if self._user_exists(item)],
            'unread': self._unread_count(username, conversation_id),
            'last_message': self.serialize_message(last[0]) if last else None,
            'blocked': self._conversation_blocked(username, conversation_id),
            **preference,
        }

    def conversations(self):
        username, _, error = self.require_user()
        if error:
            return error
        result = [self.conversation_payload(username, PUBLIC_CONVERSATION)]
        for item in self._user_records():
            target = item['username']
            if target != username:
                result.append(self.conversation_payload(username, _direct_id(username, target)))
        return jsonify({'ok': True, 'conversations': result})

    def direct_conversation(self):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        target = _as_text(_json_payload().get('username')).strip()
        if not target or target == username or not self._user_exists(target):
            return _error('用户不存在或不能与自己私聊', 400)
        return jsonify({'ok': True, 'conversation': self.conversation_payload(username, _direct_id(username, target))})

    def conversation_preferences(self, conversation_id: str):
        username, _, error = self.require_user(csrf=request.method == 'PATCH')
        if error:
            return error
        if not self._conversation_allowed(username, conversation_id):
            return _error('没有权限访问该会话', 403)
        if request.method == 'GET':
            return jsonify({'ok': True, 'conversation_id': conversation_id, 'preferences': self._conversation_preference(username, conversation_id)})
        payload = _json_payload()
        allowed = {'pinned', 'muted', 'archived', 'hidden'}
        updates = {key: bool(payload[key]) for key in allowed if key in payload}
        if not updates:
            return _error('没有可更新的会话偏好', 400)
        updates['updated_at'] = _now()
        self.preferences.update_one(
            {'username': username, 'conversation_id': conversation_id},
            {'$set': {'username': username, 'conversation_id': conversation_id, **updates}},
            upsert=True,
        )
        result = self._conversation_preference(username, conversation_id)
        self.event_hub.publish('conversation.updated', {'conversation': self.conversation_payload(username, conversation_id)}, audience={username})
        return jsonify({'ok': True, 'conversation_id': conversation_id, 'preferences': result})

    def search(self):
        username, _, error = self.require_user()
        if error:
            return error
        query_text = _as_text(request.args.get('q')).strip()
        if not query_text:
            return jsonify({'ok': True, 'results': []})
        conversation_id = _as_text(request.args.get('conversation_id')).strip()
        if conversation_id and not self._conversation_allowed(username, conversation_id):
            return _error('没有权限搜索该会话', 403)
        try:
            limit = min(MAX_SEARCH_RESULTS, max(1, int(request.args.get('limit', 30))))
        except (TypeError, ValueError):
            limit = 30
        target_user = _as_text(request.args.get('user')).strip()
        matcher = re.compile(re.escape(query_text), re.IGNORECASE)
        hidden_ids = {
            str(item['message_id'])
            for item in self.hidden_messages.find({'username': username})
        }
        documents = list(self.database.find().sort('_id', -1))
        results = []
        for index, document in enumerate(documents):
            message_conversation = _as_text(document.get('conversation_id')) or PUBLIC_CONVERSATION
            if conversation_id and message_conversation != conversation_id:
                continue
            if not self._conversation_allowed(username, message_conversation):
                continue
            message_id = _message_id(document, index)
            if message_id in hidden_ids:
                continue
            actor = _as_text(document.get('user'))
            if target_user and actor != target_user:
                continue
            content = _as_text(document.get('content', document.get('chat', '')))
            if not matcher.search(content) and not matcher.search(actor):
                continue
            serialized = self.serialize_message(document, index)
            results.append({'message': serialized, 'snippet': content[:240]})
            if len(results) >= limit:
                break
        return jsonify({'ok': True, 'query': query_text, 'results': results})

    def _find_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        if conversation_id == PUBLIC_CONVERSATION:
            query = {'$or': [{'conversation_id': PUBLIC_CONVERSATION}, {'conversation_id': {'$exists': False}}]}
        else:
            query = {'conversation_id': conversation_id}
        documents = list(self.database.find(query))
        current_username = self.current_user()[0]
        if current_username:
            documents = [
                item for item in documents
                if not item.get('user')
                or item.get('user') == current_username
                or not any(
                    self._is_blocked(current_username, other) or self._is_blocked(other, current_username)
                    for other in {str(item.get('user'))}
                    if other and other != current_username
                )
            ]
        hidden = {
            str(item['message_id'])
            for item in self.hidden_messages.find({'username': self.current_user()[0], 'conversation_id': conversation_id})
        }
        documents = [item for item in documents if _message_id(item) not in hidden]
        documents.sort(key=_sort_key)
        return documents

    def _unread_count(self, username: str, conversation_id: str) -> int:
        cursor = self.read_cursors.find_one({'username': username, 'conversation_id': conversation_id})
        last_read = float(cursor.get('last_read_at', 0)) if cursor else 0
        return sum(1 for item in self._find_messages(conversation_id) if _created_at(item) > last_read and item.get('user') != username)

    def _attachment_from_content(self, content: str, message_type: str, user: str) -> list[dict[str, Any]]:
        markers = {'image': '::img::', 'audio': '::wav::', 'voice': '::wav::', 'file': '::file::', 'emoji': '::emoji::'}
        marker = markers.get(message_type)
        if not marker:
            for candidate, candidate_marker in markers.items():
                if content.startswith(candidate_marker):
                    marker = candidate_marker
                    message_type = candidate
                    break
        if not marker or not content.startswith(marker):
            return []
        filename = content[len(marker):].strip()
        if not filename:
            return []
        if message_type == 'emoji':
            url = '/chat/emoji/static/%s/%s' % (quote(user, safe=''), quote(filename, safe=''))
        else:
            safe_filename = os.path.basename(filename)
            if safe_filename != filename or '/' in filename or '\\' in filename:
                return []
            url = '/static/uploads/' + quote(safe_filename, safe='')
        return [{'id': None, 'name': filename, 'mime': mimetypes.guess_type(filename)[0] or 'application/octet-stream', 'url': url}]

    def serialize_message(self, document: dict[str, Any], index: int = 0) -> dict[str, Any]:
        content = _as_text(document.get('content', document.get('chat', '')))
        username = _as_text(document.get('user'))
        message_type = _as_text(document.get('type')) or self.state['infer_message_type'](content, None, username)
        conversation_id = _as_text(document.get('conversation_id')) or PUBLIC_CONVERSATION
        message_id = _message_id(document, index)
        viewer = self.current_user()[0]
        profile = self.serialize_user(username) if username and self._user_exists(username) else {'display_name': username, 'color': '#888888'}
        created_at = _created_at(document)
        reactions: dict[str, dict[str, Any]] = {}
        for emoji, users in (document.get('reactions') or {}).items():
            names = sorted({str(item) for item in users}) if isinstance(users, list) else []
            reactions[str(emoji)] = {'count': len(names), 'users': names, 'reacted': self.current_user()[0] in names}
        attachments = list(document.get('attachments') or [])
        if not attachments:
            attachments = self._attachment_from_content(content, message_type, username)
        for attachment in attachments:
            if attachment.get('id') and not attachment.get('url'):
                attachment['url'] = '/api/v2/uploads/' + str(attachment['id'])
        return {
            'id': message_id,
            'conversation_id': conversation_id,
            'user': username,
            'display_name': profile.get('display_name', username),
            'color': document.get('color') or profile.get('color') or '#888888',
            'time': _as_text(document.get('time')),
            'timestamp': created_at,
            'created_at': created_at,
            'content': content,
            'format': document.get('format') or ('plain' if message_type != 'text' else 'markdown'),
            'type': message_type,
            'recalled': bool(document.get('recalled', False)),
            'edited': bool(document.get('edited', False)),
            'edited_at': document.get('edited_at'),
            'reply_to': str(document['reply_to']) if document.get('reply_to') else None,
            'reactions': reactions,
            'attachments': attachments,
            'forwarded_from': document.get('forwarded_from'),
            'bookmarked': bool(viewer and self.bookmarks.find_one({'username': viewer, 'message_id': message_id})),
            'pinned': bool(self.pins.find_one({'conversation_id': conversation_id, 'message_id': message_id})),
        }

    def messages(self, conversation_id: str):
        username, is_token, error = self.require_user()
        if error:
            return error
        if not self._conversation_allowed(username, conversation_id):
            return _error('没有权限访问该会话', 403)
        payload = _json_payload() if request.method == 'POST' else request.args
        if request.method == 'GET':
            try:
                limit = min(MAX_PAGE_SIZE, max(1, int(payload.get('limit', DEFAULT_PAGE_SIZE))))
            except (TypeError, ValueError):
                limit = DEFAULT_PAGE_SIZE
            documents = self._find_messages(conversation_id)
            before = _decode_cursor(payload.get('before'))
            after = _decode_cursor(payload.get('after'))
            if before:
                documents = [item for index, item in enumerate(documents) if _sort_key(item, index)[:2] < before]
                has_more = len(documents) > limit
                documents = documents[-limit:]
            elif after:
                documents = [item for index, item in enumerate(documents) if _sort_key(item, index)[:2] > after]
                has_more = len(documents) > limit
                documents = documents[:limit]
            else:
                has_more = len(documents) > limit
                documents = documents[-limit:]
            result = [self.serialize_message(item, index) for index, item in enumerate(documents)]
            before_cursor = _encode_cursor(result[0]['created_at'], result[0]['id']) if result and has_more else None
            after_cursor = _encode_cursor(result[-1]['created_at'], result[-1]['id']) if result and has_more and not before else None
            return jsonify({'ok': True, 'conversation': self.conversation_payload(username, conversation_id), 'messages': result, 'cursors': {'before': before_cursor, 'after': after_cursor}})
        return self.create_message(username, conversation_id, payload, is_token=is_token)

    def create_message(self, username: str, conversation_id: str, payload: dict[str, Any], *, is_token: bool = False):
        if not self._conversation_allowed(username, conversation_id):
            return _error('没有权限访问该会话', 403)
        if self._conversation_blocked(username, conversation_id):
            return _error('该会话已被屏蔽，无法发送消息', 403)
        try:
            self.state['ensure_not_muted'](username)
        except Exception as exc:
            until = getattr(exc, 'muted_until', 0)
            return _error('您已被禁言', 403, muted_until=until)
        content = _as_text(payload.get('content', payload.get('upload_value', '')))
        attachments = payload.get('attachments') if isinstance(payload.get('attachments'), list) else []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                return _error('附件格式无效', 400)
            file_id = _as_text(attachment.get('id')).strip()
            if file_id and not self._file_accessible(username, file_id):
                return _error('没有权限使用该附件', 403)
            if not file_id:
                url = _as_text(attachment.get('url'))
                if url and not (url.startswith('/static/uploads/') or url.startswith('/api/v2/uploads/')):
                    return _error('附件地址无效', 400)
        if not content and not attachments:
            return _error('消息不能为空', 400)
        if len(content) > MAX_MESSAGE_LENGTH:
            return _error('消息过长', 413)
        message_type = _as_text(payload.get('type')) or self.state['infer_message_type'](content)
        reply_to = _as_text(payload.get('reply_to')) or None
        if reply_to:
            reply_document = self._find_document(reply_to)
            reply_conversation = (_as_text(reply_document.get('conversation_id')) or PUBLIC_CONVERSATION) if reply_document else None
            if not reply_document or reply_conversation != conversation_id:
                return _error('引用消息不属于当前会话', 400)
        now = _now()
        document = {
            'id': uuid.uuid4().hex,
            'chat': content,
            'content': content,
            'user': username,
            'color': self.state['get_user_color'](username),
            'time': self.state['get_current_time'](),
            'created_at': now,
            'timestamp': now,
            'type': message_type,
            'format': _as_text(payload.get('format')) or ('plain' if message_type != 'text' else 'markdown'),
            'conversation_id': conversation_id,
            'recalled': False,
            'reply_to': reply_to,
            'reactions': {},
            'edited': False,
            'attachments': attachments,
        }
        self.database.insert_one(document)
        self._notify_mentions(document)
        self.publish_legacy_event('message.created', document)
        return jsonify({'ok': True, 'message': self.serialize_message(document), 'update': request.headers.get('X-Chat-Token')})

    def message(self, message_id: str):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        document = self._find_document(message_id)
        if not document:
            return _error('消息不存在', 404)
        conversation_id = _as_text(document.get('conversation_id')) or PUBLIC_CONVERSATION
        if not self._conversation_allowed(username, conversation_id):
            return _error('没有权限访问该消息', 403)
        if request.method == 'DELETE':
            self.hidden_messages.update_one(
                {'username': username, 'message_id': _message_id(document), 'conversation_id': conversation_id},
                {'$set': {'username': username, 'message_id': _message_id(document), 'conversation_id': conversation_id, 'created_at': _now()}},
                upsert=True,
            )
            return jsonify({'ok': True, 'id': _message_id(document), 'hidden': True})
        if document.get('user') != username and not self.state['is_admin'](username):
            return _error('只能编辑自己的消息', 403)
        if self.state['is_admin'](username) is False and _now() - _created_at(document) > EDIT_WINDOW_SECONDS:
            return _error('消息编辑时间已过', 403)
        payload = _json_payload()
        content = _as_text(payload.get('content'))
        if not content or len(content) > MAX_MESSAGE_LENGTH:
            return _error('消息内容无效', 400)
        self.edits.insert_one({'message_id': _message_id(document), 'editor': username, 'content': document.get('content', document.get('chat', '')), 'created_at': _now()})
        updated = {'content': content, 'chat': content, 'format': _as_text(payload.get('format')) or document.get('format') or 'markdown', 'edited': True, 'edited_at': _now()}
        self.database.update_one({'_id': document['_id']}, {'$set': updated})
        document.update(updated)
        self.publish_legacy_event('message.updated', document)
        return jsonify({'ok': True, 'message': self.serialize_message(document)})

    def message_recall(self, message_id: str):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        document = self._find_document(message_id)
        if not document:
            return _error('消息不存在', 404)
        if document.get('user') != username and not self.state['is_admin'](username):
            return _error('只能撤回自己的消息', 403)
        if not self.state['is_admin'](username) and _now() - _created_at(document) > RECALL_WINDOW_SECONDS:
            return _error('只能撤回两分钟内的消息', 403)
        self._delete_document(document)
        return jsonify({'ok': True, 'id': message_id, 'deleted': True})

    def _find_document(self, message_id: str) -> dict[str, Any] | None:
        document = self.database.find_one({'id': str(message_id)})
        if document:
            return document
        for index, candidate in enumerate(self.database.find().sort('_id', 1)):
            if _message_id(candidate, index) == str(message_id):
                return candidate
        return None

    def _delete_document(self, document: dict[str, Any]) -> None:
        message_id = _message_id(document)
        conversation_id = _as_text(document.get('conversation_id')) or PUBLIC_CONVERSATION
        self.database.delete_one({'_id': document['_id']})
        self.state['delete_legacy_attachment'](document)
        for attachment in document.get('attachments') or []:
            file_id = str(attachment.get('id') or '')
            if file_id:
                try:
                    still_referenced = self.database.count_documents({'attachments.id': file_id})
                except Exception:
                    still_referenced = 0
                if not still_referenced:
                    self.delete_file(file_id)
        self.event_hub.publish('message.deleted', {'id': message_id}, conversation_id=conversation_id, audience=self._conversation_users(conversation_id))

    def message_reactions(self, message_id: str):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        document = self._find_document(message_id)
        if not document:
            return _error('消息不存在', 404)
        conversation_id = _as_text(document.get('conversation_id')) or PUBLIC_CONVERSATION
        if not self._conversation_allowed(username, conversation_id):
            return _error('没有权限访问该消息', 403)
        emoji = _as_text(_json_payload().get('emoji')).strip()
        action = _as_text(_json_payload().get('action', 'add')).lower()
        if not emoji or len(emoji) > 16:
            return _error('Reaction 无效', 400)
        reactions = document.get('reactions') or {}
        users = set(reactions.get(emoji) or [])
        if action == 'remove':
            users.discard(username)
        else:
            users.add(username)
        if users:
            reactions[emoji] = sorted(users)
        else:
            reactions.pop(emoji, None)
        self.database.update_one({'_id': document['_id']}, {'$set': {'reactions': reactions}})
        payload = self.serialize_message({**document, 'reactions': reactions})
        self.event_hub.publish('reaction.updated', {'message': payload}, conversation_id=conversation_id, audience=self._conversation_users(conversation_id))
        return jsonify({'ok': True, 'message': payload})

    def _authorized_message(self, username: str, message_id: str) -> tuple[dict[str, Any] | None, str | None, Any | None]:
        document = self._find_document(message_id)
        if not document:
            return None, None, _error('消息不存在', 404)
        conversation_id = _as_text(document.get('conversation_id')) or PUBLIC_CONVERSATION
        if not self._conversation_allowed(username, conversation_id):
            return None, None, _error('没有权限访问该消息', 403)
        return document, conversation_id, None

    def message_bookmark(self, message_id: str):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        document, conversation_id, error = self._authorized_message(username, message_id)
        if error:
            return error
        identifier = _message_id(document)
        if request.method == 'DELETE':
            self.bookmarks.delete_one({'username': username, 'message_id': identifier})
            bookmarked = False
        else:
            self.bookmarks.update_one(
                {'username': username, 'message_id': identifier},
                {'$set': {'username': username, 'message_id': identifier, 'conversation_id': conversation_id, 'created_at': _now()}},
                upsert=True,
            )
            bookmarked = True
        message = self.serialize_message(document)
        message['bookmarked'] = bookmarked
        return jsonify({'ok': True, 'message': message, 'bookmarked': bookmarked})

    def bookmark_list(self):
        username, _, error = self.require_user()
        if error:
            return error
        try:
            limit = min(MAX_SEARCH_RESULTS, max(1, int(request.args.get('limit', 50))))
        except (TypeError, ValueError):
            limit = 50
        results = []
        for bookmark in self.bookmarks.find({'username': username}).sort('created_at', -1).limit(limit):
            document = self._find_document(str(bookmark.get('message_id')))
            if not document:
                continue
            conversation_id = _as_text(document.get('conversation_id')) or PUBLIC_CONVERSATION
            if self._conversation_allowed(username, conversation_id):
                results.append(self.serialize_message(document))
        return jsonify({'ok': True, 'bookmarks': results})

    def message_pin(self, message_id: str):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        document, conversation_id, error = self._authorized_message(username, message_id)
        if error:
            return error
        if self._conversation_blocked(username, conversation_id):
            return _error('该会话已被屏蔽', 403)
        identifier = _message_id(document)
        if request.method == 'DELETE':
            self.pins.delete_one({'conversation_id': conversation_id, 'message_id': identifier})
            pinned = False
        else:
            self.pins.update_one(
                {'conversation_id': conversation_id, 'message_id': identifier},
                {'$set': {'conversation_id': conversation_id, 'message_id': identifier, 'pinned_by': username, 'created_at': _now()}},
                upsert=True,
            )
            pinned = True
        message = self.serialize_message(document)
        message['pinned'] = pinned
        self.event_hub.publish('message.pinned', {'message': message, 'pinned': pinned}, conversation_id=conversation_id, audience=self._conversation_users(conversation_id))
        return jsonify({'ok': True, 'message': message, 'pinned': pinned})

    def conversation_pins(self, conversation_id: str):
        username, _, error = self.require_user()
        if error:
            return error
        if not self._conversation_allowed(username, conversation_id):
            return _error('没有权限访问该会话', 403)
        result = []
        for pin in self.pins.find({'conversation_id': conversation_id}).sort('created_at', -1):
            document = self._find_document(str(pin.get('message_id')))
            if document:
                result.append(self.serialize_message(document))
        return jsonify({'ok': True, 'conversation_id': conversation_id, 'pins': result})

    def message_report(self, message_id: str):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        document, conversation_id, error = self._authorized_message(username, message_id)
        if error:
            return error
        if document.get('user') == username:
            return _error('不能举报自己的消息', 400)
        reason = _as_text(_json_payload().get('reason')).strip()
        if not reason or len(reason) > 500:
            return _error('举报原因长度必须为 1-500 个字符', 400)
        identifier = _message_id(document)
        existing = self.reports.find_one({'message_id': identifier, 'reporter': username, 'status': 'open'})
        if existing:
            return _error('你已经举报过这条消息', 409)
        report = {
            'id': uuid.uuid4().hex,
            'message_id': identifier,
            'conversation_id': conversation_id,
            'reporter': username,
            'reported_user': _as_text(document.get('user')),
            'reason': reason,
            'status': 'open',
            'created_at': _now(),
        }
        self.reports.insert_one(report)
        self.event_hub.publish('report.created', {'report_id': report['id'], 'message_id': identifier}, audience={item['username'] for item in self._user_records() if self.state['is_admin'](item['username'])})
        report.pop('_id', None)
        return jsonify({'ok': True, 'report': report})

    def message_forward(self, message_id: str):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        source, source_conversation, error = self._authorized_message(username, message_id)
        if error:
            return error
        payload = _json_payload()
        targets = payload.get('conversation_ids')
        if not isinstance(targets, list):
            targets = [payload.get('conversation_id')]
        targets = list(dict.fromkeys(_as_text(item).strip() for item in targets if _as_text(item).strip()))
        if not targets or len(targets) > 20:
            return _error('至少选择一个、最多选择 20 个目标会话', 400)
        for target in targets:
            if not self._conversation_allowed(username, target):
                return _error('没有权限发送到目标会话', 403)
            if self._conversation_blocked(username, target):
                return _error('目标会话已被屏蔽', 403)
        now = _now()
        created: list[dict[str, Any]] = []
        original_id = _message_id(source)
        for target in targets:
            content = _as_text(source.get('content', source.get('chat', '')))
            document = {
                'id': uuid.uuid4().hex,
                'chat': content,
                'content': content,
                'user': username,
                'color': self.state['get_user_color'](username),
                'time': self.state['get_current_time'](),
                'created_at': now,
                'timestamp': now,
                'type': _as_text(source.get('type')) or self.state['infer_message_type'](content),
                'format': _as_text(source.get('format')) or 'markdown',
                'conversation_id': target,
                'recalled': False,
                'reply_to': None,
                'reactions': {},
                'edited': False,
                'attachments': list(source.get('attachments') or []),
                'forwarded_from': {'message_id': original_id, 'conversation_id': source_conversation, 'user': source.get('user')},
            }
            self.database.insert_one(document)
            self._notify_mentions(document)
            self.publish_legacy_event('message.created', document)
            created.append(self.serialize_message(document))
        return jsonify({'ok': True, 'messages': created})

    def typing(self, conversation_id: str):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        if not self._conversation_allowed(username, conversation_id):
            return _error('没有权限访问该会话', 403)
        self.event_hub.publish('typing', {'username': username, 'active': bool(_json_payload().get('active', True))}, conversation_id=conversation_id, audience=self._conversation_users(conversation_id), exclude=username)
        return jsonify({'ok': True})

    def read(self, conversation_id: str):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        if not self._conversation_allowed(username, conversation_id):
            return _error('没有权限访问该会话', 403)
        payload = _json_payload()
        now = _now()
        self.read_cursors.update_one(
            {'username': username, 'conversation_id': conversation_id},
            {'$set': {'username': username, 'conversation_id': conversation_id, 'message_id': _as_text(payload.get('message_id')), 'last_read_at': now}},
            upsert=True,
        )
        self.event_hub.publish('read', {'username': username, 'message_id': _as_text(payload.get('message_id')), 'at': now}, conversation_id=conversation_id, audience=self._conversation_users(conversation_id), exclude=username)
        return jsonify({'ok': True, 'conversation_id': conversation_id, 'last_read_at': now})

    def events(self):
        username, _, error = self.require_user()
        if error:
            return error
        return self._event_response(username)

    def bot_events(self):
        username, is_token, error = self.require_user()
        if error:
            return error
        if not is_token:
            return _error('机器人事件流需要 Bearer token', 403)
        return self._event_response(username)

    def _event_response(self, username: str):
        identifier, subscriber = self.event_hub.subscribe(username)
        last_event_id = request.headers.get('Last-Event-ID')

        def generate():
            if last_event_id:
                yield ': resumed\n\n'
            try:
                while True:
                    try:
                        event = subscriber.get(timeout=15)
                    except queue.Empty:
                        yield ': heartbeat\n\n'
                        continue
                    payload = json.dumps(event['data'], ensure_ascii=False, separators=(',', ':'))
                    yield 'id: %s\nevent: %s\ndata: %s\n\n' % (event['id'], event['type'], payload)
            finally:
                self.event_hub.unsubscribe(identifier)

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'},
        )

    def notification_list(self):
        username, _, error = self.require_user()
        if error:
            return error
        try:
            limit = min(100, max(1, int(request.args.get('limit', 50))))
        except (TypeError, ValueError):
            limit = 50
        items = []
        for item in self.notifications.find({'username': username}).sort('created_at', -1).limit(limit):
            item.pop('_id', None)
            items.append(item)
        return jsonify({'ok': True, 'notifications': items})

    def notifications_read(self):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        payload = _json_payload()
        query = {'username': username}
        if payload.get('id'):
            query['id'] = str(payload['id'])
        self.notifications.update_many(query, {'$set': {'read': True, 'read_at': _now()}})
        return jsonify({'ok': True})

    def emojis(self):
        username, _, error = self.require_user()
        if error:
            return error
        requested_user = _as_text(request.args.get('username')).strip() or username
        if requested_user != username and not self.state['is_admin'](username):
            return _error('没有权限查看该用户的 Emoji', 403)
        root = Path(self.state['base_dir']) / 'static' / 'emoji' / requested_user
        if not root.is_dir():
            return jsonify({'ok': True, 'emojis': []})
        items = [
            {'name': item.name, 'url': '/chat/emoji/static/%s/%s' % (quote(requested_user, safe=''), quote(item.name, safe=''))}
            for item in sorted(root.iterdir(), key=lambda value: value.name.lower())
            if item.is_file()
        ]
        return jsonify({'ok': True, 'username': requested_user, 'emojis': items})

    def _emoji_root(self, username: str) -> Path | None:
        if not username or Path(username).name != username or '/' in username or '\\' in username:
            return None
        root = (Path(self.state['base_dir']) / 'static' / 'emoji' / username).resolve()
        parent = (Path(self.state['base_dir']) / 'static' / 'emoji').resolve()
        return root if root.parent == parent else None

    def emoji_upload(self):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        uploaded = request.files.get('file')
        if not uploaded or not uploaded.filename:
            return _error('没有选择表情图片', 400)
        if uploaded.mimetype and not uploaded.mimetype.startswith('image/'):
            return _error('表情包必须是图片文件', 400)
        filename = secure_filename(uploaded.filename)
        root = self._emoji_root(username)
        if not filename or not root:
            return _error('文件名无效', 400)
        root.mkdir(parents=True, exist_ok=True)
        uploaded.save(root / filename)
        return jsonify({
            'ok': True,
            'emoji': {
                'name': filename,
                'url': '/chat/emoji/static/%s/%s' % (quote(username, safe=''), quote(filename, safe='')),
            },
        })

    def emoji_delete(self, filename: str):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        safe_filename = secure_filename(filename or '')
        if not safe_filename or safe_filename != filename or '/' in filename or '\\' in filename:
            return _error('文件名无效', 400)
        root = self._emoji_root(username)
        path = root / safe_filename if root else None
        if not path or not path.is_file():
            return _error('表情包不存在', 404)
        path.unlink()
        return jsonify({'ok': True, 'name': safe_filename})

    def _file_bytes(self, file_id: str) -> tuple[bytes, dict[str, Any]] | None:
        metadata = self.files.find_one({'file_id': file_id})
        if not metadata:
            memory = self._memory_files.get(file_id)
            return memory
        storage = metadata.get('storage')
        try:
            if storage == 'gridfs' and self._gridfs is not None and ObjectId is not None:
                stream = self._gridfs.get(ObjectId(file_id))
                return stream.read(), metadata
            if storage == 'disk':
                path = Path(metadata.get('path', '')).resolve()
                root = (Path(self.state['base_dir']) / 'static' / 'uploads').resolve()
                if root in path.parents and path.is_file():
                    return path.read_bytes(), metadata
        except Exception:
            return None
        return None

    def _store_file(self, data: bytes, filename: str, mime: str, owner: str | None = None) -> dict[str, Any]:
        safe_name = secure_filename(filename) or 'attachment'
        file_id = ''
        storage = 'disk'
        path = ''
        if self._gridfs is not None:
            try:
                file_id = str(self._gridfs.put(data, filename=safe_name, content_type=mime, uploaded_at=_now()))
                storage = 'gridfs'
            except Exception:
                file_id = ''
        if not file_id:
            file_id = uuid.uuid4().hex
            directory = Path(self.state['base_dir']) / 'static' / 'uploads'
            directory.mkdir(parents=True, exist_ok=True)
            path = str(directory / ('v2-' + file_id + '-' + safe_name))
            Path(path).write_bytes(data)
        metadata = {
            'file_id': file_id,
            'filename': safe_name,
            'mime': mime,
            'size': len(data),
            'owner': owner,
            'storage': storage,
            'path': path,
            'created_at': _now(),
        }
        self.files.insert_one(metadata)
        return {'id': file_id, 'name': safe_name, 'mime': mime, 'size': len(data), 'url': '/api/v2/uploads/' + file_id}

    def delete_file(self, file_id: str) -> None:
        if not file_id:
            return
        metadata = self.files.find_one({'file_id': file_id})
        if not metadata:
            return
        if metadata.get('storage') == 'gridfs' and self._gridfs is not None and ObjectId is not None:
            try:
                self._gridfs.delete(ObjectId(file_id))
            except Exception:
                pass
        elif metadata.get('storage') == 'disk':
            try:
                Path(metadata.get('path', '')).unlink(missing_ok=True)
            except OSError:
                pass
        self.files.delete_one({'_id': metadata['_id']})
        self._memory_files.pop(file_id, None)

    def uploads(self):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        try:
            self.state['ensure_not_muted'](username)
        except Exception as exc:
            return _error('您已被禁言', 403, muted_until=getattr(exc, 'muted_until', 0))
        uploaded = request.files.get('file')
        if not uploaded or not uploaded.filename:
            return _error('没有选择文件', 400)
        data = uploaded.read()
        if not data:
            return _error('文件为空', 400)
        extension = Path(uploaded.filename).suffix.lower().lstrip('.')
        limits = {'jpg': 20, 'jpeg': 20, 'png': 20, 'gif': 20, 'webp': 20, 'mp3': 50, 'wav': 50, 'ogg': 50, 'webm': 200, 'mp4': 200, 'zip': 100}
        limit = limits.get(extension, 100) * 1024 * 1024
        if len(data) > limit:
            return _error('文件超过类型大小限制', 413, max_bytes=limit)
        mime = uploaded.mimetype or mimetypes.guess_type(uploaded.filename)[0] or 'application/octet-stream'
        attachment = self._store_file(data, uploaded.filename, mime, owner=username)
        return jsonify({'ok': True, 'attachment': attachment})

    def _upload_limit(self, filename: str) -> int:
        extension = Path(filename).suffix.lower().lstrip('.')
        limits = {'jpg': 20, 'jpeg': 20, 'png': 20, 'gif': 20, 'webp': 20, 'mp3': 50, 'wav': 50, 'ogg': 50, 'webm': 200, 'mp4': 200, 'zip': 100}
        return min(MAX_UPLOAD_BYTES, limits.get(extension, 100) * 1024 * 1024)

    def _staging_path(self, upload_id: str) -> Path:
        root = (Path(self.state['base_dir']) / 'static' / 'uploads' / '.v2-staging').resolve()
        candidate = (root / (secure_filename(upload_id) + '.part')).resolve()
        if root not in candidate.parents:
            raise ValueError('上传会话无效')
        return candidate

    def upload_init(self):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        try:
            self.state['ensure_not_muted'](username)
        except Exception as exc:
            return _error('您已被禁言', 403, muted_until=getattr(exc, 'muted_until', 0))
        payload = _json_payload()
        filename = secure_filename(_as_text(payload.get('filename')).strip()) or 'attachment'
        try:
            size = int(payload.get('size', 0))
        except (TypeError, ValueError):
            size = 0
        if size <= 0:
            return _error('文件大小无效', 400)
        limit = self._upload_limit(filename)
        if size > limit:
            return _error('文件超过类型大小限制', 413, max_bytes=limit)
        upload_id = uuid.uuid4().hex
        path = self._staging_path(upload_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'')
        chunk_size = 1024 * 1024
        record = {
            'upload_id': upload_id,
            'owner': username,
            'filename': filename,
            'mime': _as_text(payload.get('mime')) or mimetypes.guess_type(filename)[0] or 'application/octet-stream',
            'size': size,
            'chunk_size': chunk_size,
            'received': 0,
            'chunks': [],
            'path': str(path),
            'status': 'open',
            'created_at': _now(),
            'updated_at': _now(),
        }
        self.upload_sessions.insert_one(record)
        return jsonify({'ok': True, 'upload_id': upload_id, 'chunk_size': chunk_size, 'size': size, 'received': 0})

    def upload_chunk(self, upload_id: str, chunk_index: int):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        record = self.upload_sessions.find_one({'upload_id': upload_id, 'owner': username, 'status': 'open'})
        if not record:
            return _error('上传会话不存在或已结束', 404)
        data = request.get_data(cache=False)
        if not data:
            return _error('上传分片为空', 400)
        try:
            offset = int(request.headers.get('X-Chunk-Offset', chunk_index * int(record.get('chunk_size', 1024 * 1024))))
        except (TypeError, ValueError):
            return _error('分片偏移无效', 400)
        if offset < 0 or offset + len(data) > int(record['size']):
            return _error('分片超出文件范围', 416)
        path = self._staging_path(upload_id)
        chunks = [item for item in (record.get('chunks') or []) if int(item.get('index', -1)) != chunk_index]
        with self._file_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = 'r+b' if path.exists() else 'wb'
            with path.open(mode) as stream:
                stream.seek(offset)
                stream.write(data)
        chunks.append({'index': chunk_index, 'offset': offset, 'size': len(data)})
        intervals = sorted((int(item['offset']), int(item['offset']) + int(item['size'])) for item in chunks)
        merged: list[list[int]] = []
        for start, end in intervals:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        received = sum(end - start for start, end in merged)
        self.upload_sessions.update_one({'_id': record['_id']}, {'$set': {'chunks': chunks, 'received': received, 'updated_at': _now()}})
        return jsonify({'ok': True, 'upload_id': upload_id, 'chunk_index': chunk_index, 'received': received, 'size': record['size'], 'complete': received == int(record['size'])})

    def upload_complete(self, upload_id: str):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        record = self.upload_sessions.find_one({'upload_id': upload_id, 'owner': username, 'status': 'open'})
        if not record:
            return _error('上传会话不存在或已结束', 404)
        if int(record.get('received', 0)) != int(record.get('size', 0)):
            return _error('文件仍未上传完整', 409, received=record.get('received', 0), size=record.get('size', 0))
        path = self._staging_path(upload_id)
        if not path.is_file() or path.stat().st_size != int(record['size']):
            return _error('上传文件校验失败', 409)
        with self._file_lock:
            data = path.read_bytes()
        attachment = self._store_file(data, record['filename'], record['mime'], owner=username)
        self.upload_sessions.update_one({'_id': record['_id']}, {'$set': {'status': 'completed', 'updated_at': _now(), 'file_id': attachment['id']}})
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return jsonify({'ok': True, 'attachment': attachment})

    def upload_session(self, upload_id: str):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        record = self.upload_sessions.find_one({'upload_id': upload_id, 'owner': username, 'status': 'open'})
        if not record:
            return _error('上传会话不存在或已结束', 404)
        path = self._staging_path(upload_id)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        self.upload_sessions.update_one({'_id': record['_id']}, {'$set': {'status': 'cancelled', 'updated_at': _now()}})
        return jsonify({'ok': True, 'upload_id': upload_id, 'status': 'cancelled'})

    def upload_file(self, file_id: str):
        username, _, error = self.require_user()
        if error:
            return error
        if not self._file_accessible(username, file_id):
            return _error('没有权限访问该文件', 403)
        result = self._file_bytes(file_id)
        if not result:
            return _error('文件不存在', 404)
        data, metadata = result
        return send_file(io.BytesIO(data), mimetype=metadata.get('mime'), download_name=metadata.get('filename'), max_age=3600)

    def file_preview(self, file_id: str):
        username, _, error = self.require_user()
        if error:
            return error
        if not self._file_accessible(username, file_id):
            return _error('没有权限访问该文件', 403)
        result = self._file_bytes(file_id)
        if not result:
            return _error('文件不存在', 404)
        data, metadata = result
        if len(data) > MAX_PREVIEW_BYTES:
            return _error('文件超过预览大小限制', 413)
        filename = metadata.get('filename', '')
        if filename.lower().endswith('.zip'):
            entries = []
            total = 0
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    for index, info in enumerate(archive.infolist()):
                        if index >= MAX_ZIP_ENTRIES:
                            return _error('ZIP 条目过多', 413)
                        total += max(0, int(info.file_size))
                        if total > MAX_ZIP_METADATA_BYTES:
                            return _error('ZIP 目录超过限制', 413)
                        entries.append({'name': info.filename, 'size': info.file_size, 'compressed_size': info.compress_size, 'modified': info.date_time})
            except zipfile.BadZipFile:
                return _error('ZIP 文件无效', 400)
            return jsonify({'ok': True, 'filename': filename, 'kind': 'zip', 'entries': entries})
        content, encoding, candidates = _decode_text_candidates(data)
        return jsonify({'ok': True, 'filename': filename, 'kind': 'text', 'encoding': encoding, 'content': content, 'candidates': candidates})

    def legacy_file_preview(self):
        username, _, error = self.require_user()
        if error:
            return error
        filename = _as_text(request.args.get('filename')).strip()
        if not filename or filename in {'.', '..'} or Path(filename).name != filename or '/' in filename or '\\' in filename:
            return _error('文件名无效', 400)
        root = (Path(self.state['base_dir']) / 'static' / 'uploads').resolve()
        path = (root / filename).resolve()
        data: bytes | None = None
        metadata: dict[str, Any] = {'filename': filename, 'mime': mimetypes.guess_type(filename)[0] or 'text/plain'}
        if root in path.parents and path.is_file():
            if not self._legacy_file_is_referenced(username, filename):
                return _error('没有权限访问该文件', 403)
            data = path.read_bytes()
        else:
            result = self.find_legacy_file(filename)
            if result:
                data, mime, download_name = result
                metadata = {'filename': download_name or filename, 'mime': mime or metadata['mime']}
            else:
                return _error('文件不存在', 404)
        if len(data) > MAX_PREVIEW_BYTES:
            return _error('文件超过预览大小限制', 413)
        content, encoding, candidates = _decode_text_candidates(data)
        return jsonify({'ok': True, 'filename': metadata['filename'], 'kind': 'text', 'encoding': encoding, 'content': content, 'candidates': candidates})

    def _legacy_file_is_referenced(self, username: str, filename: str) -> bool:
        if self.state['is_admin'](username):
            return True
        for document in self.database.find():
            conversation_id = _as_text(document.get('conversation_id')) or PUBLIC_CONVERSATION
            if _as_text(document.get('user')) == username or self._conversation_allowed(username, conversation_id):
                content = _as_text(document.get('content', document.get('chat', '')))
                if content.startswith(('::img::', '::wav::', '::file::')) and Path(content.split('::', 2)[-1].strip()).name == filename:
                    return True
                for attachment in document.get('attachments') or []:
                    if isinstance(attachment, dict) and (_as_text(attachment.get('name')) == filename or _as_text(attachment.get('url')).endswith('/' + quote(filename, safe=''))):
                        return True
        return False

    def _file_accessible(self, username: str, file_id: str) -> bool:
        metadata = self.files.find_one({'file_id': file_id})
        if not metadata:
            return False
        if metadata.get('owner') == username or self.state['is_admin'](username):
            return True
        for document in self.database.find({'attachments.id': file_id}):
            conversation_id = _as_text(document.get('conversation_id')) or PUBLIC_CONVERSATION
            if self._conversation_allowed(username, conversation_id):
                return True
        return False

    def find_legacy_file(self, filename: str):
        safe_name = secure_filename(os.path.basename(filename or ''))
        if not safe_name:
            return None
        metadata = self.files.find_one({'filename': safe_name}, sort=[('created_at', -1)])
        if not metadata:
            return None
        result = self._file_bytes(str(metadata.get('file_id')))
        if not result:
            return None
        data, info = result
        return data, info.get('mime') or 'application/octet-stream', info.get('filename') or safe_name

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    def bot_token(self):
        username, is_token, error = self.require_user(csrf=True)
        if error:
            return error
        if request.method == 'DELETE':
            self.bot_tokens.update_many({'username': username, 'active': True}, {'$set': {'active': False, 'revoked_at': _now()}})
            return jsonify({'ok': True, 'revoked': True})
        payload = _json_payload()
        active = self.bot_tokens.find_one({'username': username, 'active': True})
        if active and not bool(payload.get('replace')):
            return _error('每个用户只能有一个有效 token', 409)
        if active:
            self.bot_tokens.update_one({'_id': active['_id']}, {'$set': {'active': False, 'revoked_at': _now()}})
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        record = {'username': username, 'token_hash': self._hash_token(token), 'prefix': token[:12], 'active': True, 'scopes': ['messages:read', 'messages:write', 'attachments:read', 'attachments:write'], 'created_at': _now(), 'expires_at': float(payload.get('expires_at') or 0)}
        self.bot_tokens.insert_one(record)
        return jsonify({'ok': True, 'token': token, 'created_at': record['created_at'], 'scopes': record['scopes'], 'warning': 'token 只在本次响应显示，请立即保存'})

    def bot_messages(self):
        username, is_token, error = self.require_user()
        if error:
            return error
        if not is_token:
            return _error('机器人接口需要 Bearer token', 403)
        if request.method == 'GET':
            conversation_id = _as_text(request.args.get('conversation_id')) or PUBLIC_CONVERSATION
            if not self._conversation_allowed(username, conversation_id):
                return _error('没有权限访问该会话', 403)
            return self.messages(conversation_id)
        payload = _json_payload()
        conversation_id = _as_text(payload.get('conversation_id')) or PUBLIC_CONVERSATION
        return self.create_message(username, conversation_id, payload, is_token=True)

    def bot_stream_start(self):
        username, is_token, error = self.require_user()
        if error:
            return error
        if not is_token:
            return _error('机器人流式接口需要 Bearer token', 403)
        payload = _json_payload()
        conversation_id = _as_text(payload.get('conversation_id')) or PUBLIC_CONVERSATION
        if not self._conversation_allowed(username, conversation_id):
            return _error('没有权限访问该会话', 403)
        stream_id = uuid.uuid4().hex
        self.streams.insert_one({'stream_id': stream_id, 'owner': username, 'conversation_id': conversation_id, 'format': _as_text(payload.get('format')) or 'markdown', 'content': '', 'status': 'open', 'created_at': _now(), 'updated_at': _now()})
        self.event_hub.publish('stream.started', {'stream_id': stream_id}, conversation_id=conversation_id, audience=self._conversation_users(conversation_id))
        return jsonify({'ok': True, 'stream_id': stream_id, 'status': 'open'})

    def bot_stream(self, stream_id: str):
        username, is_token, error = self.require_user()
        if error:
            return error
        if not is_token:
            return _error('机器人流式接口需要 Bearer token', 403)
        stream = self.streams.find_one({'stream_id': stream_id, 'owner': username, 'status': 'open'})
        if not stream:
            return _error('流不存在或已结束', 404)
        if request.method == 'DELETE':
            self.streams.update_one({'_id': stream['_id']}, {'$set': {'status': 'cancelled', 'updated_at': _now()}})
            self.event_hub.publish('stream.cancelled', {'stream_id': stream_id}, conversation_id=stream['conversation_id'], audience=self._conversation_users(stream['conversation_id']))
            return jsonify({'ok': True, 'stream_id': stream_id, 'status': 'cancelled'})
        payload = _json_payload()
        if request.method == 'PATCH' or payload.get('complete'):
            content = _as_text(payload.get('content')) or _as_text(stream.get('content'))
            if not content:
                return _error('流内容不能为空', 400)
            self.streams.update_one({'_id': stream['_id']}, {'$set': {'content': content, 'status': 'completed', 'updated_at': _now()}})
            result = self.create_message(username, stream['conversation_id'], {'content': content, 'format': stream.get('format', 'markdown')}, is_token=True)
            self.event_hub.publish('stream.completed', {'stream_id': stream_id}, conversation_id=stream['conversation_id'], audience=self._conversation_users(stream['conversation_id']))
            return result
        delta = _as_text(payload.get('delta'))
        if not delta:
            return _error('delta 不能为空', 400)
        content = _as_text(stream.get('content')) + delta
        self.streams.update_one({'_id': stream['_id']}, {'$set': {'content': content, 'updated_at': _now()}})
        self.event_hub.publish('stream.delta', {'stream_id': stream_id, 'delta': delta}, conversation_id=stream['conversation_id'], audience=self._conversation_users(stream['conversation_id']))
        return jsonify({'ok': True, 'stream_id': stream_id, 'length': len(content)})

    def _notify_mentions(self, document: dict[str, Any]) -> None:
        content = _as_text(document.get('content', document.get('chat', '')))
        known = {item['username'] for item in self._user_records()}
        mentioned = {content[index + 1:].split()[0].strip(',.!?;:') for index, char in enumerate(content[:-1]) if char == '@'}
        mentioned &= known
        conversation_id = _as_text(document.get('conversation_id')) or PUBLIC_CONVERSATION
        for target in mentioned:
            if target == document.get('user'):
                continue
            if self._is_blocked(target, _as_text(document.get('user'))) or self._is_blocked(_as_text(document.get('user')), target):
                continue
            item = {'id': uuid.uuid4().hex, 'username': target, 'kind': 'mention', 'message_id': _message_id(document), 'conversation_id': conversation_id, 'actor': document.get('user'), 'created_at': _now(), 'read': False}
            self.notifications.insert_one(item)
            item.pop('_id', None)
            self.event_hub.publish('notification', item, conversation_id=conversation_id, audience={target})

    def publish_legacy_event(self, event_type: str, document: dict[str, Any]) -> None:
        conversation_id = _as_text(document.get('conversation_id')) or PUBLIC_CONVERSATION
        if event_type == 'message.deleted':
            data = {'id': _message_id(document)}
        else:
            data = {'message': self.serialize_message(document)}
        self.event_hub.publish(event_type, data, conversation_id=conversation_id, audience=self._conversation_users(conversation_id))

    def _require_admin(self, *, csrf: bool = False) -> tuple[str | None, Any | None]:
        username, _, error = self.require_user(csrf=csrf)
        if error:
            return None, error
        if not self.state['is_admin'](username):
            return None, _error('没有管理权限', 403)
        return username, None

    def admin_reports(self):
        username, error = self._require_admin(csrf=request.method == 'PATCH')
        if error:
            return error
        if request.method == 'PATCH':
            payload = _json_payload()
            report_id = _as_text(payload.get('id')).strip()
            status = _as_text(payload.get('status')).strip().lower()
            if not report_id or status not in {'open', 'reviewing', 'resolved', 'dismissed'}:
                return _error('举报状态无效', 400)
            result = self.reports.update_one({'id': report_id}, {'$set': {'status': status, 'reviewed_by': username, 'reviewed_at': _now()}})
            if not result.matched_count:
                return _error('举报不存在', 404)
            return jsonify({'ok': True, 'id': report_id, 'status': status})
        try:
            limit = min(100, max(1, int(request.args.get('limit', 50))))
        except (TypeError, ValueError):
            limit = 50
        status = _as_text(request.args.get('status')).strip()
        query = {'status': status} if status else {}
        reports = []
        for item in self.reports.find(query).sort('created_at', -1).limit(limit):
            item.pop('_id', None)
            reports.append(item)
        return jsonify({'ok': True, 'reports': reports})

    def admin_users(self):
        username, error = self._require_admin()
        if error:
            return error
        mute_collection = self.state.get('mutes')
        users = []
        for item in self._user_records():
            target = item['username']
            mute = mute_collection.find_one({'username': target}) if mute_collection is not None else None
            users.append({
                **self.serialize_user(target),
                'muted_until': float(mute.get('muted_until', 0)) if mute else 0,
                'muted_by': mute.get('muted_by') if mute else None,
            })
        return jsonify({'ok': True, 'users': users})

    def admin_mute(self, target_username: str):
        actor, error = self._require_admin(csrf=True)
        if error:
            return error
        target_username = _as_text(target_username).strip()
        if not self._user_exists(target_username):
            return _error('用户不存在', 404)
        if self.state['is_admin'](target_username):
            return _error('管理员不能被禁言', 403)
        mute_collection = self.state.get('mutes')
        if mute_collection is None:
            return _error('禁言存储未配置', 503)
        if request.method == 'DELETE':
            mute_collection.delete_many({'username': target_username})
            return jsonify({'ok': True, 'username': target_username, 'muted_until': 0})
        payload = _json_payload()
        try:
            duration = int(payload.get('duration', 60))
        except (TypeError, ValueError):
            duration = 60
        if duration < 1 or duration > 86400:
            return _error('禁言时长必须为 1-86400 秒', 400)
        muted_until = _now() + duration
        mute_collection.update_one(
            {'username': target_username},
            {'$set': {'username': target_username, 'muted_until': muted_until, 'muted_by': actor, 'created_at': _now()}},
            upsert=True,
        )
        return jsonify({'ok': True, 'username': target_username, 'muted_until': muted_until})

    def admin_audit(self):
        username, error = self._require_admin()
        if error:
            return error
        try:
            limit = min(100, max(1, int(request.args.get('limit', 50))))
        except (TypeError, ValueError):
            limit = 50
        records = []
        for item in self.audit.find().sort('created_at', -1).limit(limit):
            item.pop('_id', None)
            records.append(item)
        return jsonify({'ok': True, 'audit': records})

    def admin_purge(self):
        username, _, error = self.require_user(csrf=True)
        if error:
            return error
        if not self.state['is_admin'](username):
            return _error('没有管理权限', 403)
        payload = _json_payload()
        query: dict[str, Any] = {}
        if payload.get('conversation_id'):
            conversation_id = str(payload['conversation_id'])
            query['$or'] = [{'conversation_id': conversation_id}]
            if conversation_id == PUBLIC_CONVERSATION:
                query['$or'].append({'conversation_id': {'$exists': False}})
        if payload.get('user'):
            query['user'] = str(payload['user'])
        if payload.get('message_id'):
            document = self._find_document(str(payload['message_id']))
            if not document:
                return _error('消息不存在', 404)
            query['_id'] = document['_id']
        if not query:
            return _error('必须提供删除范围', 400)
        documents = list(self.database.find(query))
        dry_run = payload.get('dry_run', True)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() not in {'0', 'false', 'no'}
        if dry_run:
            return jsonify({'ok': True, 'dry_run': True, 'count': len(documents), 'ids': [_message_id(item) for item in documents]})
        for document in documents:
            self._delete_document(document)
        self.audit.insert_one({'actor': username, 'action': 'purge', 'query': query, 'count': len(documents), 'created_at': _now()})
        return jsonify({'ok': True, 'deleted': len(documents)})


def register_v2_api(app, state: dict[str, Any]) -> V2Service:
    return V2Service(app, state)
