"""冒烟测试：初始化 → 注册 → 登录 → 发消息 → 命令 → 撤回 → 禁言 → 权限组。

用法：python -m tests.smoke_test  （无需真实 MongoDB，使用 mongomock 回退）
"""
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chatter import create_app, state  # noqa: E402


def extract_token(html):
    match = re.search(r'update: "(\d+)"', html)
    if not match:
        raise AssertionError('未在 chat.html 中找到 update token')
    return match.group(1)


def main():
    tmp = tempfile.mkdtemp(prefix='chatter_test_')
    try:
        app = create_app(data_dir=tmp)
        client = app.test_client()

        # 1. 未初始化 → 重定向到 /init
        r = client.get('/')
        assert r.status_code == 302 and r.headers['Location'].endswith('/init'), '未初始化应跳转 /init'

        # 2. 初始化
        r = client.post('/init', data={
            'db_ip': '127.0.0.1', 'db_port': '27017', 'db_user': '', 'db_pass': '',
            'server_ip': '127.0.0.1:5000',
            'admin_user': 'admin', 'admin_pass': 'admin123', 'admin_pass_confirm': 'admin123',
            'invite_count': '2',
        })
        assert r.status_code == 200, '初始化应成功'
        codes = state.read_lines('invite_code.txt')
        assert len(codes) == 2, '应生成 2 个邀请码'

        # 3. 初始化后根路径 → 登录页
        r = client.get('/')
        assert r.status_code == 200 and b'login' in r.data.lower(), '应返回登录页'

        # 4. 注册新用户
        r = client.post('/register', data={
            'username': 'alice', 'password': 'alice123', 'invite_code': codes[0],
            'color': '#ff0000',
        })
        assert r.status_code == 302, '注册应成功'
        assert 'alice' in state.usernames

        # 5. 管理员登录
        r = client.post('/chatts', data={'username': 'admin', 'password': 'admin123'})
        assert r.status_code == 200, '管理员登录失败'
        admin_token = extract_token(r.data.decode('utf-8'))

        # 6. 管理员发消息
        r = client.post('/chatts-new', json={
            'username': 'admin', 'update': admin_token, 'upload_value': 'hello world'})
        assert r.status_code == 200 and r.get_json()['ok'], '发消息失败'
        r = client.post('/chatts-new', json={
            'username': 'admin', 'update': admin_token, 'upload_value': 'second message'})
        assert r.status_code == 200 and r.get_json()['ok'], '发消息失败'

        # 7. 拉取消息
        r = client.post('/chattss', json={'username': 'admin', 'update': admin_token})
        data = r.get_json()
        assert data['ok'] and data['is_admin'], 'chattss 响应异常'
        assert any(m['content'] == 'hello world' for m in data['messages']), '消息未返回'
        assert 'chat.clear' in data['permissions'], '管理员应拥有全部权限'

        # 8. 撤回消息（hello world）
        target_id = None
        for m in data['messages']:
            if m['content'] == 'hello world':
                target_id = m['id']
        r = client.post('/api/messages/%s/recall' % target_id, json={
            'username': 'admin', 'update': admin_token})
        assert r.status_code == 200, '撤回失败'

        # 9. 管理员执行命令（delete 1）
        r = client.post('/chatts-new', json={
            'username': 'admin', 'update': admin_token, 'upload_value': 'command: delete 1'})
        assert r.status_code == 200, '命令执行失败'
        r = client.post('/chattss', json={'username': 'admin', 'update': admin_token})
        data = r.get_json()
        assert any(m['user'] == 'system' for m in data['messages']), '应产生系统消息'

        # 10. 普通用户登录并发送命令（应作为普通消息，不执行）
        r = client.post('/chatts', data={'username': 'alice', 'password': 'alice123'})
        assert r.status_code == 200, 'alice 登录失败'
        alice_token = extract_token(r.data.decode('utf-8'))
        r = client.post('/chatts-new', json={
            'username': 'alice', 'update': alice_token, 'upload_value': 'command: delete 1'})
        assert r.status_code == 200
        r = client.post('/chattss', json={'username': 'alice', 'update': alice_token})
        alice_data = r.get_json()
        assert 'chat.clear' not in alice_data['permissions'] and 'admin.panel' not in alice_data['permissions'], \
            'alice 不应有管理权限'
        r = client.post('/chattss', json={'username': 'admin', 'update': admin_token})
        data = r.get_json()
        assert any(m['user'] == 'alice' and m['content'] == 'command: delete 1'
                   for m in data['messages']), '无权限命令应作为普通消息发送'

        # 11. 禁言 + 禁言后发消息被拒
        r = client.post('/api/mute', json={
            'username': 'admin', 'update': admin_token, 'target': 'alice', 'duration': 60})
        assert r.status_code == 200, '禁言失败'
        r = client.post('/chatts-new', json={
            'username': 'alice', 'update': alice_token, 'upload_value': 'muted test'})
        assert r.status_code == 403, '被禁言用户发消息应被拒绝'
        r = client.post('/api/unmute', json={
            'username': 'admin', 'update': admin_token, 'target': 'alice'})
        assert r.status_code == 200, '解除禁言失败'

        # 12. 普通用户禁言他人 → 403
        r = client.post('/api/mute', json={
            'username': 'alice', 'update': alice_token, 'target': 'bob', 'duration': 60})
        assert r.status_code == 403, '普通用户禁言应被拒绝'

        # 13. 在线列表与用户名列表
        r = client.post('/get_online', json={'username': 'admin', 'update': admin_token})
        assert r.status_code == 200
        r = client.get('/username-list')
        assert 'admin' in r.data.decode('utf-8')

        # 14. 登出
        r = client.get('/logout?update=' + admin_token)
        assert r.status_code == 302

        print('OK: 冒烟测试全部通过（14 项）')
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
