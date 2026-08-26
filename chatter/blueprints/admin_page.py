"""管理面板页面：独立页 /admin 与聊天室弹窗内容片段 /admin/content。"""
from flask import render_template, request, redirect

from .. import auth, permissions, state
from . import make_blueprint

bp = make_blueprint('admin_page')


@bp.route('/admin')
def admin_page():
    username = auth.authenticate_request()
    if not username or not permissions.has_permission(username, 'admin.panel'):
        return redirect(state.base_path + '/')
    update = request.args.get('update') or ''
    return render_template(
        'admin.html',
        username=username,
        update=update,
        is_admin=permissions.is_admin(username),
        permissions=permissions.expanded_permissions(username),
    )


@bp.route('/admin/content')
def admin_content():
    """聊天室管理弹窗的页面片段（需带 token 访问）。"""
    if not auth.authenticate_request():
        return auth.json_error('认证失败', 401)
    # strip：去除 Jinja 渲染产生的首尾换行，避免片段注入 pre-wrap 容器时出现幻影空行
    return render_template('admin_content.html', update=request.args.get('update') or '').strip()
