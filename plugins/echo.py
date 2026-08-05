# -*- coding: utf-8 -*-
"""echo 示例插件（单文件式）。

演示能力：
- PLUGIN_INFO 元信息
- on_load：注册命令、钩子
"""
import os

PLUGIN_INFO = {
    'name': 'echo',
    'version': '0.1.0',
    'author': 'syh',
    'description': '单文件示例插件：command: echo <内容> 将内容以系统消息回显；并在收到消息时记录日志。',
}


def on_load(ctx):
    # 命令：command: echo <内容>
    def cmd_echo(username, parts, d_time, command_str):
        from chatter import messages
        text = command_str[len('command: echo'):].strip()
        if not text:
            return None
        return messages.add_system_message('[echo] %s' % text)

    ctx.add_command('echo', cmd_echo,
                    permission='plugins.echo.echo',
                    description='回显内容：echo <内容>')

    # 钩子：消息发送时写入插件日志文件
    def on_message_send(document, username):
        try:
            log_path = os.path.join(ctx.directory, 'echo.log')
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write('%s | %s | %s\n' % (username, document.get('time'), document.get('content')))
        except OSError:
            pass

    ctx.on('message_send', on_message_send)
