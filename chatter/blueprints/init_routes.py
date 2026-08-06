"""初始化路由：/init 与 /init/ping。"""
import os
import random
import string

from flask import jsonify, redirect, render_template, request, url_for

from .. import config, database, messages, state, users
from ..auth import authenticate_request
from ..state import logger
from . import make_blueprint

bp = make_blueprint('init')


def _is_initialized():
    if not os.path.exists(config.config_path()):
        return False
    users_path = os.path.join(state.DATA_DIR, 'usernames.list')
    if not os.path.exists(users_path):
        return False
    with open(users_path, 'r', encoding='utf-8') as f:
        return bool(f.read().strip())


@bp.route('/init', methods=['GET', 'POST'])
def init_page():
    # 如果已经初始化过（有 config.json 且至少有一个用户），则禁止再次访问
    if _is_initialized():
        return redirect(url_for('auth.normal'))

    if request.method == 'GET':
        cfg = config.load_config()
        # 不显式传 base_path：模板统一使用上下文处理器注入的实时挂载前缀
        # （state.base_path），避免全新安装（无 config.json）时表单/接口路径丢失前缀。
        # 表单中的 base_path 输入框由上下文处理器预填实际前缀，用户可修改。
        return render_template('init.html',
                               db_ip=cfg.get('db_ip', '127.0.0.1'),
                               db_port=cfg.get('db_port', '27017'),
                               db_user=cfg.get('db_user', ''),
                               db_pass=cfg.get('db_pass', ''),
                               server_ip=cfg.get('server_ip', ''),
                               base_path_value=state.base_path,
                               port=cfg.get('port', 5000),
                               admin_user='admin',
                               error=None)

    # POST 处理
    db_ip = request.form.get('db_ip', '').strip()
    db_port = request.form.get('db_port', '').strip()
    db_user = request.form.get('db_user', '').strip()
    db_pass = request.form.get('db_pass', '').strip()
    new_server_ip = request.form.get('server_ip', '').strip()
    new_base_path = config.normalize_base_path(request.form.get('base_path'))
    new_port = request.form.get('port', '5000').strip()
    admin_user = request.form.get('admin_user', '').strip()
    admin_pass = request.form.get('admin_pass', '').strip()
    admin_pass_confirm = request.form.get('admin_pass_confirm', '').strip()
    invite_count = request.form.get('invite_count', '5').strip()

    def re_render(error_message):
        return render_template('init.html', error=error_message,
                               db_ip=db_ip, db_port=db_port, db_user=db_user, db_pass=db_pass,
                               server_ip=new_server_ip, base_path_value=new_base_path,
                               port=new_port,
                               admin_user=admin_user, invite_count=invite_count)

    # 基本验证
    if not db_ip or not db_port or not admin_user or not admin_pass:
        return re_render('所有必填字段不能为空')
    if admin_pass != admin_pass_confirm:
        return re_render('管理员密码不一致')
    try:
        new_port = int(new_port)
        if not 1 <= new_port <= 65535:
            return re_render('端口必须在 1-65535 之间')
    except ValueError:
        return re_render('端口必须是数字')
    try:
        invite_count = int(invite_count)
        if invite_count < 1:
            invite_count = 1
    except ValueError:
        invite_count = 5

    # 保存配置（包含管理员列表与管理员的 admin 权限组）
    old_base_path = state.base_path  # 当前实际挂载前缀（前缀变更前重启无效）
    old_port = state.settings.get('port', 5000)
    new_config = config.load_config()
    new_config.update({
        'db_ip': db_ip,
        'db_port': db_port,
        'db_user': db_user,
        'db_pass': db_pass,
        'server_ip': new_server_ip,
        'base_path': new_base_path,
        'port': new_port,
        'admins': [admin_user],
        'initial_admin': admin_user,
    })
    user_groups = dict(new_config.get('user_groups') or {})
    user_groups[admin_user] = 'admin'
    new_config['user_groups'] = user_groups
    config.save_config(new_config)
    config.load_settings()

    # 创建管理员用户
    existing_users = state.read_lines('usernames.list')
    if admin_user in existing_users:
        return re_render('管理员用户名已存在，请更换')

    from werkzeug.security import generate_password_hash
    users.append_user(admin_user, generate_password_hash(admin_pass), '#ffffff')

    # 生成邀请码
    invite_path = os.path.join(state.DATA_DIR, 'invite_code.txt')
    existing_codes = set(state.read_lines('invite_code.txt'))
    for _ in range(invite_count):
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        existing_codes.add(code)
    with open(invite_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(existing_codes)) + '\n')

    # 重新连接数据库（使用新配置）
    database.init_database(config.load_settings())

    # 插入一条系统消息
    messages.add_system_message('系统初始化完成，管理员 %s 已创建' % admin_user)
    logger.info('系统初始化完成，管理员：%s', admin_user)

    generated_codes = state.read_lines('invite_code.txt')
    return render_template('init_complete.html',
                           admin_user=admin_user,
                           invite_codes=generated_codes,
                           db_ip=db_ip,
                           server_ip=new_server_ip,
                           live_base_path=old_base_path,
                           saved_base_path=new_base_path,
                           saved_port=new_port,
                           restart_required=(new_base_path != old_base_path or new_port != old_port))


@bp.route('/init/ping', methods=['POST'])
def init_ping():
    """测试数据库连接（用于初始化页面）。"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '缺少请求数据'}), 400

    db_ip = data.get('db_ip', '').strip()
    db_port = data.get('db_port', '').strip()
    db_user = data.get('db_user', '').strip()
    db_pass = data.get('db_pass', '').strip()

    if not db_ip or not db_port:
        return jsonify({'success': False, 'message': '数据库IP和端口不能为空'}), 400

    if db_user or db_pass:
        uri = f"mongodb://{db_user}:{db_pass}@{db_ip}:{db_port}"
    else:
        uri = f"mongodb://{db_ip}:{db_port}"

    try:
        from pymongo import MongoClient
        client = MongoClient(uri, serverSelectionTimeoutMS=2000)
        client.admin.command('ping')
        return jsonify({'success': True, 'message': '连接成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': '连接失败: %s' % str(e)})


@bp.route('/init/status', methods=['GET'])
def init_status():
    return jsonify({'initialized': _is_initialized()})
