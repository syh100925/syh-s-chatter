from flask import Flask, render_template, request, redirect, send_file, Response
import time
import random
from pymongo import MongoClient
import logging
import os
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

server_ip = ''

database_ip = '127.0.0.1' # YOUR IP
database_port = '27017'
database_user = ''
database_password = ''

usernames = open('usernames.list', 'r', encoding='utf-8').read().split('\n')
passwords = open('passwords.list', 'r', encoding='utf-8').read().split('\n')
user_colors = open('colors.list', 'r', encoding='utf-8').read().split('\n')


client = MongoClient('mongodb://' + database_user + ':' + database_password + '@' + database_ip + ':' + database_port)

db = client['chats']
database = db['values']

if len(db.list_collection_names()) == 0:
    database.insert_one({'chat': 'clear', 'user': 'admin', 'color': 'grey', 'time': 'unknown'})

d_c = 0
for data in database.find():
    d_c += 1
if d_c < 20:
    for _ in range(20 - d_c):
        database.insert_one({'chat': '', 'user': '', 'color': '', 'time': ''})

app = Flask(__name__)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(os.path.join(os.path.dirname(__file__), 'log.txt'))

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

logger.addHandler(file_handler)

open('login_users.txt', 'a')
open('login_passes.txt', 'a')

ip = server_ip

loginings = []

def get_current_time():
    d_time = time.localtime()
    d_year = str(d_time.tm_year)
    d_month = str(d_time.tm_mon)
    d_day = str(d_time.tm_mday)
    d_hour = str(d_time.tm_hour)
    d_min = str(d_time.tm_min)
    if len(d_year) == 1:
        d_year = '0' + d_year
    if len(d_month) == 1:
        d_month = '0' + d_month
    if len(d_hour) == 1:
        d_hour = '0' + d_hour
    if len(d_min) == 1:
        d_min = '0' + d_min
    if len(d_day) == 1:
        d_day = '0' + d_day
    d_time = d_year + ':' + d_month + ':' + d_day + ':' + d_hour + ':' + d_min
    return d_time

def get_data():
    """
    从 database 集合中获取所有消息，按插入顺序返回（最早的在前面）。
    返回四个列表：chats, users, colors, times，长度等于实际消息数，无填充。
    """
    cursor = database.find().sort('_id', 1)  # 按 _id 升序保证插入顺序
    chats, users, colors, times = [], [], [], []
    for doc in cursor:
        chats.append(doc.get('chat', ''))
        users.append(doc.get('user', ''))
        colors.append(doc.get('color', ''))
        times.append(doc.get('time', ''))
    return [chats, users, colors, times]

def add_chat(username, value, d_time):
    """
    向 database 集合中添加一条新消息（直接插入文档）。
    """
    logger.info(f'用户：{username} 上传了信息：{value}')

    # 管理员命令处理
    if username == 'admin' and value[:9] == 'command: ':
        admin_command(username, value, d_time)
        return

    # 获取该用户的颜色
    color = user_colors[usernames.index(username)]

    # 插入新文档
    database.insert_one({
        'chat': value,
        'user': username,
        'color': color,
        'time': d_time
    })

