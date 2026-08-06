# -*- coding: utf-8 -*-
"""hello_world 示例插件（文件夹式）。

演示能力：
- register_blueprint：新增独立页面
- add_command：新增聊天命令 command: hello
- add_css / add_js：注入聊天室外观与脚本
- add_tool_link：工具弹窗加入口
- on 钩子：message_send（记录插件收到的消息）
"""
from flask import Blueprint

# 插件配置（可通过管理面板修改）
PLUGIN_ACCENT = 'limegreen'


def on_load(ctx):
    # 1. 新增服务：/plugins/hello_world/about 页面
    bp = Blueprint('hello_world_pages', __name__)

    @bp.route('/plugins/hello_world/about')
    def about():
        return '<h1>Hello World 插件</h1><p>这是一个由插件系统提供的新页面。</p>'

    ctx.register_blueprint(bp)

    # 2. 新增聊天命令：command: hello
    def cmd_hello(username, parts, d_time, command_str):
        from chatter import messages
        target = parts[1] if len(parts) > 1 else username
        return messages.add_system_message('%s 向 %s 打了个招呼' % (username, target))

    ctx.add_command('hello', cmd_hello,
                    permission=None,
                    description='打个招呼：hello [用户名]')

    # 3. 注入外观 CSS（修改聊天室外观）
    ctx.add_css('''
        .chat-header p { letter-spacing: 6px !important; }
    ''')

    # 4. 注入 JS（修改聊天室功能）
    ctx.add_js('''
        // 在控制台输出插件加载状态
        console.log('[plugin:hello_world] loaded, base_path=' + BASE_PATH);
    ''')

    # 5. 工具集链接（以 / 开头按根路径定位，不再追加 base_path）
    ctx.add_tool_link('Hello World 插件页', '/plugins/hello_world/about')

    # 6. 钩子：消息发送时记录
    def on_message(document, username):
        print('[plugin:hello_world] message from', username, ':', document.get('content'))

    ctx.on('message_send', on_message)
