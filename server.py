"""syh's chatter —— 启动入口。

独立运行：python server.py
嵌入式使用见 chatter 包文档（create_app / register_into）。
"""
from chatter import create_app, state

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(state.settings.get('port', 5000)), debug=False)