def admin_command(username, command_str, d_time):
    """
    处理管理员命令，直接操作数据库。
    command_str 格式："command: 命令 参数"
    """
    parts = command_str[9:].split(' ')
    cmd = parts[0]

    if cmd == 'clear':
        # 删除所有消息，并插入一条 clear 记录
        database.delete_many({})
        database.insert_one({
            'chat': 'clear',
            'user': 'admin',
            'color': 'grey',
            'time': d_time
        })

    elif cmd == 'change_color' and len(parts) >= 3:
        target_user = parts[1]
        new_color = parts[2]
        if target_user in usernames:
            idx = usernames.index(target_user)
            user_colors[idx] = new_color
            with open('colors.list', 'w', encoding='utf-8') as f:
                f.write('\n'.join(user_colors) + '\n')
            # 注意：已有消息的颜色不会改变，只影响后续消息
            logger.info(f'管理员将用户 {target_user} 的颜色改为 {new_color}')

    elif cmd == 'delete' and len(parts) >= 2:
        try:
            count = int(parts[1])
        except ValueError:
            count = 0
        if count > 0:
            # 按 _id 升序找出所有文档，删除最后 count 个
            all_docs = list(database.find().sort('_id', 1))
            if len(all_docs) >= count:
                ids_to_delete = [doc['_id'] for doc in all_docs[-count:]]
                database.delete_many({'_id': {'$in': ids_to_delete}})
                logger.info(f'管理员删除了最后 {count} 条消息')
    else:
        # 未知命令：将命令本身作为普通消息插入（原逻辑）
        color = user_colors[usernames.index(username)]
        database.insert_one({
            'chat': command_str,  # 原样保存，前端会显示未知命令
            'user': username,
            'color': color,
            'time': d_time
        })

# ========== 第二个聊天室 (database_z) 的对应函数 ==========

def get_data_z():
    """从 database_z 获取所有消息"""
    cursor = database_z.find().sort('_id', 1)
    chats, users, colors, times = [], [], [], []
    for doc in cursor:
        chats.append(doc.get('chat', ''))
        users.append(doc.get('user', ''))
        colors.append(doc.get('color', ''))
        times.append(doc.get('time', ''))
    return [chats, users, colors, times]

def add_chat_z(username, value, d_time):
    """
    向 database_z 添加消息。如果 username 是 admin，则执行 clear 操作（清空并插入一条 clear）。
    """
    logger.info(f'用户：{username} 上传了信息：{value}')

    # 管理员特殊处理：执行 clear
    if username == 'admin':
        database_z.delete_many({})
        database_z.insert_one({
            'chat': 'clear',
            'user': 'admin',
            'color': 'grey',
            'time': d_time
        })
        return

    # 普通用户正常插入
    color = user_colors[usernames.index(username)]
    database_z.insert_one({
        'chat': value,
        'user': username,
        'color': color,
        'time': d_time
    })

@app.route('/')
def normal():
    registered = request.args.get('registered')
    return render_template('login.html', registered=registered)

@app.route('/logout')
def logout():
    return redirect('/')

@app.route('/error')
def error():
    return render_template('login_error.html')

@app.route('/chattss', methods=['POST'])
def chats():
    username = request.form.get('username')
    update = request.form.get('update')
    a = open('login_users.txt', 'r').read().split('\n')
    b = open('login_passes.txt', 'r').read().split('\n')
    logining_users = {}
    for i in range(len(a)):
        logining_users[a[i]] = [int(b[i])]
    if username not in logining_users or not str(logining_users[username][0]) == update:
        return '认证数据错误\n聊天室\nred\nunknown'

    chats, users, colors, times = get_data()
    r = ''
    for i in chats:
        r += i + ' || '
    r = r[: -4] + '\n'
    for i in users:
        r += i + ' || '
    r = r[: -4] + '\n'
    for i in colors:
        r += i + ' || '
    r = r[: -4] + '\n'
    for i in times:
        r += i + ' || '

    fl = True
    for i in range(len(loginings) - 1, -1, -1):
        if time.time() - loginings[i]['time'] > 10:
            loginings.pop(i)
        elif loginings[i]['username'] == username:
            fl = False
            loginings[i]['time'] = time.time()
    if fl:
        loginings.append({'username': username, 'time': time.time()})

    return r

