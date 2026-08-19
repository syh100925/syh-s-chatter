"""冒烟测试：初始化 → 注册 → 登录 → 发消息 → 命令 → 撤回 → 禁言 → 权限组。

用法：python -m tests.smoke_test  （无需真实 MongoDB，使用 mongomock 回退）
"""
import json
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
        assert b"cursor:url('/static/cur-default.png')" in r.data, \
            '聊天室页面应注入自定义鼠标指针'

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
        assert b'cur-default' not in r.data, 'JSON 接口不应注入鼠标指针样式'

        # 7b. 插件页面不应注入鼠标指针（仅聊天室路由生效）
        r = client.get('/plugins/hello_world/about')
        assert r.status_code == 200, '插件页面应可访问'
        assert b'cur-default' not in r.data, '插件页面不应注入鼠标指针'

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

        # 10b. 撤回鉴权：普通用户只能撤回自己的消息，管理员可撤回任意消息
        assert 'message.recall.any' not in alice_data['permissions'], \
            '普通用户不应拥有 message.recall.any 权限'
        r = client.post('/chatts-new', json={
            'username': 'admin', 'update': admin_token, 'upload_value': 'recall target'})
        assert r.status_code == 200, '发消息失败'
        recall_target = r.get_json()['message']['id']
        r = client.post('/api/messages/%s/recall' % recall_target, json={
            'username': 'alice', 'update': alice_token})
        assert r.status_code == 403, '普通用户撤回他人消息应被拒绝'
        r = client.post('/api/messages/%s/recall' % recall_target, json={
            'username': 'admin', 'update': admin_token})
        assert r.status_code == 200, '管理员应可撤回他人消息'
        r = client.post('/chattss', json={'username': 'alice', 'update': alice_token})
        own_data = r.get_json()
        own_target = next((m['id'] for m in own_data['messages']
                           if m['user'] == 'alice'), None)
        assert own_target, '应能找到 alice 自己的消息'
        r = client.post('/api/messages/%s/recall' % own_target, json={
            'username': 'alice', 'update': alice_token})
        assert r.status_code == 200, '普通用户应能撤回自己的消息'

        # ============ 分段传输：分页查询 ============
        import uuid as _uuid
        import time as _time
        from chatter import messages as _messages
        # 直插 210 条消息，验证默认只返回最近部分（避免逐条走 HTTP）
        for i in range(210):
            state.database.insert_one({
                'id': _uuid.uuid4().hex, 'chat': 'bulk-%d' % i, 'content': 'bulk-%d' % i,
                'user': 'bulkuser', 'color': '#123456', 'time': _messages.get_current_time(),
                'created_at': _time.time(), 'type': 'text', 'recalled': False, 'reply_to': None,
            })
        base_total = 5 + 210  # 此前 5 条 + 批量 210 条

        # 默认（不填分页参数）：只返回最近 200 条
        r = client.post('/chattss', json={'username': 'admin', 'update': admin_token})
        data = r.get_json()
        assert data['ok'], 'chattss 响应异常'
        assert len(data['messages']) == _messages.DEFAULT_PAGE_LIMIT, \
            '默认应只返回最近 %d 条：%d' % (_messages.DEFAULT_PAGE_LIMIT, len(data['messages']))
        assert data['has_more'] is True, '存在更早消息时 has_more 应为 True'
        assert data['total'] == base_total, 'total 应为消息总数：%s' % data['total']
        assert data['messages'][0]['content'] == 'bulk-10', '默认页应从最近窗口开头'
        assert data['messages'][-1]['content'] == 'bulk-209', '默认页应以最新消息结尾'
        default_page = data['messages']

        # limit 参数生效
        r = client.post('/chattss', json={'username': 'admin', 'update': admin_token, 'limit': 3})
        data = r.get_json()
        assert [m['content'] for m in data['messages']] == ['bulk-207', 'bulk-208', 'bulk-209'], \
            'limit=3 应只返回最近 3 条'
        assert data['has_more'] is True and data['total'] == base_total

        # 非法/越界 limit 回退：非数字按默认处理，0 下限为 1
        r = client.post('/chattss', json={'username': 'admin', 'update': admin_token, 'limit': 'abc'})
        assert len(r.get_json()['messages']) == _messages.DEFAULT_PAGE_LIMIT, '非法 limit 应回退默认'
        r = client.post('/chattss', json={'username': 'admin', 'update': admin_token, 'limit': 0})
        assert len(r.get_json()['messages']) == 1, 'limit=0 应回退为 1'

        # after：只返回该消息之后（更新）的消息
        anchor_id = default_page[-2]['id']  # bulk-208
        r = client.post('/chattss', json={
            'username': 'admin', 'update': admin_token, 'after': anchor_id, 'limit': 10})
        data = r.get_json()
        assert [m['content'] for m in data['messages']] == ['bulk-209'], 'after 应只返回更新的消息'

        # before：返回该消息之前（更早）的消息，升序且不含锚点
        r = client.post('/chattss', json={
            'username': 'admin', 'update': admin_token, 'before': anchor_id, 'limit': 3})
        data = r.get_json()
        assert [m['content'] for m in data['messages']] == ['bulk-205', 'bulk-206', 'bulk-207'], \
            'before 应返回更早消息且升序'
        assert data['has_more'] is True

        # before 到最早边界：has_more 应为 False
        oldest_id = default_page[0]['id']  # bulk-10
        r = client.post('/chattss', json={
            'username': 'admin', 'update': admin_token, 'before': oldest_id, 'limit': 200})
        data = r.get_json()
        assert len(data['messages']) == 15, '更早消息应为 15 条：%d' % len(data['messages'])
        assert data['messages'][-1]['content'] == 'bulk-9', '更早窗口应以 bulk-9 结尾'
        assert data['has_more'] is False, '到达最早消息时 has_more 应为 False'

        # 未知游标：回退为默认最近窗口
        r = client.post('/chattss', json={
            'username': 'admin', 'update': admin_token, 'before': 'no-such-id', 'limit': 3})
        assert [m['content'] for m in r.get_json()['messages']] == ['bulk-207', 'bulk-208', 'bulk-209'], \
            '未知游标应回退为最近窗口'

        # 清理批量消息，避免影响后续场景
        state.database.delete_many({'user': 'bulkuser'})
        r = client.post('/chattss', json={'username': 'admin', 'update': admin_token})
        assert r.get_json()['total'] == 5, '清理后 total 应恢复为 5'

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

        # 12b. 账户保护：初始管理员不可被删除/降级，管理员不可移除自己的权限
        r = client.get('/admin/api/users?update=' + admin_token)
        users_data = r.get_json()
        assert users_data['ok'] and users_data['initial_admin'] == 'admin', '应回传初始管理员标记'
        assert users_data['actor'] == 'admin', '应回传当前操作者'
        # 删除初始管理员（自己）→ 拒绝
        r = client.post('/admin/api/users/delete', json={
            'username': 'admin', 'update': admin_token, 'username': 'admin'})
        assert r.status_code == 400, '删除初始管理员应被拒绝'
        # 通过设置移除自己的 admin 权限 → 拒绝（admins 保持原样）
        r = client.post('/admin/api/settings', json={
            'username': 'admin', 'update': admin_token,
            'settings': {'admins': ['alice']}})
        settings_data = r.get_json()
        assert 'admin' in settings_data['settings']['admins'], \
            '初始管理员不可被移出管理员列表'
        # 通过权限组把初始管理员降级 → 拒绝
        r = client.post('/admin/api/users/group', json={
            'username': 'admin', 'update': admin_token, 'username': 'admin', 'group': 'user'})
        assert r.status_code == 400, '把初始管理员移出管理员组应被拒绝'
        assert 'admin' in state.admins, '初始管理员应仍保留在管理员列表'
        # 删除普通用户 → 允许
        r = client.post('/register', data={
            'username': 'bob', 'password': 'bob123', 'invite_code': codes[1],
            'color': '#00ff00'})
        assert r.status_code == 302, 'bob 注册失败'
        r = client.post('/admin/api/users/delete', json={
            'username': 'admin', 'update': admin_token, 'username': 'bob'})
        assert r.status_code == 200, '删除普通用户应允许'

        # 13. 在线列表与用户名列表
        r = client.post('/get_online', json={'username': 'admin', 'update': admin_token})
        assert r.status_code == 200
        r = client.get('/username-list')
        assert 'admin' in r.data.decode('utf-8')

        # 14. 登出
        r = client.get('/logout?update=' + admin_token)
        assert r.status_code == 302

        # ============ 场景 A：带前缀（base_path='/chat'）初始化与路由 ============
        tmp2 = tempfile.mkdtemp(prefix='chatter_test_prefix_')
        try:
            app2 = create_app(data_dir=tmp2, base_path='/chat')
            client2 = app2.test_client()

            # 未初始化时，根路径经 before_request 跳转到前缀下的 /init
            r = client2.get('/')
            assert r.status_code == 302 and r.headers['Location'].endswith('/chat/init'), \
                '带前缀时根路径应跳转到 /chat/init'

            # 初始化页应在前缀下可访问，且 ping 请求 URL 带上前缀
            r = client2.get('/chat/init')
            assert r.status_code == 200, '带前缀时初始化页应可访问'
            assert b"fetch('/chat/init/ping'" in r.data, '初始化页 JS 应包含带前缀的 ping URL'

            # 数据库测试接口在前缀下应可用（修复前为 404）
            r = client2.post('/chat/init/ping', json={
                'db_ip': '127.0.0.1', 'db_port': '27017', 'db_user': '', 'db_pass': ''})
            assert r.status_code == 200, '带前缀时 /init/ping 应返回 200'

            # 带前缀初始化
            r = client2.post('/chat/init', data={
                'db_ip': '127.0.0.1', 'db_port': '27017', 'db_user': '', 'db_pass': '',
                'server_ip': '127.0.0.1:5000',
                'admin_user': 'admin', 'admin_pass': 'admin123',
                'admin_pass_confirm': 'admin123', 'invite_count': '1',
                'base_path': '/chat',
            })
            assert r.status_code == 200, '带前缀初始化应成功'
            cfg2 = json.load(open(os.path.join(tmp2, 'config.json'), encoding='utf-8'))
            assert cfg2.get('base_path') == '/chat', '初始化应保存 base_path=/chat'
            # 前缀未变更：完成页登录链接指向当前挂载，且无重启提示
            assert b'href="/chat/"' in r.data, '完成页登录链接应指向 /chat/'
            assert '重启服务' not in r.data.decode('utf-8'), '前缀未变更时不应提示重启'

            # 带前缀登录页
            r = client2.get('/chat/')
            assert r.status_code == 200 and b'login' in r.data.lower(), '应返回登录页'
            assert b"cursor:url('/chat/static/cur-default.png')" in r.data, \
                '带前缀时鼠标指针 URL 应带上前缀'

            # 裸前缀（无尾斜杠）应相对重定向到 /chat/（修复前为绝对 308 URL）
            r = client2.get('/chat')
            assert r.status_code == 302 and r.headers['Location'] == '/chat/', \
                'GET /chat 应 302 相对跳转到 /chat/'

            # ============ 场景 B：删掉 config.json 重新初始化，前缀应被清空 ============
            os.remove(os.path.join(tmp2, 'config.json'))
            # 服务未重启，state.settings 仍持有旧前缀 /chat（复现旧 bug 的条件）

            r = client2.get('/chat/init')
            assert r.status_code == 200, '删除 config.json 后初始化页仍应可访问'

            # base_path 留空提交（用户想从根路径重来）
            r = client2.post('/chat/init', data={
                'db_ip': '127.0.0.1', 'db_port': '27017', 'db_user': '', 'db_pass': '',
                'server_ip': '127.0.0.1:5000',
                'admin_user': 'admin2', 'admin_pass': 'admin123',
                'admin_pass_confirm': 'admin123', 'invite_count': '1',
                'base_path': '',
            })
            assert r.status_code == 200, '重新初始化应成功'
            cfg2 = json.load(open(os.path.join(tmp2, 'config.json'), encoding='utf-8'))
            assert cfg2.get('base_path') == '', 'base_path 留空时不应回退到内存中的旧前缀（修复点）'
            # 前缀发生了变更（/chat -> ''）：完成页应提示重启，且登录链接指向当前实际挂载
            html2 = r.data.decode('utf-8')
            assert '重启服务' in html2, '前缀变更时应提示重启生效'
            assert 'href="/chat/"' in html2, '重启前登录链接应指向当前实际挂载 /chat/'
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)

        # ============ 场景 C：前缀规范化与端口配置 ============
        tmp3 = tempfile.mkdtemp(prefix='chatter_test_norm_')
        try:
            app3 = create_app(data_dir=tmp3, base_path='/chat')
            client3 = app3.test_client()

            # 输入不带前导斜杠、带尾斜杠的前缀 + 自定义端口
            r = client3.post('/chat/init', data={
                'db_ip': '127.0.0.1', 'db_port': '27017', 'db_user': '', 'db_pass': '',
                'server_ip': '127.0.0.1:9090',
                'admin_user': 'admin', 'admin_pass': 'admin123',
                'admin_pass_confirm': 'admin123', 'invite_count': '1',
                'base_path': 'chat/', 'port': '9090',
            })
            assert r.status_code == 200, '初始化（前缀+端口）应成功'
            cfg3 = json.load(open(os.path.join(tmp3, 'config.json'), encoding='utf-8'))
            assert cfg3.get('base_path') == '/chat', '"chat/" 应规范化为 "/chat"'
            assert cfg3.get('port') == 9090, '初始化应保存端口 9090'
            assert '9090' in r.data.decode('utf-8'), '完成页应展示保存的端口'

            # 裸前缀相对重定向
            r = client3.get('/chat')
            assert r.status_code == 302 and r.headers['Location'] == '/chat/', \
                '规范化前缀后 GET /chat 仍应相对跳转'
            assert client3.get('/chat/').status_code == 200, '前缀下页面应可访问'
        finally:
            shutil.rmtree(tmp3, ignore_errors=True)

        # ============ 场景 D：端口校验（非法端口不写库） ============
        tmp4 = tempfile.mkdtemp(prefix='chatter_test_port_')
        try:
            app4 = create_app(data_dir=tmp4)
            client4 = app4.test_client()
            r = client4.post('/init', data={
                'db_ip': '127.0.0.1', 'db_port': '27017', 'db_user': '', 'db_pass': '',
                'server_ip': '127.0.0.1',
                'admin_user': 'admin', 'admin_pass': 'admin123',
                'admin_pass_confirm': 'admin123', 'invite_count': '1',
                'base_path': '', 'port': '99999',
            })
            assert r.status_code == 200 and '端口' in r.data.decode('utf-8'), \
                '非法端口应重新渲染并提示'
            assert not os.path.exists(os.path.join(tmp4, 'config.json')), \
                '非法端口不应写入配置'
        finally:
            shutil.rmtree(tmp4, ignore_errors=True)

        # ============ 场景 E：C++ 预览（GB18030 编码 + 重名去重后缀） ============
        import io as _io
        old_static_dir = state.STATIC_DIR
        tmp_static = os.path.join(tmp, 'static')
        try:
            state.STATIC_DIR = tmp_static
            app5 = create_app(data_dir=tmp)
            client5 = app5.test_client()
            r = client5.post('/chatts', data={'username': 'admin', 'password': 'admin123'})
            assert r.status_code == 200, '登录失败'
            token5 = extract_token(r.data.decode('utf-8'))
            cpp_bytes = ('#include <iostream>\n// 中文注释：你好世界\n'
                         'int main() { return 0; }\n').encode('gbk')
            names = []
            for _ in range(2):
                r = client5.post('/chatts_file', data={
                    'file': (_io.BytesIO(cpp_bytes), 'main.cpp'),
                    'username': 'admin', 'update': token5,
                }, content_type='multipart/form-data')
                assert r.status_code == 200, 'C++ 文件上传失败'
                names.append(r.get_json()['message']['content'].split('::file::')[1])
            assert names[1] == 'main (1).cpp', '重名上传应生成去重后缀'
            for name in names:
                r = client5.get('/api/cpp-preview?filename=%s&update=%s' % (name, token5))
                assert r.status_code == 200, 'C++ 预览失败：%s' % name
                assert '中文注释' in r.get_json()['content'], \
                    'GB18030 中文内容应正确解码：%s' % name
        finally:
            state.STATIC_DIR = old_static_dir

        # ============ 场景 F：中文文件名上传与访问 ============
        import io as _io6
        old_static_dir6 = state.STATIC_DIR
        tmp_static6 = os.path.join(tmp, 'static')
        try:
            state.STATIC_DIR = tmp_static6
            app6 = create_app(data_dir=tmp)
            client6 = app6.test_client()
            r = client6.post('/chatts', data={'username': 'admin', 'password': 'admin123'})
            assert r.status_code == 200, '登录失败'
            token6 = extract_token(r.data.decode('utf-8'))
            text_bytes = '中文内容：你好世界\n'.encode('utf-8')
            r = client6.post('/chatts_file', data={
                'file': (_io6.BytesIO(text_bytes), '测试文档.txt'),
                'username': 'admin', 'update': token6,
            }, content_type='multipart/form-data')
            assert r.status_code == 200, '中文文件名上传失败'
            name = r.get_json()['message']['content'].split('::file::')[1]
            assert name == '测试文档.txt', '中文文件名应被保留：%r' % name
            file_hash = r.get_json()['message'].get('file_hash')
            file_size = r.get_json()['message'].get('file_size')
            assert file_hash and re.match(r'^[0-9a-f]{64}$', file_hash), \
                'file_hash 应为 64 位十六进制 SHA-256：%r' % file_hash
            assert file_size == len(text_bytes), 'file_size 应等于文件字节数：%r' % file_size
            r = client6.get('/static/uploads/' + name)
            assert r.status_code == 200, '中文文件名静态访问失败'
            assert '你好世界' in r.data.decode('utf-8'), '中文文件内容应可下载'
            import hashlib as _hashlib
            same = _hashlib.sha256(text_bytes).hexdigest()
            assert file_hash == same, 'file_hash 应为文件 SHA-256：%r != %r' % (file_hash, same)
            r2 = client6.post('/chatts_file', data={
                'file': (_io6.BytesIO(text_bytes), '同名文档.txt'),
                'username': 'admin', 'update': token6,
            }, content_type='multipart/form-data')
            assert r2.status_code == 200, '重复内容上传失败'
            assert r2.get_json()['message'].get('file_hash') == same, \
                '相同内容两次上传 file_hash 应一致'
            r = client6.post('/chat/emoji/upload', data={
                'file': (_io6.BytesIO(b'x'), '表情包.png'),
                'username': 'admin', 'update': token6,
            }, content_type='multipart/form-data')
            assert r.status_code == 200, '中文表情包文件名上传失败'
            assert r.get_json()['filename'] == '表情包.png', '中文表情包名应被保留'
            r = client6.get('/chat/emoji/static/admin/表情包.png')
            assert r.status_code == 200, '中文表情包静态访问失败'
        finally:
            state.STATIC_DIR = old_static_dir6

        print('OK: 冒烟测试全部通过（15 项 + 前缀场景 A/B + 规范化场景 C/D + C++ 预览场景 E + 中文文件名场景 F）')
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
