from flask import Flask, jsonify, redirect, render_template, request, send_from_directory
import logging
import os
import random
import time
import uuid
import json
from datetime import datetime

from pymongo import MongoClient
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

def load_config():
    """从 config.json 加载配置，若不存在则返回默认空配置"""
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_config(config):
    """保存配置到 config.json"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

# 加载配置
config = load_config()
server_ip = config.get('server_ip', '')
database_ip = config.get('db_ip', '127.0.0.1')
database_port = config.get('db_port', '27017')
database_user = config.get('db_user', '')
database_password = config.get('db_pass', '')
admins = config.get('admins', ['admin'])   # 管理员用户名列表

def read_lines(filename):
    try:
        with open(os.path.join(BASE_DIR, filename), 'r', encoding='utf-8') as stream:
            return [line.strip() for line in stream.read().splitlines()]
    except FileNotFoundError:
        return []


usernames = read_lines('usernames.list')
passwords = read_lines('passwords.list')
user_colors = read_lines('colors.list')

if database_user or database_password:
    mongo_uri = 'mongodb://' + database_user + ':' + database_password + '@' + database_ip + ':' + database_port
else:
    mongo_uri = 'mongodb://' + database_ip + ':' + database_port

app = Flask(__name__)

logger = logging.getLogger('syh-chatter')
logger.setLevel(logging.INFO)
if not logger.handlers:
    file_handler = logging.FileHandler(os.path.join(BASE_DIR, 'log.txt'))
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)


def create_database_client():
    mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
    try:
        mongo_client.admin.command('ping')
        return mongo_client
    except Exception as exc:
        logger.warning('MongoDB unavailable at %s: %s', mongo_uri, exc)
        try:
            import mongomock
        except ImportError:
            logger.error('mongomock is not installed; database requests will fail until MongoDB starts')
            return mongo_client
        logger.warning('Using in-memory mongomock fallback; messages will not persist across restarts')
        return mongomock.MongoClient()


client = create_database_client()
db = client['chats']
database = db['values']
mutes = db['mutes']

for filename in ('login_users.txt', 'login_passes.txt'):
    open(os.path.join(BASE_DIR, filename), 'a', encoding='utf-8').close()

ip = server_ip
loginings = []

IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'bmp', 'gif', 'webp', 'svg', 'ico'}
AUDIO_EXTENSIONS = {'mp3', 'wav', 'flac', 'ogg', 'm4a'}
CPP_PREVIEW_LIMIT = 1024 * 1024
MUTE_MIN_SECONDS = 1
MUTE_MAX_SECONDS = 86400


class MuteError(Exception):
    def __init__(self, muted_until):
        self.muted_until = muted_until
        super().__init__('您已被禁言')


def get_current_time():
    return time.strftime('%Y:%m:%d:%H:%M', time.localtime())


def is_admin(username):
    """检查用户名是否在管理员列表中（从 config.json 读取）"""
    return username in admins


def get_user_color(username):
    try:
        index = usernames.index(username)
    except ValueError:
        return '#808080'
    return user_colors[index] if index < len(user_colors) and user_colors[index] else '#808080'


def _session_paths():
    return (os.path.join(BASE_DIR, 'login_users.txt'), os.path.join(BASE_DIR, 'login_passes.txt'))


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
    return request.args.get('update') or payload.get('update') or request.headers.get('X-Chat-Token')


def authenticate_request():
    # The token is authoritative. Request-body usernames are retained for
    # legacy clients but must never choose the acting user.
    return authenticate_token(request_token())


def json_error(message, status=400, **extra):
    body = {'ok': False, 'error': message}
    body.update(extra)
    return jsonify(body), status


def touch_presence(username):
    now = time.time()
    loginings[:] = [entry for entry in loginings if now - entry['time'] <= 10]
    for entry in loginings:
        if entry['username'] == username:
            entry['time'] = now
            return
    loginings.append({'username': username, 'time': now})


def get_mute_record(username):
    record = mutes.find_one({'username': username})
    if not record:
        return None
    muted_until = float(record.get('muted_until', 0) or 0)
    if muted_until <= time.time():
        try:
            mutes.delete_one({'_id': record['_id']})
        except (KeyError, TypeError):
            mutes.delete_one({'username': username})
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


def infer_message_type(content, stored_type=None, user=None):
    content = '' if content is None else str(content)
    # Content markers repair legacy records that were stored with type="text".
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
        'color': doc.get('color') or get_user_color(user),
        'time': message_time,
        'timestamp': created_at,
        'content': content,
        'type': infer_message_type(content, doc.get('type'), user),
        'recalled': bool(doc.get('recalled', doc.get('revoked', False))),
        'reply_to': str(doc['reply_to']) if doc.get('reply_to') else None,
    }


def iter_message_docs():
    return database.find().sort('_id', 1)


def get_messages():
    messages = []
    for index, doc in enumerate(iter_message_docs()):
        if not doc.get('user'):
            continue
        messages.append(serialize_message(doc, index))
    return messages


def get_data():
    """Legacy four-list accessor retained for old integrations."""
    messages = get_messages()
    return [
        [message['content'] for message in messages],
        [message['user'] for message in messages],
        [message['color'] for message in messages],
        [message['time'] for message in messages],
    ]


def find_message(message_id):
    message_id = str(message_id or '')
    doc = database.find_one({'id': message_id})
    if doc:
        return doc
    for index, candidate in enumerate(iter_message_docs()):
        if legacy_message_id(candidate, index) == message_id:
            return candidate
    return None


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
    database.insert_one(document)
    return serialize_message(document)


def add_chat(username, value, d_time=None, reply_to=None, message_type=None, check_mute=True):
    if check_mute:
        ensure_not_muted(username)
    value = '' if value is None else str(value)
    d_time = d_time or get_current_time()
    logger.info('用户：%s 上传了信息：%s', username, value)

    if is_admin(username) and value.startswith('command: '):
        return admin_command(username, value, d_time)

    if reply_to and not find_message(reply_to):
        reply_to = None

    document = {
        'id': uuid.uuid4().hex,
        'chat': value,
        'content': value,
        'user': username,
        'color': get_user_color(username),
        'time': d_time,
        'created_at': time.time(),
        'type': message_type or infer_message_type(value),
        'recalled': False,
        'reply_to': str(reply_to) if reply_to else None,
    }
    database.insert_one(document)
    return serialize_message(document)


def admin_command(username, command_str, d_time):
    parts = command_str[9:].split()
    if not parts:
        return add_chat(username, command_str, d_time, check_mute=False)
    command = parts[0]

    if command == 'clear':
        database.delete_many({})
        return add_system_message('管理员清除了聊天记录')

    if command == 'change_color' and len(parts) >= 3:
        target_user, new_color = parts[1], parts[2]
        if target_user in usernames:
            index = usernames.index(target_user)
            while len(user_colors) <= index:
                user_colors.append('#808080')
            user_colors[index] = new_color
            with open(os.path.join(BASE_DIR, 'colors.list'), 'w', encoding='utf-8') as stream:
                stream.write('\n'.join(user_colors) + '\n')
            logger.info('管理员将用户 %s 的颜色改为 %s', target_user, new_color)
            return add_system_message('管理员已更新 %s 的头像颜色' % target_user)

    if command == 'delete' and len(parts) >= 2:
        try:
            count = int(parts[1])
        except ValueError:
            count = 0
        if count > 0:
            docs = list(iter_message_docs())
            ids = [doc['_id'] for doc in docs[-count:] if '_id' in doc]
            if ids:
                database.delete_many({'_id': {'$in': ids}})
            return add_system_message('管理员删除了最后 %s 条消息' % count)

    document = {
        'id': uuid.uuid4().hex,
        'chat': command_str,
        'content': command_str,
        'user': username,
        'color': get_user_color(username),
        'time': d_time,
        'created_at': time.time(),
        'type': 'text',
        'recalled': False,
        'reply_to': None,
    }
    database.insert_one(document)
    return serialize_message(document)


def _save_login(username):
    sessions = load_sessions()
    token = str(random.randint(1000000000, 9999999999))
    sessions[username] = token
    save_sessions(sessions)
    touch_presence(username)
    return token


def _remove_login(username):
    sessions = load_sessions()
    sessions.pop(username, None)
    save_sessions(sessions)


def _safe_upload_path(filename):
    safe_name = secure_filename(os.path.basename(filename or ''))
    if not safe_name or safe_name in {'.', '..'}:
        return None, None
    upload_dir = os.path.join(BASE_DIR, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir, safe_name


def _attachment_filename(message):
    content = message.get('content', message.get('chat', ''))
    for prefix in ('::img::', '::wav::', '::file::'):
        if str(content).startswith(prefix):
            return str(content)[len(prefix):].strip()
    return None


def _delete_attachment(message):
    filename = _attachment_filename(message)
    if not filename:
        return
    upload_dir = os.path.join(BASE_DIR, 'static', 'uploads')
    path = os.path.abspath(os.path.join(upload_dir, os.path.basename(filename)))
    if os.path.dirname(path) != os.path.abspath(upload_dir):
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _decode_cpp(raw_bytes):
    try:
        from charset_normalizer import from_bytes
        match = from_bytes(raw_bytes).best()
        if match is not None:
            detected = (match.encoding or '').lower()
            decoded = str(match)
            # Short GB2312 samples are often indistinguishable from Big5 to an
            # automated detector. GB18030 is a compatible superset and keeps
            # the common mainland C++ source case readable.
            if detected in {'big5', 'cp950', 'gbk', 'gb2312', 'gb18030'}:
                try:
                    mainland_text = raw_bytes.decode('gb18030')
                    if any('\u4e00' <= char <= '\u9fff' for char in mainland_text):
                        return mainland_text, 'gb18030'
                except UnicodeDecodeError:
                    pass
            return decoded, (match.encoding or 'unknown')
    except Exception as exc:  # pragma: no cover - dependency/runtime fallback
        logger.warning('charset-normalizer failed: %s', exc)
    return raw_bytes.decode('utf-8', errors='replace'), 'utf-8'


def _cpp_path(filename):
    safe = secure_filename(os.path.basename(filename or ''))
    if not safe or not safe.lower().endswith('.cpp'):
        return None
    upload_dir = os.path.abspath(os.path.join(BASE_DIR, 'static', 'uploads'))
    path = os.path.abspath(os.path.join(upload_dir, safe))
    return path if os.path.dirname(path) == upload_dir else None

@app.route('/init', methods=['GET', 'POST'])
def init_page():
    global database_ip, database_port, database_user, database_password, server_ip, admins
    global usernames, passwords, user_colors, client, db, database, mutes
    # 如果已经初始化过（有 config.json 且至少有一个用户），则禁止再次访问
    if os.path.exists(CONFIG_FILE) and os.path.exists(os.path.join(BASE_DIR, 'usernames.list')):
        with open(os.path.join(BASE_DIR, 'usernames.list'), 'r', encoding='utf-8') as f:
            if f.read().strip():
                return redirect('/')

    if request.method == 'GET':
        cfg = load_config()
        return render_template('init.html',
                               db_ip=cfg.get('db_ip', '127.0.0.1'),
                               db_port=cfg.get('db_port', '27017'),
                               db_user=cfg.get('db_user', ''),
                               db_pass=cfg.get('db_pass', ''),
                               server_ip=cfg.get('server_ip', ''),
                               admin_user='admin',
                               error=None)

    # POST 处理
    db_ip = request.form.get('db_ip', '').strip()
    db_port = request.form.get('db_port', '').strip()
    db_user = request.form.get('db_user', '').strip()
    db_pass = request.form.get('db_pass', '').strip()
    new_server_ip = request.form.get('server_ip', '').strip()   # 从表单获取服务器 IP
    admin_user = request.form.get('admin_user', '').strip()
    admin_pass = request.form.get('admin_pass', '').strip()
    admin_pass_confirm = request.form.get('admin_pass_confirm', '').strip()
    invite_count = request.form.get('invite_count', '5').strip()

    # 基本验证
    if not db_ip or not db_port or not admin_user or not admin_pass:
        return render_template('init.html', error='所有必填字段不能为空',
                               db_ip=db_ip, db_port=db_port, db_user=db_user, db_pass=db_pass,
                               server_ip=server_ip, admin_user=admin_user, invite_count=invite_count)
    if admin_pass != admin_pass_confirm:
        return render_template('init.html', error='管理员密码不一致',
                               db_ip=db_ip, db_port=db_port, db_user=db_user, db_pass=db_pass,
                               server_ip=server_ip, admin_user=admin_user, invite_count=invite_count)
    try:
        invite_count = int(invite_count)
        if invite_count < 1:
            invite_count = 1
    except ValueError:
        invite_count = 5

    # 将配置写入全局变量（供后续连接使用）
    database_ip = db_ip
    database_port = db_port
    database_user = db_user
    database_password = db_pass
    server_ip = new_server_ip
    admins = [admin_user]   # 初始化管理员列表

    # 保存配置（包含管理员列表）
    new_config = {
        'db_ip': db_ip,
        'db_port': db_port,
        'db_user': db_user,
        'db_pass': db_pass,
        'server_ip': server_ip,
        'admins': admins,   # 存储管理员用户名列表
    }
    save_config(new_config)

    # 创建管理员用户
    usernames_path = os.path.join(BASE_DIR, 'usernames.list')
    passwords_path = os.path.join(BASE_DIR, 'passwords.list')
    colors_path = os.path.join(BASE_DIR, 'colors.list')

    existing_users = read_lines('usernames.list')
    if admin_user in existing_users:
        return render_template('init.html', error='管理员用户名已存在，请更换',
                               db_ip=db_ip, db_port=db_port, db_user=db_user, db_pass=db_pass,
                               server_ip=server_ip, admin_user=admin_user, invite_count=invite_count)

    hashed = generate_password_hash(admin_pass)
    with open(usernames_path, 'a', encoding='utf-8') as f:
        f.write(admin_user + '\n')
    with open(passwords_path, 'a', encoding='utf-8') as f:
        f.write(hashed + '\n')
    with open(colors_path, 'a', encoding='utf-8') as f:
        f.write('#ffffff\n')  # 默认白色

    # 生成邀请码
    invite_path = os.path.join(BASE_DIR, 'invite_code.txt')
    import random, string
    existing_codes = set(read_lines('invite_code.txt'))
    for _ in range(invite_count):
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        existing_codes.add(code)
    with open(invite_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(existing_codes)) + '\n')

    # 更新全局用户列表
    usernames = read_lines('usernames.list')
    passwords = read_lines('passwords.list')
    user_colors = read_lines('colors.list')

    # 重新连接数据库（使用新配置）
    client = create_database_client()
    db = client['chats']
    database = db['values']
    mutes = db['mutes']

    # 插入一条系统消息（可选）
    add_system_message('系统初始化完成，管理员 %s 已创建' % admin_user)

    logger.info('系统初始化完成，管理员：%s', admin_user)

    # 读取所有邀请码用于展示
    generated_codes = read_lines('invite_code.txt')

    # 渲染完成页面（传递邀请码列表和管理员名、数据库IP、服务器IP）
    return render_template('init_complete.html',
                           admin_user=admin_user,
                           invite_codes=generated_codes,
                           db_ip=database_ip,
                           server_ip=server_ip)

@app.route('/init/ping', methods=['POST'])
def init_ping():
    """测试数据库连接（用于初始化页面）"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '缺少请求数据'}), 400

    db_ip = data.get('db_ip', '').strip()
    db_port = data.get('db_port', '').strip()
    db_user = data.get('db_user', '').strip()
    db_pass = data.get('db_pass', '').strip()

    if not db_ip or not db_port:
        return jsonify({'success': False, 'message': '数据库IP和端口不能为空'}), 400

    # 构建临时连接字符串
    if db_user or db_pass:
        uri = f"mongodb://{db_user}:{db_pass}@{db_ip}:{db_port}"
    else:
        uri = f"mongodb://{db_ip}:{db_port}"

    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=2000)
        client.admin.command('ping')
        return jsonify({'success': True, 'message': '✅ 连接成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'❌ 连接失败: {str(e)}'})

@app.route('/')
def normal():
    return render_template('login.html', registered=request.args.get('registered'))


@app.route('/logout')
def logout():
    username = authenticate_token(request_token())
    if username:
        _remove_login(username)
    return redirect('/')


@app.route('/error')
def error():
    return render_template('login_error.html')


@app.route('/chattss', methods=['POST'])
def chats():
    username = authenticate_request()
    if not username:
        return json_error('认证数据错误', 401)
    touch_presence(username)
    state = mute_state(username)
    return jsonify({
        'ok': True,
        'messages': get_messages(),
        'current_user': username,
        'is_admin': is_admin(username),
        'muted': state['muted'],
        'muted_until': state['muted_until'],
        'server_time': time.time(),
    })


@app.route('/chatts_file', methods=['POST'])
def chat_file():
    username = authenticate_request()
    if not username:
        return json_error('认证数据错误', 401)
    try:
        ensure_not_muted(username)
    except MuteError as exc:
        return json_error('您已被禁言', 403, muted_until=exc.muted_until)

    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        return json_error('没有选择文件', 400)
    upload_dir, original_name = _safe_upload_path(uploaded.filename)
    if not upload_dir:
        return json_error('文件名无效', 400)

    name, extension = os.path.splitext(original_name)
    final_name = original_name
    counter = 1
    while os.path.exists(os.path.join(upload_dir, final_name)):
        final_name = '%s (%s)%s' % (name, counter, extension)
        counter += 1
    file_path = os.path.join(upload_dir, final_name)
    uploaded.save(file_path)

    extension_name = extension.lower().lstrip('.')
    if extension_name in IMAGE_EXTENSIONS:
        message_type, prefix = 'image', '::img::'
    elif extension_name in AUDIO_EXTENSIONS:
        message_type, prefix = 'audio', '::wav::'
    else:
        message_type, prefix = 'file', '::file::'
    payload = request_payload()
    try:
        message = add_chat(
            username,
            prefix + final_name,
            get_current_time(),
            reply_to=payload.get('reply_to'),
            message_type=message_type,
            check_mute=False,
        )
    except Exception:
        try:
            os.remove(file_path)
        except FileNotFoundError:
            pass
        raise
    return jsonify({'ok': True, 'update': request_token(), 'message': message})


@app.route('/get_online', methods=['GET', 'POST'])
def get_online():
    username = authenticate_request()
    if not username:
        return json_error('认证数据错误', 401)
    touch_presence(username)
    online = [entry['username'] for entry in loginings if entry['username'] != username]
    return ','.join(online)


@app.route('/username-list', methods=['GET'])
def online_list():
    return '||'.join(usernames)


@app.route('/chatts', methods=['GET', 'POST'])
def chat():
    global usernames, passwords, user_colors
    usernames = read_lines('usernames.list')
    passwords = read_lines('passwords.list')
    user_colors = read_lines('colors.list')

    sessions = load_sessions()
    token = request.args.get('update')
    username = authenticate_token(token) if token else None
    password = None
    session_login = bool(username)
    if username:
        password = passwords[usernames.index(username)] if username in usernames else None
    else:
        candidate = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        username = candidate if candidate in usernames else None

    if not username or username not in usernames:
        return redirect('/error')
    if session_login:
        valid_password = True
    else:
        try:
            valid_password = check_password_hash(passwords[usernames.index(username)], password)
        except (IndexError, ValueError, TypeError):
            valid_password = False
    if not valid_password:
        return redirect('/error')

    e_update = token if token and token == sessions.get(username) else _save_login(username)
    logger.info('用户：%s 登入聊天室', username)
    return render_template(
        'chat.html',
        text=str(request.args.get('text') or ''),
        username=username,
        update=e_update,
        self_ip=ip,
        jump_ip='http://' + ip + '/chatts?update=' + str(e_update),
        is_admin=is_admin(username),
        mute_until=mute_state(username)['muted_until'],
    )


@app.route('/register', methods=['GET', 'POST'])
def register():
    global usernames, passwords, user_colors
    if request.method == 'GET':
        return render_template('register.html')

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    invite_code = request.form.get('invite_code', '').strip()
    color = request.form.get('color', '#808080').strip()
    if not username or not password or not invite_code:
        return render_template('register.html', error='所有字段都必须填写', username=username, color=color, invite_code=invite_code)

    existing_users = read_lines('usernames.list')
    if username in existing_users:
        return render_template('register.html', error='用户名已存在，请选择其他名称', username=username, color=color, invite_code=invite_code)

    codes = read_lines('invite_code.txt')
    if invite_code not in codes:
        return render_template('register.html', error='无效的邀请码', username=username, color=color, invite_code=invite_code)

    codes.remove(invite_code)
    with open(os.path.join(BASE_DIR, 'invite_code.txt'), 'w', encoding='utf-8') as stream:
        stream.write('\n'.join(codes) + ('\n' if codes else ''))
    hashed_password = generate_password_hash(password)
    with open(os.path.join(BASE_DIR, 'usernames.list'), 'a', encoding='utf-8') as stream:
        stream.write(username + '\n')
    with open(os.path.join(BASE_DIR, 'passwords.list'), 'a', encoding='utf-8') as stream:
        stream.write(hashed_password + '\n')
    with open(os.path.join(BASE_DIR, 'colors.list'), 'a', encoding='utf-8') as stream:
        stream.write(color + '\n')
    usernames.append(username)
    passwords.append(hashed_password)
    user_colors.append(color)
    logger.info('新用户注册：%s，颜色：%s', username, color)
    return redirect('/?registered=true')


@app.route('/chatts-new', methods=['POST', 'GET'])
def chat_new():
    username = authenticate_request()
    if not username:
        return json_error('认证数据错误', 401)
    payload = request_payload()
    value = payload.get('upload_value', '')
    if value is None:
        value = ''
    value = str(value)
    if not value:
        return json_error('消息不能为空', 400)
    message_type = 'emoji' if value.startswith('::emoji::') else 'text'
    try:
        message = add_chat(username, value, get_current_time(), reply_to=payload.get('reply_to'), message_type=message_type)
    except MuteError as exc:
        return json_error('您已被禁言', 403, muted_until=exc.muted_until)
    return jsonify({'ok': True, 'update': request_token(), 'message': message})


def _message_for_recall(message_id, username):
    document = find_message(message_id)
    if not document:
        return None, '消息不存在'
    message = serialize_message(document)
    if message['type'] == 'system':
        return None, '系统消息不可撤回'
    if message['recalled']:
        return None, '消息已经撤回'
    if not is_admin(username) and message['user'] != username:
        return None, '只能撤回自己的消息'
    if not is_admin(username):
        created_at = message.get('timestamp') or 0
        if not created_at or time.time() - created_at > 120:
            return None, '只能撤回两分钟内的消息'
    return document, None


@app.route('/api/messages/<message_id>/recall', methods=['POST'])
@app.route('/api/recall', methods=['POST'])
@app.route('/chatts-recall', methods=['POST'])
@app.route('/recall', methods=['POST'])
def recall_message(message_id=None):
    username = authenticate_request()
    if not username:
        return json_error('认证数据错误', 401)
    if message_id is None:
        payload = request_payload()
        message_id = payload.get('id') or payload.get('message_id')
    document, error_message = _message_for_recall(message_id, username)
    if error_message:
        return json_error(error_message, 403 if '只能' in error_message else 404)
    update = {'$set': {'recalled': True, 'recalled_at': time.time()}}
    if document.get('_id') is not None:
        database.update_one({'_id': document['_id']}, update)
    elif document.get('id'):
        database.update_one({'id': document['id']}, update)
    _delete_attachment(document)
    return jsonify({'ok': True, 'id': str(message_id)})


def _mute_target_from_request():
    payload = request_payload()
    target = (payload.get('target') or payload.get('username') or '').strip()
    duration_value = payload.get('duration', 60)
    try:
        duration = int(duration_value)
    except (TypeError, ValueError):
        duration = 60
    return target, duration


@app.route('/api/mute', methods=['POST'])
@app.route('/chat/mute', methods=['POST'])
@app.route('/mute', methods=['POST'])
def mute_user():
    actor = authenticate_request()
    if not actor:
        return json_error('认证数据错误', 401)
    if not is_admin(actor):
        return json_error('没有禁言权限', 403)
    target, duration = _mute_target_from_request()
    if target not in usernames:
        return json_error('用户不存在', 404)
    if is_admin(target):
        return json_error('管理员不能被禁言', 403)
    if duration < MUTE_MIN_SECONDS or duration > MUTE_MAX_SECONDS:
        return json_error('禁言时长必须为 1-86400 秒', 400)
    existing = get_mute_record(target)
    if existing:
        return json_error('该用户已经处于禁言状态', 409, muted_until=float(existing['muted_until']))
    muted_until = time.time() + duration
    mutes.update_one(
        {'username': target},
        {'$set': {'username': target, 'muted_until': muted_until, 'muted_by': actor, 'created_at': time.time()}},
        upsert=True,
    )
    add_system_message('%s 将 %s 禁言 %s 秒' % (actor, target, duration))
    return jsonify({'ok': True, 'username': target, 'muted_until': muted_until})


@app.route('/api/unmute', methods=['POST'])
@app.route('/chat/unmute', methods=['POST'])
@app.route('/unmute', methods=['POST'])
def unmute_user():
    actor = authenticate_request()
    if not actor:
        return json_error('认证数据错误', 401)
    if not is_admin(actor):
        return json_error('没有解除禁言权限', 403)
    target, _ = _mute_target_from_request()
    if target not in usernames:
        return json_error('用户不存在', 404)
    record = get_mute_record(target)
    if not record:
        return json_error('该用户当前未被禁言', 404)
    mutes.delete_one({'_id': record['_id']})
    add_system_message('%s 解除了 %s 的禁言' % (actor, target))
    return jsonify({'ok': True, 'username': target, 'muted_until': 0})


@app.route('/api/cpp-preview', methods=['GET', 'POST'])
@app.route('/cpp-preview', methods=['GET', 'POST'])
@app.route('/chat/cpp-preview', methods=['GET', 'POST'])
def cpp_preview():
    username = authenticate_request()
    if not username:
        return json_error('认证数据错误', 401)
    payload = request_payload()
    filename = payload.get('filename') or request.args.get('filename')
    path = _cpp_path(filename)
    if not path or not os.path.isfile(path):
        return json_error('文件不存在或不是 .cpp 文件', 404)
    if os.path.getsize(path) > CPP_PREVIEW_LIMIT:
        return json_error('文件超过 1MB', 413)
    with open(path, 'rb') as stream:
        content, encoding = _decode_cpp(stream.read())
    return jsonify({'ok': True, 'filename': os.path.basename(path), 'content': content, 'encoding': encoding})


def _emoji_directory(username):
    safe_user = secure_filename(username or '')
    if not safe_user:
        return None
    path = os.path.abspath(os.path.join(BASE_DIR, 'static', 'emoji', safe_user))
    root = os.path.abspath(os.path.join(BASE_DIR, 'static', 'emoji'))
    return path if os.path.dirname(path) == root else None


@app.route('/chat/emoji/list/<username>', methods=['GET'])
def emoji_list(username):
    actor = authenticate_request()
    if actor != username and not is_admin(actor or ''):
        return json_error('没有权限', 403)
    directory = _emoji_directory(username)
    if not directory or not os.path.isdir(directory):
        return jsonify([])
    return jsonify(sorted(name for name in os.listdir(directory) if os.path.isfile(os.path.join(directory, name))))


@app.route('/chat/emoji/static/<username>/<filename>', methods=['GET'])
def emoji_static(username, filename):
    directory = _emoji_directory(username)
    safe = secure_filename(filename)
    if not directory or not safe or safe != filename:
        return json_error('文件不存在', 404)
    return send_from_directory(directory, safe)


@app.route('/chat/emoji/upload', methods=['POST'])
def emoji_upload():
    actor = authenticate_request()
    if not actor:
        return json_error('认证数据错误', 401)
    try:
        ensure_not_muted(actor)
    except MuteError as exc:
        return json_error('您已被禁言', 403, muted_until=exc.muted_until)
    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        return json_error('没有选择文件', 400)
    directory = _emoji_directory(actor)
    if not directory:
        return json_error('用户名无效', 400)
    os.makedirs(directory, exist_ok=True)
    filename = secure_filename(uploaded.filename)
    if not filename:
        return json_error('文件名无效', 400)
    uploaded.save(os.path.join(directory, filename))
    return jsonify({'success': True, 'filename': filename})


@app.route('/chat/emoji/delete', methods=['POST'])
def emoji_delete():
    actor = authenticate_request()
    if not actor:
        return json_error('认证数据错误', 401)
    payload = request_payload()
    target = payload.get('username') or actor
    if target != actor and not is_admin(actor):
        return json_error('没有权限', 403)
    directory = _emoji_directory(target)
    filename = secure_filename(payload.get('filename', ''))
    if not directory or not filename:
        return json_error('文件名无效', 400)
    path = os.path.join(directory, filename)
    if not os.path.isfile(path):
        return json_error('文件不存在', 404)
    os.remove(path)
    return jsonify({'success': True})

@app.before_request
def check_initialized():
    if request.path.startswith('/static') or request.path in ('/init', '/init/ping', '/favicon.ico'):
        return
    # 排除静态文件、初始化页面、错误页面等
    if request.path.startswith('/static') or request.path == '/init' or request.path == '/favicon.ico':
        return
    # 检查是否已配置（存在 config.json 且存在至少一个用户）
    if not os.path.exists(CONFIG_FILE) or not os.path.exists(os.path.join(BASE_DIR, 'usernames.list')):
        return redirect('/init')
    # 如果 config.json 存在但无任何用户，也重定向（极端情况）
    with open(os.path.join(BASE_DIR, 'usernames.list'), 'r', encoding='utf-8') as f:
        if not f.read().strip():
            return redirect('/init')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