@app.route('/chatts_file', methods=['GET', 'POST'])
def chat_file():
    chats, users, colors, times = get_data()
    # 读取登录用户信息（这部分保持不变）
    a = open('login_users.txt', 'r').read().split('\n')
    b = open('login_passes.txt', 'r').read().split('\n')
    logining_users = {}
    for i in range(len(a)):
        if a[i]:  # 忽略空行
            logining_users[a[i]] = [int(b[i])]

    upf = request.files['file']
    ip = request.args.get('update')

    if upf.filename != '':
        # 获取原始文件名
        original_filename = secure_filename(upf.filename)
        # 分割名称和扩展名
        name, ext = os.path.splitext(original_filename)
        # 目标上传目录
        upload_dir = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
        os.makedirs(upload_dir, exist_ok=True)  # 确保目录存在

        # 生成唯一文件名（保留原始名，避免重名）
        final_filename = original_filename
        counter = 1
        while os.path.exists(os.path.join(upload_dir, final_filename)):
            # 格式：name (1).ext
            final_filename = f"{name} ({counter}){ext}"
            counter += 1

        # 保存文件
        upf.save(os.path.join(upload_dir, final_filename))

        # 处理更新令牌
        if ip is None:
            ip = 0
        else:
            ip = int(ip)
        username = 'unknown'

        d_time = get_current_time()

        for i in logining_users:
            if str(logining_users[i][0]) == str(ip):
                username = i

        if username == 'unknown':
            return redirect('/chatts?update=' + str(ip))

        # 根据文件类型确定前缀
        f_v = '::file::'
        f_imgs_types = ['jpg', 'png', 'jpeg', 'bmp']
        if ext.lower().lstrip('.') in f_imgs_types:  # 注意ext包含点，所以用ext[1:]或lower
            f_v = '::img::'
        f_audios_types = ['mp3', 'wav', 'flac']
        if ext.lower().lstrip('.') in f_audios_types:
            f_v = '::wav::'

        value = f_v + final_filename

        add_chat(username, value, d_time)

    return str(ip)

@app.route('/get_online', methods=['GET', 'POST'])
def get_online():
    a = open('login_users.txt', 'r').read().split('\n')
    b = open('login_passes.txt', 'r').read().split('\n')
    logining_users = {}
    for i in range(len(a)):
        logining_users[a[i]] = [int(b[i])]

    ip = request.values.get('update')

    username = 'unknown'

    for i in logining_users:
        if str(logining_users[i][0]) == str(ip):
            username = i

    if username != 'unknown':
        s = ''
        co = 0
        for i in loginings:
            if i['username'] != username:
                s += i['username'] + ','
                co += 1
        if co != 0:
            s = s[:-1]
        else:
            s = ''
        return s

    return redirect('/chatts?update=' + str(ip))

@app.route('/username-list', methods=['GET'])
def online_list():
    res = ""
    for i in usernames:
        res += i + "||"
    res = res[:-2]
    return res

