// syh's chatter 管理面板前端
// 弹窗内：聊天室 fetch /admin/content 片段 + 本脚本 + ChatterAdmin.init()
// 独立页：admin.html 直接包含本脚本（auto-init）
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
    function toast(message, isError) {
        const el = document.getElementById('adminToast');
        if (!el) { alert(message); return; }
        el.textContent = message;
        el.className = 'admin-toast' + (isError ? ' error' : '');
        el.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(function () { el.hidden = true; }, 3000);
    }

    function page(name) {
        return document.getElementById('tab-' + name);
    }

    function setLoading(name) {
        const el = page(name);
        if (el) el.innerHTML = '<div class="admin-loading">加载中...</div>';
    }

    // ---------------- Tab 切换 ----------------

    function switchTab(name) {
        document.querySelectorAll('.admin-tab').forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('data-tab') === name);
        });
        document.querySelectorAll('.admin-tab-page').forEach(function (el) {
            el.classList.toggle('active', el.id === 'tab-' + name);
        });
        setLoading(name);
        loaders[name]();
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
                        const name = prompt('新用户名：', user);
                        if (!name || name === user) return;
                        api('/admin/api/users/rename', 'POST', { username: user, new_name: name })
                            .then(function () { toast('已改名'); loadUsers(); })
                            .catch(function (err) { toast(err.message, true); });
                    } else if (act === 'password') {
                        const pw = prompt('新密码（至少 1 个字符）：');
                        if (pw === null) return;
                        if (!pw) { toast('密码不能为空', true); return; }
                        api('/admin/api/users/password', 'POST', { username: user, new_password: pw })
                            .then(function () { toast('密码已重置'); })
                            .catch(function (err) { toast(err.message, true); });
                    } else if (act === 'delete') {
                        if (!confirm('确定删除用户 ' + user + ' 吗？此操作不可撤销。')) return;
                        api('/admin/api/users/delete', 'POST', { username: user })
                            .then(function () { toast('已删除'); loadUsers(); })
                            .catch(function (err) { toast(err.message, true); });
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
                const name = prompt('新权限组名称：');
                if (!name) return;
                if (groups[name]) { toast('该权限组已存在', true); return; }
                groups[name] = ['message.*'];
                loadGroups();
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
                    if (!confirm('删除权限组 ' + name + '？组内用户将退回默认组。')) return;
                    delete groups[name];
                    loadGroups();
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
                                '<textarea class="admin-textarea" id="pluginConfText" spellcheck="false">' + esc(json) + '</textarea>';
                            area.querySelector('#pluginConfCancel').addEventListener('click', function () { area.innerHTML = ''; });
                            area.querySelector('#pluginConfSave').addEventListener('click', function () {
                                let parsed;
                                try { parsed = JSON.parse(area.querySelector('#pluginConfText').value); }
                                catch (e) { toast('JSON 解析失败：' + e.message, true); return; }
                                api('/admin/api/plugins/' + encodeURIComponent(name) + '/config', 'POST', { config: parsed })
                                    .then(function () { toast('配置已保存'); })
                                    .catch(function (err) { toast(err.message, true); });
                            });
                        })
                        .catch(function (err) { toast(err.message, true); });
                });
            });
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
                html += '<div class="admin-bar-col"><div class="admin-bar" style="height:' + h + '%"><span>' + d.count + '</span></div><div class="admin-bar-label">' + esc(d.day) + '</div></div>';
            });
            html += '</div>';
            html += '<div class="admin-section-title">访问最多的路径</div><table class="admin-table"><thead><tr><th>路径</th><th>次数</th></tr></thead><tbody>';
            t.top_paths.forEach(function (p) {
                html += '<tr><td>' + esc(p.path) + '</td><td>' + p.count + '</td></tr>';
            });
            html += '</tbody></table>';
            el.innerHTML = html;
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
                box.innerHTML = '<div class="admin-loading">加载中...</div>';
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
                if (!confirm('删除用户 ' + user + ' 的全部消息？')) return;
                api('/admin/api/database/delete-user', 'POST', { username: user })
                    .then(function (data) { toast('已删除 ' + data.deleted + ' 条消息'); loadDatabase(); })
                    .catch(function (err) { toast(err.message, true); });
            });
            el.querySelector('#clearAllMsgBtn').addEventListener('click', function () {
                if (!confirm('清空全部聊天记录？此操作不可撤销！')) return;
                api('/admin/api/database/clear', 'POST')
                    .then(function () { toast('聊天记录已清空'); loadDatabase(); })
                    .catch(function (err) { toast(err.message, true); });
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
        traffic: loadTraffic,
        database: loadDatabase,
        settings: loadSettings,
        tools: loadTools,
    };

    function init() {
        const root = document.querySelector('.admin-panel-root');
        if (!root || root.getAttribute('data-inited')) return;
        root.setAttribute('data-inited', '1');
        root.querySelectorAll('.admin-tab').forEach(function (btn) {
            btn.addEventListener('click', function () { switchTab(btn.getAttribute('data-tab')); });
        });
        switchTab('users');
    }

    window.ChatterAdmin = { init: init, switchTab: switchTab, refresh: function () { switchTab(document.querySelector('.admin-tab.active').getAttribute('data-tab')); } };

    // 独立页（admin.html）自动初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
