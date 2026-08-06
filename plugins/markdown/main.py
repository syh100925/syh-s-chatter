# -*- coding: utf-8 -*-
"""markdown 渲染插件（文件夹式）。

启用插件即默认开启 Markdown 渲染（无需命令开关）：
- 文本消息按 Markdown 渲染：标题/列表/表格/引用/代码块（复用页面 highlight.js 高亮）
- 代码块头部提供「复制」按钮；「格式化」开关控制代码的智能格式化
  （统一缩进与空格规范化，Tab=4，影响显示与复制，默认开启，可关闭）
- 超过 10 行的代码块默认折叠，点击展开
- 「显示原文/显示Markdown」在消息右键菜单中切换

前端通过渲染钩子（window.__chatterRenderHooks，在 chat.js 之前注入）接管
文本消息气泡的内容渲染，注入文件：static/markdown.js 与 static/markdown.css。
"""


def on_load(ctx):
    ctx.add_css('static/markdown.css')
    ctx.add_js('static/markdown.js')
