// syh's chatter 管理面板前端
// 弹窗内：聊天室 fetch /admin/content 片段 + 本脚本 + ChatterAdmin.init()
// 独立页：admin.html 直接包含本脚本（auto-init）
//
// 安全约定：
// - 所有对话框为自研组件（不使用原生 prompt/confirm/alert），动态内容一律 textContent 写入；
// - 列表渲染中的插值一律经 esc() 转义，杜绝 HTML 注入。
(function () {
    'use strict';

    const cfg = window.CHAT_CONFIG || {};
    const BASE = cfg.base_path || '';
    const token = cfg.update || '';

    // ---------------- 基础工具 ----------------

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function truncate(text, max) {
        text = String(text || '');
        return text.length > max ? text.slice(0, max) + '…' : text;
    }

    function formatBytes(n) {
        n = Number(n);
        if (!Number.isFinite(n) || n < 0) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let i = 0;
        while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
        return (i ? n.toFixed(1) : String(Math.round(n))) + ' ' + units[i];
    }

    function api(path, method, body) {
        // token 统一随 query 携带（服务端 request_token 优先读 args），并加 header 兜底
        const opts = {
            method: method || 'GET',
            headers: { 'Content-Type': 'application/json', 'X-Chat-Token': token || '' },
        };
        const sep = path.indexOf('?') === -1 ? '?' : '&';
        const url = BASE + path + sep + 'update=' + encodeURIComponent(token || '');
        if (body !== undefined) {
            opts.body = JSON.stringify(Object.assign({ username: cfg.username, update: token }, body));
        }
        return fetch(url, opts).then(function (r) {
            return r.json().then(function (data) {
                if (!r.ok || !data.ok) {
                    const err = new Error(data.error || ('请求失败 (' + r.status + ')'));
                    err.status = r.status;
                    throw err;
                }
                return data;
            });
        });
    }

    let toastTimer = null;
    let toastHideTimer = null;
    function toast(message, isError) {
        const el = document.getElementById('adminToast');
        if (!el) { adminAlert(message); return; }
        clearTimeout(toastTimer);
        clearTimeout(toastHideTimer);
        el.textContent = message;
        el.className = 'admin-toast' + (isError ? ' error' : '');
        el.hidden = false;
        toastTimer = setTimeout(function () {
            el.classList.add('admin-toast-out');
            toastHideTimer = setTimeout(function () {
                el.hidden = true;
                el.classList.remove('admin-toast-out');
            }, 220);
        }, 3000);
    }

    function page(name) {
        return document.getElementById('tab-' + name);
    }

    function setLoading(name) {
        const el = page(name);
        if (el) el.innerHTML = '<div class="admin-loading">加载中</div>';
    }

    // ---------------- 二级跳转导航 ----------------
    // 一级：横向滚动菜单页；二级：分区内容页（返回按钮跳回一级）

    const SECTION_TITLES = {
        users: '用户',
        groups: '权限组',
        plugins: '插件',
        uploads: '上传',
        traffic: '流量',
        database: '数据库',
        settings: '设置',
        tools: '工具',
    };
    let currentSection = null;

    function showMenu() {
        const menuPage = document.getElementById('adminMenuPage');
        const sectionPage = document.getElementById('adminSectionPage');
        if (!menuPage || !sectionPage) return;
        sectionPage.classList.remove('active');
        menuPage.classList.add('active');
        currentSection = null;
    }

    function switchTab(name) {
        const menuPage = document.getElementById('adminMenuPage');
        const sectionPage = document.getElementById('adminSectionPage');
        if (!menuPage || !sectionPage) return;
        menuPage.classList.remove('active');
        sectionPage.classList.add('active');
        document.querySelectorAll('.admin-tab-page').forEach(function (el) {
            el.classList.toggle('active', el.id === 'tab-' + name);
        });
        const nameEl = document.getElementById('adminSectionName');
        if (nameEl) nameEl.textContent = SECTION_TITLES[name] || name;
        currentSection = name;
        setLoading(name);
        loaders[name]();
    }

    // ---------------- 自写对话框（替代原生 prompt/confirm/alert） ----------------
    // buildDialog(options) -> Promise
    //   resolve：confirm=true/false；prompt=字符串或 null；alert=true
    // 安全：标题/消息/输入值全部经 textContent/value 写入，无任何 innerHTML 注入路径。

    const FOCUSABLE = 'button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])';

    function buildDialog(options) {
        options = options || {};
        return new Promise(function (resolve) {
            let settled = false;
            const overlay = document.createElement('div');
            overlay.className = 'admin-dialog-overlay';
            overlay.setAttribute('role', 'dialog');
            overlay.setAttribute('aria-modal', 'true');

            const card = document.createElement('div');
            card.className = 'admin-dialog-card';

            const titlebar = document.createElement('div');
            titlebar.className = 'admin-dialog-titlebar';
            const titleEl = document.createElement('span');
            titleEl.textContent = options.title || '提示';
            const closeBtn = document.createElement('button');
            closeBtn.type = 'button';
            closeBtn.className = 'admin-dialog-close';
            closeBtn.textContent = '✕';
            closeBtn.setAttribute('aria-label', '关闭');
            titlebar.append(titleEl, closeBtn);

            const body = document.createElement('div');
            body.className = 'admin-dialog-body';
            if (options.message) {
                const msg = document.createElement('div');
                msg.className = 'admin-dialog-message';
                msg.textContent = String(options.message);
                body.appendChild(msg);
            }
            let input = null;
            let hint = null;
            if (options.input) {
                input = document.createElement('input');
                input.className = 'admin-dialog-input';
                input.type = options.input.type === 'password' ? 'password' : 'text';
                input.value = options.input.value != null ? String(options.input.value) : '';
                if (options.input.placeholder) input.placeholder = options.input.placeholder;
                if (options.input.maxlength) input.maxLength = options.input.maxlength;
                input.setAttribute('spellcheck', 'false');
                input.setAttribute('autocomplete', 'off');
                body.appendChild(input);
                hint = document.createElement('div');
                hint.className = 'admin-dialog-hint';
                hint.textContent = options.input.hint || '';
                body.appendChild(hint);
            }

            const actions = document.createElement('div');
            actions.className = 'admin-dialog-actions';
            const cancelText = options.cancelText != null ? options.cancelText : '取消';
            const confirmText = options.confirmText || '确认';
            let cancelBtn = null;
            if (!options.alertOnly) {
                cancelBtn = document.createElement('button');
                cancelBtn.type = 'button';
                cancelBtn.className = 'admin-btn';
                cancelBtn.textContent = cancelText;
            }
            const confirmBtn = document.createElement('button');
            confirmBtn.type = 'button';
            confirmBtn.className = 'admin-btn' + (options.danger ? ' admin-btn-danger' : ' admin-btn-primary');
            confirmBtn.textContent = confirmText;
            if (cancelBtn) actions.appendChild(cancelBtn);
            actions.appendChild(confirmBtn);

            card.append(titlebar, body, actions);
            overlay.appendChild(card);
            document.body.appendChild(overlay);

            function finish(value) {
                if (settled) return;
                settled = true;
                document.removeEventListener('keydown', onKeydown, true);
                overlay.classList.add('admin-dialog-closing');
                setTimeout(function () {
                    if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
                }, 180);
                resolve(value);
            }

            function setHintError(text) {
                if (!hint) return;
                hint.textContent = text;
                hint.classList.toggle('is-error', !!text);
                if (input) { input.focus(); input.select(); }
            }

            function doConfirm() {
                if (input) {
                    const value = input.value;
                    if (options.validate) {
                        const err = options.validate(value);
                        if (err) { setHintError(err); return; }
                    }
                    finish(value);
                } else {
                    finish(true);
                }
            }
            function doCancel() { finish(input ? null : false); }

            confirmBtn.addEventListener('click', doConfirm);
            if (cancelBtn) cancelBtn.addEventListener('click', doCancel);
            closeBtn.addEventListener('click', doCancel);
            overlay.addEventListener('mousedown', function (e) {
                if (e.target === overlay) doCancel();
            });
            card.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' && e.target !== confirmBtn) {
                    e.preventDefault();
                    doConfirm();
                }
            });

            // ESC 关闭 + Tab 焦点圈闭（模态对话框，焦点不允许逃出）
            function onKeydown(e) {
                if (e.key === 'Escape') { e.stopPropagation(); doCancel(); return; }
                if (e.key === 'Tab') {
                    const items = Array.prototype.filter.call(
                        card.querySelectorAll(FOCUSABLE),
                        function (el) { return !el.disabled && el.offsetParent !== null; });
                    if (!items.length) return;
                    const first = items[0];
                    const last = items[items.length - 1];
                    if (e.shiftKey && document.activeElement === first) {
                        e.preventDefault(); last.focus();
                    } else if (!e.shiftKey && document.activeElement === last) {
                        e.preventDefault(); first.focus();
                    }
                }
            }
            document.addEventListener('keydown', onKeydown, true);

            (input || confirmBtn).focus();
            if (input && input.value) input.select();
        });
    }

    function adminConfirm(message, options) {
        options = options || {};
        return buildDialog({
            title: options.title || '确认操作',
            message: message,
            danger: options.danger !== false,
            confirmText: options.confirmText || '确认',
            cancelText: options.cancelText,
        }).then(function (v) { return v === true; });
    }

    function adminPrompt(message, options) {
        options = options || {};
        return buildDialog({
            title: options.title || '输入',
            message: message,
            input: {
                value: options.value,
                placeholder: options.placeholder,
                type: options.type,
                maxlength: options.maxlength,
                hint: options.hint,
            },
            validate: options.validate,
            confirmText: options.confirmText || '确认',
        }).then(function (v) { return typeof v === 'string' ? v : null; });
    }

    function adminAlert(message, options) {
        options = options || {};
        return buildDialog({
            title: options.title || '提示',
            message: message,
            alertOnly: true,
            danger: !!options.danger,
            confirmText: options.confirmText || '知道了',
        }).then(function () { return true; });
    }

    // ---------------- 用户 ----------------

    function groupOptions(groups, selected) {
        const names = Object.keys(groups);
        if (names.indexOf(selected) === -1) names.push(selected);
        return names.map(function (name) {
            return '<option value="' + esc(name) + '"' + (name === selected ? ' selected' : '') + '>' + esc(name) + '</option>';
        }).join('');
    }

    function loadUsers() {
        const el = page('users');
        Promise.all([api('/admin/api/users'), api('/admin/api/groups')]).then(function (results) {
            const userData = results[0];
            const users = userData.users;
            const groups = results[1].groups;
            const defaultGroup = results[1].default_group;
            const actor = userData.actor;
            const initialAdmin = userData.initial_admin;
            let html =
                '<div class="admin-toolbar"><span>共 ' + users.length + ' 名用户</span>' +
                '<span class="admin-toolbar-right"><input type="number" id="inviteCount" value="1" min="1" max="50" class="admin-input admin-input-sm">' +
                '<button class="admin-btn" id="inviteBtn">生成邀请码</button></span></div>' +
                '<div id="inviteResult"></div>';
            html += '<table class="admin-table"><thead><tr><th>用户名</th><th>颜色</th><th>权限组</th><th>管理</th><th>操作</th></tr></thead><tbody>';
            users.forEach(function (u) {
                const isSelf = u.username === actor;
                const isInitial = u.username === initialAdmin;
                const protectedRow = isSelf || isInitial || u.is_admin;
                const badges = (isInitial ? '<span class="admin-badge admin-badge-initial">初始管理员</span>' : '') +
                    (isSelf ? '<span class="admin-badge admin-badge-self">我</span>' : '');
                html += '<tr>' +
                    '<td>' + esc(u.username) + badges + '</td>' +
                    '<td><input type="color" class="admin-color" data-user="' + esc(u.username) + '" value="' + esc(u.color) + '"></td>' +
                    '<td><select class="admin-group-sel" data-user="' + esc(u.username) + '"' + (protectedRow ? ' disabled' : '') + '>' + groupOptions(groups, u.group) + '</select>' +
                    (u.group === defaultGroup ? '<div class="admin-hint">默认组</div>' : '') + '</td>' +
                    '<td>' + (u.is_admin ? '<svg class="icon" aria-hidden="true"><use href="#i-check"/></svg>' : '') + '</td>' +
                    '<td class="admin-ops">' +
                    '<button class="admin-btn admin-btn-sm" data-act="rename" data-user="' + esc(u.username) + '"' + (isSelf ? ' disabled' : '') + '>改名</button> ' +
                    '<button class="admin-btn admin-btn-sm" data-act="password" data-user="' + esc(u.username) + '">密码</button> ' +
                    (protectedRow
                        ? '<span class="admin-hint admin-protected">受保护</span>'
                        : '<button class="admin-btn admin-btn-sm admin-btn-danger" data-act="delete" data-user="' + esc(u.username) + '">删除</button>') +
                    '</td></tr>';
            });
            html += '</tbody></table>';
            el.innerHTML = html;

            el.querySelector('#inviteBtn').addEventListener('click', function () {
                const count = parseInt(el.querySelector('#inviteCount').value, 10) || 1;
                api('/admin/api/invites', 'POST', { count: count }).then(function (data) {
                    el.querySelector('#inviteResult').innerHTML =
                        '<div class="admin-codes">' + data.codes.map(function (code) {
                            return '<span class="admin-code">' + esc(code) + '</span>';
                        }).join('') + '</div>';
                    toast('已生成 ' + data.codes.length + ' 个邀请码');
                }).catch(function (err) { toast(err.message, true); });
            });

            el.querySelectorAll('.admin-color').forEach(function (input) {
                input.addEventListener('change', function () {
                    api('/admin/api/users/color', 'POST', { username: input.getAttribute('data-user'), color: input.value })
                        .then(function () { toast('颜色已更新'); })
                        .catch(function (err) { toast(err.message, true); });
                });
            });

            el.querySelectorAll('.admin-group-sel').forEach(function (select) {
                select.addEventListener('change', function () {
                    api('/admin/api/users/group', 'POST', { username: select.getAttribute('data-user'), group: select.value })
                        .then(function () { toast('权限组已更新'); loadUsers(); })
                        .catch(function (err) { toast(err.message, true); loadUsers(); });
                });
            });

            el.querySelectorAll('[data-act]').forEach(function (btn) {
                const user = btn.getAttribute('data-user');
                btn.addEventListener('click', function () {
                    const act = btn.getAttribute('data-act');
                    if (act === 'rename') {
                        // 自写输入对话框：预填当前用户名，校验非空且与原名不同
                        adminPrompt(null, {
                            title: '重命名用户',
                            message: '将「' + user + '」改名为：',
                            value: user,
                            maxlength: 32,
                            validate: function (v) {
                                v = v.trim();
                                if (!v) return '用户名不能为空';
                                if (v === user) return '新用户名与原用户名相同';
                                return '';
                            },
                        }).then(function (name) {
                            if (name === null) return;
                            name = name.trim();
                            api('/admin/api/users/rename', 'POST', { username: user, new_name: name })
                                .then(function () { toast('已改名'); loadUsers(); })
                                .catch(function (err) { toast(err.message, true); });
                        });
                    } else if (act === 'password') {
                        adminPrompt(null, {
                            title: '重置密码',
                            message: '为用户「' + user + '」设置新密码：',
                            type: 'password',
                            hint: '至少 1 个字符；提交后立即生效',
                            validate: function (v) {
                                if (!v) return '密码不能为空';
                                return '';
                            },
                        }).then(function (pw) {
                            if (pw === null) return;
                            api('/admin/api/users/password', 'POST', { username: user, new_password: pw })
                                .then(function () { toast('密码已重置'); })
                                .catch(function (err) { toast(err.message, true); });
                        });
                    } else if (act === 'delete') {
                        adminConfirm('确定删除用户「' + user + '」吗？\n该用户的登录会话将被注销，此操作不可撤销。', {
                            title: '删除用户',
                            confirmText: '删除',
                        }).then(function (ok) {
                            if (!ok) return;
                            api('/admin/api/users/delete', 'POST', { username: user })
                                .then(function () { toast('已删除'); loadUsers(); })
                                .catch(function (err) { toast(err.message, true); });
                        });
                    }
                });
            });
        }).catch(function (err) {
            el.innerHTML = '<div class="admin-error">加载失败：' + esc(err.message) + '</div>';
        });
    }

    // ---------------- 权限组 ----------------

    function loadGroups() {
        const el = page('groups');
        api('/admin/api/groups').then(function (data) {
            const groups = data.groups;
            const points = data.points;
            const defaultGroup = data.default_group;
            let html = '<div class="admin-toolbar"><span>权限组</span>' +
                '<span class="admin-toolbar-right"><button class="admin-btn" id="addGroupBtn">+ 新建组</button> ' +
                '<button class="admin-btn admin-btn-primary" id="saveGroupsBtn">保存</button></span></div>';
            html += '<div class="admin-group-grid">';
            Object.keys(groups).forEach(function (name) {
                const perms = groups[name] || [];
                const isAdminGroup = name === 'admin';
                html += '<div class="admin-group-card" data-group="' + esc(name) + '">' +
                    '<div class="admin-group-head"><input class="admin-input admin-group-name" value="' + esc(name) + '"' + (isAdminGroup ? ' readonly' : '') + '>' +
                    (!isAdminGroup ? '<button class="admin-btn admin-btn-sm admin-btn-danger admin-group-del">删除</button>' : '<span class="admin-hint">内置组</span>') + '</div>' +
                    '<div class="admin-perms">';
                points.forEach(function (point) {
                    const checked = perms.indexOf('*') !== -1 || perms.indexOf(point) !== -1;
                    html += '<label class="admin-perm"><input type="checkbox" value="' + esc(point) + '"' + (checked ? ' checked' : '') + (isAdminGroup ? ' disabled' : '') + '>' + esc(point) + '</label>';
                });
                if (!isAdminGroup) {
                    const starChecked = perms.indexOf('*') !== -1;
                    html += '<label class="admin-perm admin-perm-star"><input type="checkbox" class="perm-star" value="*"' + (starChecked ? ' checked' : '') + '>全部权限 (*)</label>';
                }
                html += '</div></div>';
            });
            html += '</div>';
            html += '<div class="admin-row"><span>新用户默认组：</span><select id="defaultGroupSel" class="admin-input">' +
                Object.keys(groups).map(function (name) {
                    return '<option value="' + esc(name) + '"' + (name === defaultGroup ? ' selected' : '') + '>' + esc(name) + '</option>';
                }).join('') + '</select></div>';
            el.innerHTML = html;

            el.querySelector('#addGroupBtn').addEventListener('click', function () {
                adminPrompt(null, {
                    title: '新建权限组',
                    message: '新权限组名称：',
                    placeholder: '例如 editor',
                    maxlength: 32,
                    validate: function (v) {
                        v = v.trim();
                        if (!v) return '名称不能为空';
                        if (groups[v]) return '该权限组已存在';
                        return '';
                    },
                }).then(function (name) {
                    if (name === null) return;
                    groups[name.trim()] = ['message.*'];
                    loadGroups();
                });
            });

            el.querySelector('#saveGroupsBtn').addEventListener('click', function () {
                const result = {};
                el.querySelectorAll('.admin-group-card').forEach(function (card) {
                    const name = card.querySelector('.admin-group-name').value.trim();
                    if (!name) return;
                    const perms = [];
                    card.querySelectorAll('input[type="checkbox"]:checked').forEach(function (box) {
                        perms.push(box.value);
                    });
                    result[name] = perms;
                });
                const def = el.querySelector('#defaultGroupSel').value;
                api('/admin/api/groups/save', 'POST', { groups: result })
                    .then(function () { return api('/admin/api/groups/default', 'POST', { group: def }); })
                    .then(function () { toast('权限组已保存'); loadGroups(); })
                    .catch(function (err) { toast(err.message, true); });
            });

            el.querySelectorAll('.admin-group-del').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    const card = btn.closest('.admin-group-card');
                    const name = card.getAttribute('data-group');
                    adminConfirm('删除权限组「' + name + '」？\n组内用户将退回默认组（保存后生效）。', {
                        title: '删除权限组',
                        confirmText: '删除',
                    }).then(function (ok) {
                        if (!ok) return;
                        delete groups[name];
                        loadGroups();
                    });
                });
            });
        }).catch(function (err) {
            el.innerHTML = '<div class="admin-error">加载失败：' + esc(err.message) + '</div>';
        });
    }

    // ---------------- 插件 ----------------

    function loadPlugins() {
        const el = page('plugins');
        api('/admin/api/plugins').then(function (data) {
            const plugins = data.plugins;
            let html = '<div class="admin-toolbar"><span>共 ' + plugins.length + ' 个插件</span>' +
                '<span class="admin-toolbar-right"><button class="admin-btn" id="reloadPluginsBtn">重载全部</button></span></div>';
            html += '<table class="admin-table"><thead><tr><th>名称</th><th>版本</th><th>作者</th><th>描述</th><th>启用</th><th>操作</th></tr></thead><tbody>';
            plugins.forEach(function (p) {
                html += '<tr>' +
                    '<td>' + esc(p.name) + '<div class="admin-hint">' + (p.loaded ? (p.kind === 'folder' ? '文件夹式' : '单文件式') : '未加载') + '</div></td>' +
                    '<td>' + esc(p.version) + '</td>' +
                    '<td>' + esc(p.author) + '</td>' +
                    '<td class="admin-desc">' + esc(p.description) + '</td>' +
                    '<td><input type="checkbox" class="admin-toggle" data-plugin="' + esc(p.name) + '"' + (p.enabled ? ' checked' : '') + '></td>' +
                    '<td class="admin-ops">' + (p.loaded ?
                        '<button class="admin-btn admin-btn-sm" data-reload="' + esc(p.name) + '">重载</button> ' : '') +
                    (p.has_config && p.loaded ?
                        '<button class="admin-btn admin-btn-sm" data-conf="' + esc(p.name) + '">配置</button> ' : '') +
                    '</td></tr>';
            });
            html += '</tbody></table>';
            html += '<div id="pluginConfigArea"></div>';
            el.innerHTML = html;

            el.querySelector('#reloadPluginsBtn').addEventListener('click', function () {
                api('/admin/api/plugins/reload', 'POST').then(function () {
                    toast('插件已重载'); loadPlugins();
                }).catch(function (err) { toast(err.message, true); });
            });

            el.querySelectorAll('.admin-toggle').forEach(function (box) {
                box.addEventListener('change', function () {
                    const name = box.getAttribute('data-plugin');
                    api('/admin/api/plugins/' + encodeURIComponent(name) + '/toggle', 'POST', { enabled: box.checked })
                        .then(function () { toast((box.checked ? '已启用 ' : '已禁用 ') + name); loadPlugins(); })
                        .catch(function (err) { toast(err.message, true); box.checked = !box.checked; });
                });
            });

            el.querySelectorAll('[data-reload]').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    const name = btn.getAttribute('data-reload');
                    api('/admin/api/plugins/' + encodeURIComponent(name) + '/reload', 'POST')
                        .then(function () { toast('已热重载 ' + name); loadPlugins(); })
                        .catch(function (err) { toast(err.message, true); });
                });
            });

            el.querySelectorAll('[data-conf]').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    const name = btn.getAttribute('data-conf');
                    const area = el.querySelector('#pluginConfigArea');
                    api('/admin/api/plugins/' + encodeURIComponent(name) + '/config')
                        .then(function (data) {
                            const json = JSON.stringify(data.config || {}, null, 2);
                            area.innerHTML =
                                '<div class="admin-conf-head">' + esc(name) + ' 配置（JSON）' +
                                '<button class="admin-btn admin-btn-sm" id="pluginConfSave">保存</button> ' +
                                '<button class="admin-btn admin-btn-sm" id="pluginConfCancel">关闭</button></div>' +
                                '<textarea class="admin-textarea" id="pluginConfText" spellcheck="false"></textarea>';
                            // JSON 文本经 textContent 写入，避免转义遗漏
                            area.querySelector('#pluginConfText').value = json;
                            area.querySelector('#pluginConfCancel').addEventListener('click', function () { area.innerHTML = ''; });
                            area.querySelector('#pluginConfSave').addEventListener('click', function () {
                                let parsed;
                                try { parsed = JSON.parse(area.querySelector('#pluginConfText').value); }
                                catch (e) { adminAlert('JSON 解析失败：' + e.message, { danger: true }); return; }
                                api('/admin/api/plugins/' + encodeURIComponent(name) + '/config', 'POST', { config: parsed })
                                    .then(function () { toast('配置已保存'); })
                                    .catch(function (err) { toast(err.message, true); });
                            });
                            area.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                        })
                        .catch(function (err) { toast(err.message, true); });
                });
            });
        }).catch(function (err) {
            el.innerHTML = '<div class="admin-error">加载失败：' + esc(err.message) + '</div>';
        });
    }

    // ---------------- 文件批量上传 ----------------

    const UPLOAD_BATCH_LIMIT = 20;

    function loadUploads() {
        const el = page('uploads');
        api('/admin/api/uploads').then(function (data) {
            let html = '<div class="admin-toolbar"><span id="uploadStats">共 ' + data.total + ' 个文件 · ' + formatBytes(data.total_size) + '</span>' +
                '<span class="admin-toolbar-right">' +
                '<button class="admin-btn" id="uploadPickBtn">选择文件</button>' +
                '<input type="file" id="uploadInput" multiple hidden>' +
                '<button class="admin-btn" id="uploadClearQueueBtn" disabled>清空队列</button>' +
                '<button class="admin-btn admin-btn-primary" id="uploadStartBtn" disabled>开始上传</button>' +
                '<button class="admin-btn" id="uploadRefreshBtn"><svg class="icon" aria-hidden="true"><use href="#i-refresh"/></svg> 刷新</button>' +
                '</span></div>';
            html += '<div class="upload-zone" id="uploadZone" tabindex="0" role="button" aria-label="选择或拖入文件">' +
                '<svg class="icon" aria-hidden="true"><use href="#i-upload"/></svg>' +
                '<div>拖拽文件到此处，或点击选择（可多选，单次最多 ' + UPLOAD_BATCH_LIMIT + ' 个）</div></div>';
            html += '<div class="upload-queue" id="uploadQueue"></div>';
            html += '<div class="upload-overall" id="uploadOverall" style="display:none">' +
                '<span id="uploadOverallText">0%</span>' +
                '<div class="upload-overall-track"><div class="upload-overall-fill" id="uploadOverallFill"></div></div></div>';
            html += '<div class="admin-section-title">服务器文件（static/uploads）</div><div id="uploadFileList"></div>';
            el.innerHTML = html;

            const input = el.querySelector('#uploadInput');
            const zone = el.querySelector('#uploadZone');
            const queueBox = el.querySelector('#uploadQueue');
            const overall = el.querySelector('#uploadOverall');
            const overallFill = el.querySelector('#uploadOverallFill');
            const overallText = el.querySelector('#uploadOverallText');
            const startBtn = el.querySelector('#uploadStartBtn');
            const clearBtn = el.querySelector('#uploadClearQueueBtn');
            const statsEl = el.querySelector('#uploadStats');

            // queue：{file, state: pending|uploading|done|failed, progress: 0..1, error}
            let queue = [];
            let uploading = false;

            function renderQueue() {
                queueBox.replaceChildren();
                queue.forEach(function (item, index) {
                    const row = document.createElement('div');
                    row.className = 'upload-item state-' + item.state;

                    const name = document.createElement('span');
                    name.className = 'upload-item-name';
                    name.textContent = item.file.name;
                    name.title = item.file.name;

                    const meta = document.createElement('span');
                    meta.className = 'upload-item-meta';
                    meta.textContent = formatBytes(item.file.size);

                    const state = document.createElement('span');
                    state.className = 'upload-item-state';
                    state.textContent = {
                        pending: '等待',
                        uploading: Math.round((item.progress || 0) * 100) + '%',
                        done: '完成',
                        failed: '失败',
                    }[item.state];
                    if (item.state === 'failed' && item.error) row.title = item.error;

                    if (item.state === 'pending') {
                        const remove = document.createElement('button');
                        remove.type = 'button';
                        remove.className = 'file-card-remove';
                        remove.setAttribute('aria-label', '移除 ' + item.file.name);
                        remove.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-x"/></svg>';
                        remove.addEventListener('click', function () {
                            if (uploading) return;
                            queue.splice(index, 1);
                            renderQueue();
                        });
                        row.append(name, meta, state, remove);
                    } else {
                        row.append(name, meta, state);
                    }

                    if (item.state === 'uploading' || item.state === 'done' || item.state === 'failed') {
                        const track = document.createElement('div');
                        track.className = 'upload-progress-track';
                        const fill = document.createElement('div');
                        fill.className = 'upload-progress-fill';
                        fill.style.width = Math.round((item.progress || (item.state === 'done' ? 1 : 0)) * 100) + '%';
                        track.appendChild(fill);
                        row.appendChild(track);
                    }
                    queueBox.appendChild(row);
                });
                startBtn.disabled = uploading || !queue.some(function (i) { return i.state === 'pending'; });
                clearBtn.disabled = uploading || !queue.length;
                const pendingCount = queue.filter(function (i) { return i.state === 'pending'; }).length;
                startBtn.textContent = uploading ? '上传中…' : ('开始上传' + (pendingCount ? '（' + pendingCount + '）' : ''));
            }

            function addToQueue(fileList) {
                const files = Array.prototype.slice.call(fileList || []);
                let added = 0;
                let dup = 0;
                let overflow = 0;
                files.forEach(function (file) {
                    const exists = queue.some(function (i) { return i.file.name === file.name && i.file.size === file.size; });
                    if (exists) { dup++; return; }
                    if (queue.length >= UPLOAD_BATCH_LIMIT) { overflow++; return; }
                    queue.push({ file: file, state: 'pending', progress: 0 });
                    added++;
                });
                renderQueue();
                if (added) toast('已加入队列 ' + added + ' 个文件');
                if (dup || overflow) {
                    const parts = [];
                    if (dup) parts.push(dup + ' 个重复');
                    if (overflow) parts.push(overflow + ' 个超出上限');
                    toast('已忽略：' + parts.join('、'), true);
                }
            }

            function uploadOneXHR(item, onProgress) {
                return new Promise(function (resolve) {
                    const fd = new FormData();
                    fd.append('files', item.file, item.file.name);
                    const xhr = new XMLHttpRequest();
                    xhr.open('POST', BASE + '/admin/api/uploads/batch?update=' + encodeURIComponent(token));
                    xhr.setRequestHeader('X-Chat-Token', token || '');
                    xhr.upload.addEventListener('progress', function (e) {
                        if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
                    });
                    xhr.addEventListener('load', function () {
                        try {
                            const data = JSON.parse(xhr.responseText);
                            if (xhr.status === 200 && data.ok && (!data.failed || !data.failed.length)) resolve({ ok: true });
                            else resolve({ ok: false, error: (data && data.error) || (data && data.failed && data.failed[0] && data.failed[0].error) || ('HTTP ' + xhr.status) });
                        } catch (e) { resolve({ ok: false, error: '响应解析失败' }); }
                    });
                    xhr.addEventListener('error', function () { resolve({ ok: false, error: '网络错误' }); });
                    xhr.send(fd);
                });
            }

            function startUpload() {
                if (uploading) return;
                const targets = queue.filter(function (i) { return i.state === 'pending'; });
                if (!targets.length) return;
                uploading = true;
                renderQueue();
                let done = 0;
                let failed = 0;
                const total = targets.length;
                overall.style.display = '';
                let chain = Promise.resolve();
                targets.forEach(function (item) {
                    chain = chain.then(function () {
                        item.state = 'uploading';
                        item.progress = 0;
                        renderQueue();
                        return uploadOneXHR(item, function (p) {
                            item.progress = p;
                            const row = queueBox.children[queue.indexOf(item)];
                            if (row) {
                                const stateEl = row.querySelector('.upload-item-state');
                                const fillEl = row.querySelector('.upload-progress-fill');
                                if (stateEl) stateEl.textContent = Math.round(p * 100) + '%';
                                if (fillEl) fillEl.style.width = Math.round(p * 100) + '%';
                            }
                            overallFill.style.width = Math.round(((done + p) / total) * 100) + '%';
                            overallText.textContent = Math.round(((done + p) / total) * 100) + '%';
                        }).then(function (result) {
                            done++;
                            if (result.ok) {
                                item.state = 'done';
                                item.progress = 1;
                            } else {
                                item.state = 'failed';
                                item.error = result.error;
                                failed++;
                            }
                            renderQueue();
                        });
                    });
                });
                chain.then(function () {
                    uploading = false;
                    renderQueue();
                    toast(failed ? ('上传完成：' + (total - failed) + ' 成功，' + failed + ' 失败') : ('全部上传成功（' + total + ' 个）'), !!failed);
                    setTimeout(function () {
                        queue = queue.filter(function (i) { return i.state !== 'done'; });
                        renderQueue();
                        overall.style.display = 'none';
                        overallFill.style.width = '0%';
                    }, 1200);
                    refreshList();
                });
            }

            function refreshList() {
                api('/admin/api/uploads').then(function (data) {
                    statsEl.textContent = '共 ' + data.total + ' 个文件 · ' + formatBytes(data.total_size);
                    const box = el.querySelector('#uploadFileList');
                    if (!data.files.length) {
                        box.innerHTML = '<div class="admin-hint">暂无文件</div>';
                        return;
                    }
                    let rows = '<table class="admin-table"><thead><tr><th>文件名</th><th>大小</th><th>修改时间</th><th>操作</th></tr></thead><tbody>';
                    data.files.forEach(function (f) {
                        rows += '<tr>' +
                            '<td class="admin-desc"><a href="' + BASE + '/static/uploads/' + encodeURIComponent(f.name) + '" target="_blank" rel="noopener" style="color:inherit;">' + esc(f.name) + '</a></td>' +
                            '<td>' + formatBytes(f.size) + '</td>' +
                            '<td>' + esc(new Date(f.mtime * 1000).toLocaleString()) + '</td>' +
                            '<td class="admin-ops">' +
                            '<button class="admin-btn admin-btn-sm" data-copy="' + esc(f.name) + '">复制链接</button> ' +
                            '<button class="admin-btn admin-btn-sm admin-btn-danger" data-del="' + esc(f.name) + '">删除</button></td></tr>';
                    });
                    rows += '</tbody></table>';
                    box.innerHTML = rows;

                    box.querySelectorAll('[data-copy]').forEach(function (btn) {
                        btn.addEventListener('click', function () {
                            const url = location.origin + BASE + '/static/uploads/' + encodeURIComponent(btn.getAttribute('data-copy'));
                            copyText(url);
                        });
                    });
                    box.querySelectorAll('[data-del]').forEach(function (btn) {
                        btn.addEventListener('click', function () {
                            const name = btn.getAttribute('data-del');
                            adminConfirm('删除文件「' + name + '」？\n聊天中引用该文件的链接将失效。', {
                                title: '删除文件',
                                confirmText: '删除',
                            }).then(function (ok) {
                                if (!ok) return;
                                api('/admin/api/uploads/delete', 'POST', { name: name })
                                    .then(function () { toast('已删除'); refreshList(); })
                                    .catch(function (err) { toast(err.message, true); });
                            });
                        });
                    });
                }).catch(function (err) {
                    el.querySelector('#uploadFileList').innerHTML = '<div class="admin-error">' + esc(err.message) + '</div>';
                });
            }

            function copyText(text) {
                const fallback = function () {
                    const ta = document.createElement('textarea');
                    ta.value = text;
                    ta.style.position = 'fixed';
                    ta.style.opacity = '0';
                    document.body.appendChild(ta);
                    ta.select();
                    try { document.execCommand('copy'); toast('链接已复制'); }
                    catch (e) { adminAlert('复制失败，请手动复制：\n' + text); }
                    document.body.removeChild(ta);
                };
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(text).then(function () { toast('链接已复制'); }, fallback);
                } else fallback();
            }

            zone.addEventListener('click', function () { input.click(); });
            zone.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
            });
            ['dragenter', 'dragover'].forEach(function (evt) {
                zone.addEventListener(evt, function (e) { e.preventDefault(); zone.classList.add('dragover'); });
            });
            ['dragleave', 'drop'].forEach(function (evt) {
                zone.addEventListener(evt, function (e) { e.preventDefault(); zone.classList.remove('dragover'); });
            });
            zone.addEventListener('drop', function (e) {
                addToQueue(e.dataTransfer.files);
            });
            el.querySelector('#uploadPickBtn').addEventListener('click', function () { input.click(); });
            input.addEventListener('change', function () { addToQueue(this.files); this.value = ''; });
            startBtn.addEventListener('click', startUpload);
            clearBtn.addEventListener('click', function () {
                if (uploading) return;
                queue = queue.filter(function (i) { return i.state !== 'done'; });
                renderQueue();
            });
            el.querySelector('#uploadRefreshBtn').addEventListener('click', refreshList);

            renderQueue();
            refreshList();
        }).catch(function (err) {
            el.innerHTML = '<div class="admin-error">加载失败：' + esc(err.message) + '</div>';
        });
    }

    // ---------------- 流量 ----------------

    function loadTraffic() {
        const el = page('traffic');
        api('/admin/api/traffic').then(function (data) {
            const t = data.traffic;
            const maxDay = Math.max.apply(null, t.recent_days.map(function (d) { return d.count; }).concat([1]));
            let html = '<div class="admin-cards">' +
                '<div class="admin-card"><div class="admin-card-value">' + t.total + '</div><div class="admin-card-label">总请求数</div></div>' +
                '<div class="admin-card"><div class="admin-card-value">' + t.today + '</div><div class="admin-card-label">今日请求</div></div>' +
                '<div class="admin-card"><div class="admin-card-value">' + t.unique_ips + '</div><div class="admin-card-label">独立 IP</div></div>' +
                '</div>';
            html += '<div class="admin-section-title">近 7 天请求量</div><div class="admin-bars">';
            t.recent_days.forEach(function (d) {
                const h = Math.max(4, Math.round(d.count / maxDay * 100));
                html += '<div class="admin-bar-col"><div class="admin-bar" data-h="' + h + '" style="height:4%"><span>' + d.count + '</span></div><div class="admin-bar-label">' + esc(d.day) + '</div></div>';
            });
            html += '</div>';
            html += '<div class="admin-section-title">访问最多的路径</div><table class="admin-table"><thead><tr><th>路径</th><th>次数</th></tr></thead><tbody>';
            t.top_paths.forEach(function (p) {
                html += '<tr><td>' + esc(p.path) + '</td><td>' + p.count + '</td></tr>';
            });
            html += '</tbody></table>';
            el.innerHTML = html;

            // 柱状图生长动画：先以 4% 占位，下一帧过渡到目标高度
            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    el.querySelectorAll('.admin-bar[data-h]').forEach(function (bar, i) {
                        setTimeout(function () { bar.style.height = bar.getAttribute('data-h') + '%'; }, i * 60);
                    });
                });
            });
        }).catch(function (err) {
            el.innerHTML = '<div class="admin-error">加载失败：' + esc(err.message) + '</div>';
        });
    }

    // ---------------- 数据库 ----------------

    function loadDatabase() {
        const el = page('database');
        api('/admin/api/database/stats').then(function (data) {
            const stats = data.stats;
            let html = '<div class="admin-cards">' +
                '<div class="admin-card"><div class="admin-card-value">' + stats.message_count + '</div><div class="admin-card-label">消息总数</div></div>' +
                '<div class="admin-card"><div class="admin-card-value">' + stats.collections.join('、') + '</div><div class="admin-card-label">集合</div></div>' +
                '</div>';
            html += '<div class="admin-section-title">数据库信息</div><pre class="admin-pre">' + esc(JSON.stringify(stats.db_stats, null, 2)) + '</pre>';
            html += '<div class="admin-section-title">最近消息</div>' +
                '<div class="admin-row"><input type="text" id="msgUserFilter" class="admin-input" placeholder="按用户名过滤（留空为全部）">' +
                '<button class="admin-btn" id="msgRefreshBtn">刷新</button></div>' +
                '<div id="msgList"></div>';
            html += '<div class="admin-section-title">危险操作</div>' +
                '<div class="admin-row"><input type="text" id="delUserMsgInput" class="admin-input" placeholder="删除某用户的全部消息（用户名）">' +
                '<button class="admin-btn admin-btn-danger" id="delUserMsgBtn">删除该用户消息</button></div>' +
                '<div class="admin-row"><button class="admin-btn admin-btn-danger" id="clearAllMsgBtn">清空全部消息</button></div>';
            el.innerHTML = html;

            function loadMessages() {
                const user = el.querySelector('#msgUserFilter').value.trim();
                const box = el.querySelector('#msgList');
                box.innerHTML = '<div class="admin-loading">加载中</div>';
                api('/admin/api/database/messages?user=' + encodeURIComponent(user) + '&limit=20').then(function (data) {
                    let rows = '<table class="admin-table"><thead><tr><th>时间</th><th>用户</th><th>内容</th></tr></thead><tbody>';
                    data.messages.forEach(function (m) {
                        rows += '<tr><td>' + esc(m.time) + '</td><td>' + esc(m.user) + '</td><td class="admin-desc">' + esc(truncate(m.content, 60)) + '</td></tr>';
                    });
                    rows += '</tbody></table>';
                    box.innerHTML = rows || '<div class="admin-hint">暂无消息</div>';
                }).catch(function (err) {
                    box.innerHTML = '<div class="admin-error">' + esc(err.message) + '</div>';
                });
            }
            el.querySelector('#msgRefreshBtn').addEventListener('click', loadMessages);
            loadMessages();

            el.querySelector('#delUserMsgBtn').addEventListener('click', function () {
                const user = el.querySelector('#delUserMsgInput').value.trim();
                if (!user) { toast('请输入用户名', true); return; }
                adminConfirm('删除用户「' + user + '」的全部消息？\n此操作不可撤销。', {
                    title: '删除用户消息',
                    confirmText: '删除',
                }).then(function (ok) {
                    if (!ok) return;
                    api('/admin/api/database/delete-user', 'POST', { username: user })
                        .then(function (data) { toast('已删除 ' + data.deleted + ' 条消息'); loadDatabase(); })
                        .catch(function (err) { toast(err.message, true); });
                });
            });
            el.querySelector('#clearAllMsgBtn').addEventListener('click', function () {
                adminConfirm('确定清空全部聊天记录吗？\n所有用户的消息都将被永久删除，此操作不可撤销！', {
                    title: '清空聊天记录',
                    confirmText: '全部清空',
                }).then(function (ok) {
                    if (!ok) return;
                    api('/admin/api/database/clear', 'POST')
                        .then(function () { toast('聊天记录已清空'); loadDatabase(); })
                        .catch(function (err) { toast(err.message, true); });
                });
            });
        }).catch(function (err) {
            el.innerHTML = '<div class="admin-error">加载失败：' + esc(err.message) + '</div>';
        });
    }

    // ---------------- 设置 ----------------

    const SETTINGS_FIELDS = ['site_title', 'server_ip', 'port', 'poll_interval', 'mute_default_seconds', 'base_path', 'admins'];

    function loadSettings() {
        const el = page('settings');
        api('/admin/api/settings').then(function (data) {
            const s = data.settings;
            let html = '<div class="admin-settings-form">';
            html += '<label class="admin-field"><span>站点标题</span><input type="text" id="set_site_title" class="admin-input" value="' + esc(s.site_title) + '"></label>';
            html += '<label class="admin-field"><span>服务器地址 (server_ip)</span><input type="text" id="set_server_ip" class="admin-input" value="' + esc(s.server_ip) + '"><small>如 127.0.0.1:5000</small></label>';
            html += '<label class="admin-field"><span>监听端口 (port)</span><input type="number" id="set_port" class="admin-input" value="' + esc(s.port) + '"></label>';
            html += '<label class="admin-field"><span>消息轮询间隔 (毫秒)</span><input type="number" id="set_poll_interval" class="admin-input" value="' + esc(s.poll_interval) + '"></label>';
            html += '<label class="admin-field"><span>默认禁言时长 (秒)</span><input type="number" id="set_mute_default_seconds" class="admin-input" value="' + esc(s.mute_default_seconds) + '"></label>';
            html += '<label class="admin-field"><span>挂载路径 (base_path)</span><input type="text" id="set_base_path" class="admin-input" value="' + esc(s.base_path) + '"><small>需重启服务生效，如 /chat</small></label>';
            html += '<label class="admin-field"><span>管理员列表 (admins，逗号分隔)</span><input type="text" id="set_admins" class="admin-input" value="' + esc((s.admins || []).join(', ')) + '"></label>';
            html += '</div><div class="admin-row"><button class="admin-btn admin-btn-primary" id="saveSettingsBtn">保存设置</button></div>';
            el.innerHTML = html;

            el.querySelector('#saveSettingsBtn').addEventListener('click', function () {
                const settings = {};
                SETTINGS_FIELDS.forEach(function (key) {
                    const input = el.querySelector('#set_' + key);
                    if (!input) return;
                    if (key === 'admins') {
                        settings[key] = input.value.split(/[,，]/).map(function (v) { return v.trim(); }).filter(Boolean);
                    } else if (key === 'port' || key === 'poll_interval' || key === 'mute_default_seconds') {
                        settings[key] = parseInt(input.value, 10);
                    } else {
                        settings[key] = input.value;
                    }
                });
                api('/admin/api/settings', 'POST', { settings: settings })
                    .then(function () { toast('设置已保存（部分项需重启服务生效）'); loadSettings(); })
                    .catch(function (err) { toast(err.message, true); });
            });
        }).catch(function (err) {
            el.innerHTML = '<div class="admin-error">加载失败：' + esc(err.message) + '</div>';
        });
    }

    // ---------------- 快捷工具 ----------------

    function loadTools() {
        const el = page('tools');
        api('/admin/api/tool-links').then(function (data) {
            const links = data.links || [];
            const removedKeys = [];
            let html = '<div class="admin-toolbar"><span>聊天室"工具集"弹窗中的链接（' + links.length + ' 条，含插件提供的链接；可编辑 / 禁用 / 排序 / 删除。地址以 / 开头表示根路径，如 /about，不再自动追加 base_path）</span>' +
                '<span class="admin-toolbar-right"><button class="admin-btn" id="addToolLinkBtn">+ 添加链接</button> ' +
                '<button class="admin-btn admin-btn-primary" id="saveToolLinksBtn">保存</button></span></div>';
            html += '<div id="toolLinksList" class="admin-tool-links">';
            links.forEach(function (link) {
                html += toolLinkRow(link);
            });
            html += '</div>';
            el.innerHTML = html;

            function toolLinkRow(link) {
                const isPlugin = !!(link.plugin && link.key);
                return '<div class="admin-tool-link-row' + (isPlugin ? ' is-plugin' : '') + '"' +
                    (isPlugin ? ' data-plugin="' + esc(link.plugin) + '" data-key="' + esc(link.key) + '"' : '') + '>' +
                    '<span class="admin-tool-drag-icon" draggable="true" title="拖拽排序">⠿</span>' +
                    '<input type="checkbox" class="admin-tool-enabled" title="是否在弹窗中显示"' + (link.enabled !== false ? ' checked' : '') + '>' +
                    '<input type="text" class="admin-input admin-input-icon" placeholder="图标" value="' + esc(link.icon || '') + '" title="emoji 或 #i-symbol（点 ▦ 从图标库选择）">' +
                    '<button type="button" class="admin-btn admin-btn-sm tool-icon-picker" title="从 SVG 图标库选择">▦</button>' +
                    '<input type="text" class="admin-input admin-input-title" placeholder="链接名称" value="' + esc(link.title || '') + '">' +
                    '<input type="text" class="admin-input admin-input-url" placeholder="https://... 或 /xxx（根路径）" value="' + esc(link.url || '') + '">' +
                    (isPlugin ? '<span class="admin-tool-badge" title="由插件提供">' + esc(link.plugin) + '</span>' : '') +
                    '<button class="admin-btn admin-btn-sm admin-btn-danger tool-link-del">删除</button></div>';
            }

            function collect() {
                return Array.prototype.map.call(el.querySelectorAll('.admin-tool-link-row'), function (row) {
                    const link = {
                        title: row.querySelector('.admin-input-title').value.trim(),
                        url: row.querySelector('.admin-input-url').value.trim(),
                        icon: row.querySelector('.admin-input-icon').value.trim(),
                        enabled: row.querySelector('.admin-tool-enabled').checked,
                    };
                    const key = row.getAttribute('data-key');
                    const plugin = row.getAttribute('data-plugin');
                    if (key && plugin) {
                        link.key = key;
                        link.plugin = plugin;
                    }
                    return link;
                }).filter(function (link) { return link.title && link.url; });
            }

            el.querySelector('#addToolLinkBtn').addEventListener('click', function () {
                const list = el.querySelector('#toolLinksList');
                list.insertAdjacentHTML('beforeend', toolLinkRow({}));
                bindRow(list.lastElementChild);
            });

            el.querySelector('#saveToolLinksBtn').addEventListener('click', function () {
                api('/admin/api/tool-links', 'POST', { links: collect(), removed: removedKeys })
                    .then(function () { toast('快捷工具链接已保存'); loadTools(); })
                    .catch(function (err) { toast(err.message, true); });
            });

            el.querySelectorAll('.tool-link-del').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    const row = btn.closest('.admin-tool-link-row');
                    if (!row) return;
                    const key = row.getAttribute('data-key');
                    if (key) removedKeys.push(key);
                    row.remove();
                });
            });

            // SVG 图标选择器：弹出 sprite 中全部 #i-* 图标的网格
            el.querySelectorAll('.tool-icon-picker').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    const input = btn.closest('.admin-tool-link-row').querySelector('.admin-input-icon');
                    openIconPicker(input);
                });
            });
            function openIconPicker(input) {
                let overlay = document.getElementById('toolIconPicker');
                if (overlay) overlay.remove();
                overlay = document.createElement('div');
                overlay.id = 'toolIconPicker';
                overlay.className = 'tool-icon-picker-overlay';
                const icons = Array.prototype.map.call(
                    document.querySelectorAll('svg use'), function (use) {
                        return use.getAttribute('href') || '';
                    }).filter(function (h) { return h && h.indexOf('#i-') === 0; });
                const seen = [];
                const uniq = icons.filter(function (h) { if (seen.indexOf(h) !== -1) return false; seen.push(h); return true; });
                let grid = '';
                uniq.forEach(function (href) {
                    grid += '<button type="button" class="tool-icon-opt" data-href="' + href + '" title="' + href.slice(1) + '">' +
                        '<svg class="icon" aria-hidden="true"><use href="' + href + '"/></svg></button>';
                });
                overlay.innerHTML = '<div class="tool-icon-picker-panel"><div class="tool-icon-picker-head">选择 SVG 图标' +
                    '<button type="button" class="tool-icon-picker-clear" title="清空图标">清空</button>' +
                    '<button type="button" class="tool-icon-picker-close" title="关闭">✕</button></div>' +
                    '<div class="tool-icon-picker-grid">' + grid + '</div></div>';
                document.body.appendChild(overlay);
                const close = function () { overlay.remove(); };
                overlay.addEventListener('click', function (e) {
                    if (e.target === overlay || e.target.closest('.tool-icon-picker-close')) return close();
                    const opt = e.target.closest('.tool-icon-opt');
                    if (!opt) return;
                    input.value = opt.getAttribute('data-href');
                    close();
                });
                overlay.querySelector('.tool-icon-picker-clear').addEventListener('click', function () {
                    input.value = '';
                    close();
                });
                document.addEventListener('keydown', function pickerEsc(e) {
                    if (e.key !== 'Escape') return;
                    close();
                    document.removeEventListener('keydown', pickerEsc);
                });
            }

            // 拖拽排序（HTML5 drag/drop，把手拖动）
            const list = el.querySelector('#toolLinksList');
            let dragRow = null;
            list.addEventListener('dragstart', function (e) {
                if (!e.target.closest('.admin-tool-drag-icon')) return;
                dragRow = e.target.closest('.admin-tool-link-row');
                e.dataTransfer.effectAllowed = 'move';
                dragRow.classList.add('admin-tool-dragging');
            });
            list.addEventListener('dragover', function (e) {
                if (!dragRow) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
            });
            list.addEventListener('drop', function (e) {
                e.preventDefault();
                if (!dragRow) return;
                const target = e.target.closest('.admin-tool-link-row');
                if (target && target !== dragRow) {
                    list.insertBefore(dragRow, target.nextSibling);
                }
                dragRow.classList.remove('admin-tool-dragging');
                dragRow = null;
            });
            list.addEventListener('dragend', function () {
                if (dragRow) dragRow.classList.remove('admin-tool-dragging');
                dragRow = null;
            });
        }).catch(function (err) {
            el.innerHTML = '<div class="admin-error">加载失败：' + esc(err.message) + '</div>';
        });
    }

    // ---------------- 加载器表 ----------------

    const loaders = {
        users: loadUsers,
        groups: loadGroups,
        plugins: loadPlugins,
        uploads: loadUploads,
        traffic: loadTraffic,
        database: loadDatabase,
        settings: loadSettings,
        tools: loadTools,
    };

    function init() {
        const root = document.querySelector('.admin-panel-root');
        if (!root || root.getAttribute('data-inited')) return;
        root.setAttribute('data-inited', '1');
        // 无 admin.uploads 权限时隐藏上传入口（后端仍会校验，双保险）
        if (Array.isArray(cfg.permissions) && cfg.permissions.indexOf('admin.uploads') === -1 &&
            cfg.permissions.indexOf('*') === -1) {
            document.querySelectorAll('.admin-menu-btn[data-tab="uploads"]').forEach(function (btn) {
                btn.style.display = 'none';
                btn.disabled = true;
            });
        }
        // 一级菜单 → 二级分区
        root.querySelectorAll('.admin-menu-btn').forEach(function (btn) {
            btn.addEventListener('click', function () { switchTab(btn.getAttribute('data-tab')); });
        });
        // 二级返回 → 一级菜单
        const backBtn = document.getElementById('adminBackBtn');
        if (backBtn) backBtn.addEventListener('click', showMenu);
        // 打开面板停留在一级菜单页，由用户选择分区进入（二级跳转）
    }

    window.ChatterAdmin = {
        init: init,
        switchTab: switchTab,
        showMenu: showMenu,
        refresh: function () {
            if (currentSection) switchTab(currentSection);
        },
    };

    // 独立页（admin.html）自动初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