@app.route('/chatts', methods=['GET', 'POST'])
def chat():
    global usernames, passwords, user_colors
    usernames = open('usernames.list', 'r', encoding='utf-8').read().split('\n')
    passwords = open('passwords.list', 'r', encoding='utf-8').read().split('\n')
    user_colors = open('colors.list', 'r', encoding='utf-8').read().split('\n')

    a = open('login_users.txt', 'r').read().split('\n')
    b = open('login_passes.txt', 'r').read().split('\n')

    if a == ['']:
        a = []
        b = []

    text = request.args.get('text')
    if text == None:
        text = ''
    text = str(text)

    logining_users = {}
    if len(a) != 0:
        for i in range(len(a)):
            logining_users[a[i]] = [int(b[i]), time.time()]

    username = None
    password = None
    r = None

    try:
        r = int(request.args.get('update'))

    except:
        pass

    for i in logining_users:
        if logining_users[i][0] == r:
            if time.time() - logining_users[i][1] > 3 * 60:
                del logining_users[i]
                l_users = ''
                l_passes = ''
                for i in logining_users:
                    l_users += i + '\n'
                    l_passes += str(logining_users[i][0]) + '\n'
                l_users = l_users[ : -1]
                l_passes = l_passes[ : -1]

                open('login_users.txt', 'w').write(l_users)
                open('login_passes.txt', 'w').write(l_passes)

            else:
                username = i
                password = passwords[usernames.index(username)]

    if username == None and password == None:
        username = str(request.form.get('username'))
        password = str(request.form.get('password'))

    if username in usernames and check_password_hash(passwords[usernames.index(username)], password):
        if not username in logining_users:
            logger.info('用户：' + username + '登入聊天室')
        logining_users[username] = [random.randint(1000000000, 10000000000 - 1), time.time()]

        fl = True
        for i in range(len(loginings) - 1, -1, -1):
            if time.time() - loginings[i]['time'] > 10:
                loginings.pop(i)
            elif loginings[i]['username'] == username:
                fl = False
                loginings[i]['time'] = time.time()
        if fl:
            loginings.append({'username': username, 'time': time.time()})


        l_users = ''
        l_passes = ''
        for i in logining_users:
            l_users += i + '\n'
            l_passes += str(logining_users[i][0]) + '\n'
        l_users = l_users[ : -1]
        l_passes = l_passes[ : -1]

        open('login_users.txt', 'w').write(l_users)
        open('login_passes.txt', 'w').write(l_passes)

        e_update = logining_users[username][0]

        if username == "梨岚":
            return str(e_update)

        return render_template('chat.html', text=text, username=username, update=e_update, self_ip=ip, jump_ip='http://' + ip + '/chatts?update=' + str(e_update))
    else:
        return redirect('/error')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')

    # 获取表单数据
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    invite_code = request.form.get('invite_code', '').strip()
    color = request.form.get('color', '#808080').strip()

    # 基本校验
    if not username or not password or not invite_code:
        return render_template('register.html',
                               error="所有字段都必须填写",
                               username=username,
                               color=color,
                               invite_code=invite_code)

    # 检查用户名是否已存在
    with open('usernames.list', 'r', encoding='utf-8') as f:
        existing_users = [line.strip() for line in f if line.strip()]
    if username in existing_users:
        return render_template('register.html',
                               error="用户名已存在，请选择其他名称",
                               username=username,
                               color=color,
                               invite_code=invite_code)

    # 验证邀请码
    try:
        with open('invite_code.txt', 'r', encoding='utf-8') as f:
            codes = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        codes = []

    if invite_code not in codes:
        return render_template('register.html',
                               error="无效的邀请码",
                               username=username,
                               color=color,
                               invite_code=invite_code)

    # ----- 验证通过，执行注册 -----
    # 1. 移除已使用的邀请码
    codes.remove(invite_code)
    with open('invite_code.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(codes))
        if codes:
            f.write('\n')

    # 2. 哈希密码
    hashed_password = generate_password_hash(password)

    # 3. 追加新用户到三个文件
    with open('usernames.list', 'a', encoding='utf-8') as f:
        f.write(username + '\n')
    with open('passwords.list', 'a', encoding='utf-8') as f:
        f.write(hashed_password + '\n')
    with open('colors.list', 'a', encoding='utf-8') as f:
        f.write(color + '\n')

    # 4. 更新全局列表（如果有）
    global usernames, passwords, user_colors
    usernames.append(username)
    passwords.append(hashed_password)
    user_colors.append(color)

    logger.info(f'新用户注册：{username}，颜色：{color}')

    return redirect('/?registered=true')

@app.route('/chatts-new', methods=['POST', 'GET'])
def chat_new():
    a = open('login_users.txt', 'r').read().split('\n')
    b = open('login_passes.txt', 'r').read().split('\n')
    logining_users = {}
    for i in range(len(a)):
        logining_users[a[i]] = [int(b[i])]

    value = str(request.form.get('upload_value'))
    ip = request.args.get('update')
    if ip == None:
        ip = 0
    else:
        ip = int(ip)

    username = 'unknown'

    d_time = get_current_time()

    for i in logining_users:
        if str(logining_users[i][0]) == str(ip):
            username = i

    if username == "unknown":
        return redirect('/chatts?update=' + str(ip))

    add_chat(username, value, d_time)

    # return redirect('/chatts?update=' + str(ip))
    return str(ip)
