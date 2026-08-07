// syh's chatter 前端主脚本（从 chat.html 抽取）
// 页面配置通过 window.CHAT_CONFIG 注入，见模板 <script>window.CHAT_CONFIG = ...</script>
const BASE_PATH = (window.CHAT_CONFIG && window.CHAT_CONFIG.base_path) || '';
const POLL_INTERVAL = (window.CHAT_CONFIG && window.CHAT_CONFIG.poll_interval) || 3000;

function u(path) { return BASE_PATH + path; }

// 权限判断：permissions 含 "*" 或具体权限点即视为拥有
function can(permission) {
    const list = (window.CHAT_CONFIG && window.CHAT_CONFIG.permissions) || [];
    return list.indexOf('*') !== -1 || list.indexOf(permission) !== -1;
}

        document.addEventListener('DOMContentLoaded', function() {

            // ================================================================
            //  1. 原有工具函数（复制、Toast 等）
            // ================================================================
            function copyToClipboard(text) {
                return new Promise((resolve, reject) => {
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        navigator.clipboard.writeText(text).then(resolve).catch(reject);
                    } else {
                        const textarea = document.createElement('textarea');
                        textarea.value = text;
                        textarea.style.position = 'fixed';
                        textarea.style.opacity = '0';
                        document.body.appendChild(textarea);
                        textarea.select();
                        try {
                            const ok = document.execCommand('copy');
                            document.body.removeChild(textarea);
                            if (ok) resolve();
                            else reject(new Error('execCommand failed'));
                        } catch (err) {
                            document.body.removeChild(textarea);
                            reject(err);
                        }
                    }
                });
            }

            function showCopyToast() {
                const t = document.getElementById('copyToast');
                t.classList.add('show');
                setTimeout(() => t.classList.remove('show'), 1500);
            }

            // ================================================================
            //  2. 外观设置（原有，略作保留）
            // ================================================================
            const settings = {
                theme: localStorage.getItem('theme') || 'dark',
                fontSize: parseInt(localStorage.getItem('fontSize')) || 16,
                highlightTheme: localStorage.getItem('highlightTheme') || 'auto',
                bubbleRadius: parseInt(localStorage.getItem('bubbleRadius')) || 0,
                messageFontSize: parseFloat(localStorage.getItem('messageFontSize')) || 0.9,
                avatarSize: parseInt(localStorage.getItem('avatarSize')) || 36,
                avatarBorderWidth: parseInt(localStorage.getItem('avatarBorderWidth')) || 2,
                onlineDotSize: parseInt(localStorage.getItem('onlineDotSize')) || 8,
            };
            const hlLink = document.getElementById('highlight-theme');

            function applyAllSettings() {
                document.documentElement.style.setProperty('--base-font-size', settings.fontSize + 'px');
                document.documentElement.style.setProperty('--bubble-radius', settings.bubbleRadius + 'px');
                document.documentElement.style.setProperty('--message-font-size', settings.messageFontSize + 'rem');
                document.documentElement.style.setProperty('--avatar-size', settings.avatarSize + 'px');
                document.documentElement.style.setProperty('--avatar-border-width', settings.avatarBorderWidth + 'px');
                document.documentElement.style.setProperty('--online-dot-size', settings.onlineDotSize + 'px');
                updateHighlightTheme();
            }

            function updateHighlightTheme() {
                let desired = settings.highlightTheme;
                if (desired === 'auto') desired = settings.theme === 'light' ? 'light' : 'dark';
                const href = desired === 'light' ? u('/static/js/highlight.js/styles/atom-one-light.min.css') :
                    u('/static/js/highlight.js/styles/atom-one-dark.min.css');
                if (hlLink.getAttribute('href') !== href) hlLink.setAttribute('href', href);
            }

            function saveAllSettings() {
                localStorage.setItem('theme', settings.theme);
                localStorage.setItem('fontSize', settings.fontSize);
                localStorage.setItem('highlightTheme', settings.highlightTheme);
                localStorage.setItem('bubbleRadius', settings.bubbleRadius);
                localStorage.setItem('messageFontSize', settings.messageFontSize);
                localStorage.setItem('avatarSize', settings.avatarSize);
                localStorage.setItem('avatarBorderWidth', settings.avatarBorderWidth);
                localStorage.setItem('onlineDotSize', settings.onlineDotSize);
            }
            function applyThemeState() {
                if (settings.theme === 'light') {
                    document.body.classList.add('light-theme');
                    document.getElementById('modeIndicator').textContent = '亮';
                } else {
                    document.body.classList.remove('light-theme');
                    document.getElementById('modeIndicator').textContent = '暗';
                }
                applyAllSettings();
                saveAllSettings();
            }
            applyThemeState();

            // 主题圆圈扩散动画：遮罩内承载"新主题克隆页"，入场动画随圆扩散依次播放
            // 真实页面保持旧主题直至扩散完成，圆外旧主题、圆内新主题动画
            // （prefers-reduced-motion 时直接切换，不创建遮罩）
            function themeCircleTransition(cx, cy) {
                const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
                if (reduce) { applyThemeState(); return; }
                document.querySelectorAll('.theme-transition').forEach(n => n.remove());
                // 高亮代码主题随目标主题先行切换（真实与克隆页共用文档级样式表）
                const hlHref = settings.theme === 'light' ?
                    u('/static/js/highlight.js/styles/atom-one-light.min.css') :
                    u('/static/js/highlight.js/styles/atom-one-dark.min.css');
                if (hlLink.getAttribute('href') !== hlHref) hlLink.setAttribute('href', hlHref);
                // 1. 克隆当前页面并套用目标主题
                const clone = document.body.cloneNode(true);
                clone.classList.toggle('light-theme', settings.theme === 'light');
                clone.querySelectorAll('script, .draggable-window, .theme-transition').forEach(n => n.remove());
                // cloneNode 不复制滚动位置：同步消息区滚动高度，
                // 否则扩散结束遮罩消失的瞬间，克隆页与真实页滚动位置不一致会跳变
                const realSd = document.getElementById('sd');
                const cloneSd = clone.querySelector('#sd');
                if (realSd && cloneSd) cloneSd.scrollTop = realSd.scrollTop;
                // 遮罩内克隆体静态展示目标主题：禁用入场动画，避免圆扩散期间
                // 组件"重绘/重播动画"，遮罩消失时与真实页面无缝衔接
                clone.querySelectorAll('#chat, .chat-header, .chat-divider, .system-message, .user-info, #chat-combined, .boot-line, .theme-toggle, .appearance-btn, .tools-btn, .admin-entry-btn, #sd, .admin-standalone').forEach(n => { n.style.animation = 'none'; });
                const mi = clone.querySelector('#modeIndicator');
                if (mi) mi.textContent = settings.theme === 'light' ? '亮' : '暗';
                // 2. 遮罩容器承载克隆体，从按钮中心扩散
                // 挂到 document.documentElement（真实 body 之外），避免克隆体
                // 从仍带 light-theme 的真实 body 继承错误的主题变量
                const overlay = document.createElement('div');
                overlay.className = 'theme-transition';
                overlay.style.clipPath = `circle(0px at ${cx}px ${cy}px)`;
                overlay.appendChild(clone);
                document.documentElement.appendChild(overlay);
                overlay.offsetWidth; // 强制重排，确保动画从起始状态开始
                const maxR = Math.hypot(Math.max(cx, window.innerWidth - cx),
                                        Math.max(cy, window.innerHeight - cy)) + 20;
                overlay.style.clipPath = `circle(${maxR}px at ${cx}px ${cy}px)`;
                // 3. 扩散完成：真实页面切换主题并移除遮罩。
                // 先禁用 body 的 0.15s 背景/颜色过渡（否则遮罩消失瞬间会看到
                // 真实页面重新渐变一遍 = 闪烁），下一帧再恢复。
                setTimeout(() => {
                    document.body.style.transition = 'none';
                    applyThemeState();
                    overlay.remove();
                    requestAnimationFrame(() => { document.body.style.transition = ''; });
                }, 500);
            }

            document.getElementById('themeToggle').addEventListener('click', () => {
                settings.theme = settings.theme === 'light' ? 'dark' : 'light';
                const r = document.getElementById('themeToggle').getBoundingClientRect();
                themeCircleTransition(r.left + r.width / 2, r.top + r.height / 2);
            });

            // ================================================================
            //  3. 工具弹窗（原有）
            // ================================================================
            const toolsModal = document.getElementById('toolsModal');
            const toolsBtn = document.getElementById('toolsBtn');
            const toolsCloseBtn = document.getElementById('toolsCloseBtn');

            function openToolsModal() {
                toolsModal.classList.add('active');
                toolsModal.classList.remove('closing');
            }

            function closeToolsModal() {
                toolsModal.classList.add('closing');
                toolsModal.classList.remove('active');
                const h = () => {
                    toolsModal.classList.remove('closing');
                    toolsModal.removeEventListener('transitionend', h);
                };
                toolsModal.addEventListener('transitionend', h);
            }
            toolsBtn.addEventListener('click', openToolsModal);
            toolsCloseBtn.addEventListener('click', closeToolsModal);
            toolsModal.addEventListener('click', (e) => {
                if (e.target === toolsModal) closeToolsModal();
            });

            // ================================================================
            //  4. 可拖拽窗口（原有）
            // ================================================================
            let windowZIndex = 3000;
            const openWindows = {};

            function bringWindowToFront(win) {
                windowZIndex++;
                win.style.zIndex = windowZIndex;
            }

            // 聚焦已打开的窗口：置顶 + 高亮动画（与文件窗口一致）
            function focusWindow(win) {
                bringWindowToFront(win);
                win.classList.remove('highlight');
                void win.offsetWidth;
                win.classList.add('highlight');
            }

            function animateLShapedCorners(win) {
                const r = win.getBoundingClientRect();
                const cx = r.left + r.width / 2,
                    cy = r.top + r.height / 2;
                const z = windowZIndex + 1;
                const out = document.createElement('div');
                out.className = 'window-outline';
                out.style.left = cx + 'px';
                out.style.top = cy + 'px';
                out.style.width = '0px';
                out.style.height = '0px';
                out.style.zIndex = z;
                document.body.appendChild(out);
                const tr = document.createElement('div');
                tr.className = 'l-corner top-right';
                tr.style.left = cx + 'px';
                tr.style.top = cy + 'px';
                tr.style.zIndex = z;
                document.body.appendChild(tr);
                const bl = document.createElement('div');
                bl.className = 'l-corner bottom-left';
                bl.style.left = cx + 'px';
                bl.style.top = cy + 'px';
                bl.style.zIndex = z;
                document.body.appendChild(bl);
                out.offsetWidth;
                out.style.left = r.left + 'px';
                out.style.top = r.top + 'px';
                out.style.width = r.width + 'px';
                out.style.height = r.height + 'px';
                tr.style.left = (r.right - 20) + 'px';
                tr.style.top = r.top + 'px';
                bl.style.left = r.left + 'px';
                bl.style.top = (r.bottom - 20) + 'px';
                setTimeout(() => {
                    win.style.opacity = '1';
                    out.style.opacity = '0';
                    tr.style.opacity = '0';
                    bl.style.opacity = '0';
                    setTimeout(() => { out.remove();
                        tr.remove();
                        bl.remove(); }, 250);
                }, 300);
            }

            function closeDraggableWindow(win, key) {
                if (win._closing) return;
                win._closing = true;
                const r = win.getBoundingClientRect(),
                    cx = r.left + r.width / 2,
                    cy = r.top + r.height / 2,
                    z = windowZIndex + 1;
                const out = document.createElement('div');
                out.className = 'window-outline';
                out.style.left = r.left + 'px';
                out.style.top = r.top + 'px';
                out.style.width = r.width + 'px';
                out.style.height = r.height + 'px';
                out.style.opacity = '1';
                out.style.zIndex = z;
                document.body.appendChild(out);
                const tr = document.createElement('div');
                tr.className = 'l-corner top-right';
                tr.style.left = (r.right - 20) + 'px';
                tr.style.top = r.top + 'px';
                tr.style.opacity = '1';
                tr.style.zIndex = z;
                document.body.appendChild(tr);
                const bl = document.createElement('div');
                bl.className = 'l-corner bottom-left';
                bl.style.left = r.left + 'px';
                bl.style.top = (r.bottom - 20) + 'px';
                bl.style.opacity = '1';
                bl.style.zIndex = z;
                document.body.appendChild(bl);
                out.offsetWidth;
                win.style.opacity = '0';
                out.style.left = cx + 'px';
                out.style.top = cy + 'px';
                out.style.width = '0px';
                out.style.height = '0px';
                tr.style.left = cx + 'px';
                tr.style.top = cy + 'px';
                bl.style.left = cx + 'px';
                bl.style.top = cy + 'px';
                setTimeout(() => {
                    out.style.opacity = '0';
                    tr.style.opacity = '0';
                    bl.style.opacity = '0';
                    setTimeout(() => {
                        out.remove();
                        tr.remove();
                        bl.remove();
                        document.body.removeChild(win);
                        if (key) delete openWindows[key];
                    }, 250);
                }, 300);
            }

            function createDraggableWindow(title, html, showProgress, key) {
                const win = document.createElement('div');
                win.className = 'draggable-window';
                win.style.left = Math.max(30, (window.innerWidth - 550) / 2 + Math.random() * 80) + 'px';
                win.style.top = Math.max(30, (window.innerHeight - 400) / 2 + Math.random() * 60) + 'px';
                win.style.width = '600px';
                win.style.opacity = '0';
                win.innerHTML =
                    `<div class="window-titlebar"><span class="window-title">${title}</span><div class="window-actions"><button class="window-btn copy-content-btn" style="display:none;">复制</button><button class="window-btn download-window-btn" style="display:none;">下载</button><button class="window-btn close-window-btn"><svg class="icon" aria-hidden="true"><use href="#i-x"/></svg></button></div></div>${showProgress?'<div class="window-progress"><div class="progress-bar"><div class="progress-fill" style="width:0%"></div></div><div class="progress-text">准备下载...</div></div>':''}<div class="window-content">${html}</div>`;
                document.body.appendChild(win);
                if (key) openWindows[key] = win;
                const titlebar = win.querySelector('.window-titlebar');
                const contentArea = win.querySelector('.window-content');
                let dragging = false,
                    sx, sy, ix, iy;
                titlebar.addEventListener('mousedown', (e) => {
                    if (e.target.classList.contains('window-btn')) return;
                    dragging = true;
                    const r = win.getBoundingClientRect();
                    sx = e.clientX;
                    sy = e.clientY;
                    ix = r.left;
                    iy = r.top;
                    bringWindowToFront(win);
                    e.preventDefault();
                });
                document.addEventListener('mousemove', (e) => {
                    if (!dragging) return;
                    win.style.left = Math.max(0, Math.min(window.innerWidth - win.offsetWidth, ix + e.clientX - sx)) +
                        'px';
                    win.style.top = Math.max(0, Math.min(window.innerHeight - 50, iy + e.clientY - sy)) + 'px';
                });
                document.addEventListener('mouseup', () => { dragging = false; });
                contentArea.addEventListener('click', () => bringWindowToFront(win));
                win.querySelector('.close-window-btn').addEventListener('click', () => closeDraggableWindow(win, key));
                bringWindowToFront(win);
                setTimeout(() => animateLShapedCorners(win), 20);
                return win;
            }

            // ================================================================
            //  5. 外观设置窗口（原有）
            // ================================================================
            function buildSettingsSubpage(win, page) {
                const c = win.querySelector('.window-content');
                c.style.cursor = 'default';
                let html = '';
                if (page === 'main') html =
                    `<div class="settings-menu-container"><button class="settings-menu-btn" data-page="interface" style="--stripe-color: #2a6df4;"><span>界面显示</span></button><button class="settings-menu-btn" data-page="chat" style="--stripe-color: #f45b2a;"><span>聊天样式</span></button><button class="settings-menu-btn" data-page="theme" style="--stripe-color: #4caf50;"><span>主题与代码</span></button></div><div class="code-scroller"><div class="code-scroll-inner">${randomCode()+'\n'+randomCode()}</div></div>`;
                else {
                    html =
                        `<div style="width:100%; display:flex; justify-content:flex-start; margin-bottom:10px;"><button class="back-btn" data-page="main"><svg class="icon" aria-hidden="true"><use href="#i-arrow-left"/></svg> 返回</button></div>`;
                    if (page === 'interface') html +=
                        `<div class="settings-row"><label>整体字体大小</label><input type="range" id="fontSizeRange" min="12" max="24" value="${settings.fontSize}" step="1"><span id="fontSizeValue">${settings.fontSize}px</span></div><div class="settings-row"><label>头像大小</label><input type="range" id="avatarSizeRange" min="28" max="48" value="${settings.avatarSize}" step="1"><span id="avatarSizeValue">${settings.avatarSize}px</span></div><div class="settings-row"><label>头像边框粗细</label><input type="range" id="avatarBorderRange" min="0" max="6" value="${settings.avatarBorderWidth}" step="1"><span id="avatarBorderValue">${settings.avatarBorderWidth}px</span></div><div class="settings-row"><label>在线点大小</label><input type="range" id="onlineDotRange" min="6" max="14" value="${settings.onlineDotSize}" step="1"><span id="onlineDotValue">${settings.onlineDotSize}px</span></div>`;
                    else if (page === 'chat') html +=
                        `<div class="settings-row"><label>气泡圆角</label><input type="range" id="bubbleRadiusRange" min="0" max="16" value="${settings.bubbleRadius}" step="1"><span id="bubbleRadiusValue">${settings.bubbleRadius}px</span></div><div class="settings-row"><label>消息字体大小</label><input type="range" id="messageFontRange" min="0.8" max="1.2" value="${settings.messageFontSize}" step="0.05"><span id="messageFontValue">${settings.messageFontSize}rem</span></div>`;
                    else if (page === 'theme') html +=
                        `<div class="settings-row"><label>主题配色</label><select id="themeSelect"><option value="dark" ${settings.theme==='dark'?'selected':''}>暗色</option><option value="light" ${settings.theme==='light'?'selected':''}>亮色</option></select></div><div class="settings-row"><label>代码高亮</label><select id="highlightSelect"><option value="auto" ${settings.highlightTheme==='auto'?'selected':''}>跟随主题</option><option value="dark" ${settings.highlightTheme==='dark'?'selected':''}>暗色 (One Dark)</option><option value="light" ${settings.highlightTheme==='light'?'selected':''}>亮色 (One Light)</option></select></div>`;
                }
                c.innerHTML = html;
                c.querySelectorAll('[data-page]').forEach(b => b.addEventListener('click', () => buildSettingsSubpage(win, b
                    .getAttribute('data-page'))));
                if (page === 'interface') {
                    document.getElementById('fontSizeRange').addEventListener('input', (e) => { settings.fontSize =
                            parseInt(e.target.value);
                        document.getElementById('fontSizeValue').textContent = settings.fontSize + 'px';
                        applyAllSettings();
                        saveAllSettings(); });
                    document.getElementById('avatarSizeRange').addEventListener('input', (e) => { settings.avatarSize =
                            parseInt(e.target.value);
                        document.getElementById('avatarSizeValue').textContent = settings.avatarSize + 'px';
                        applyAllSettings();
                        saveAllSettings(); });
                    document.getElementById('avatarBorderRange').addEventListener('input', (e) => { settings
                            .avatarBorderWidth = parseInt(e.target.value);
                        document.getElementById('avatarBorderValue').textContent = settings.avatarBorderWidth +
                            'px';
                        applyAllSettings();
                        saveAllSettings(); });
                    document.getElementById('onlineDotRange').addEventListener('input', (e) => { settings
                            .onlineDotSize = parseInt(e.target.value);
                        document.getElementById('onlineDotValue').textContent = settings.onlineDotSize + 'px';
                        applyAllSettings();
                        saveAllSettings(); });
                } else if (page === 'chat') {
                    document.getElementById('bubbleRadiusRange').addEventListener('input', (e) => { settings
                            .bubbleRadius = parseInt(e.target.value);
                        document.getElementById('bubbleRadiusValue').textContent = settings.bubbleRadius +
                            'px';
                        applyAllSettings();
                        saveAllSettings(); });
                    document.getElementById('messageFontRange').addEventListener('input', (e) => { settings
                            .messageFontSize = parseFloat(e.target.value);
                        document.getElementById('messageFontValue').textContent = settings.messageFontSize +
                            'rem';
                        applyAllSettings();
                        saveAllSettings(); });
                } else if (page === 'theme') {
                    document.getElementById('themeSelect').addEventListener('change', (e) => { settings.theme = e
                            .target.value;
                        applyThemeState(); });
                    document.getElementById('highlightSelect').addEventListener('change', (e) => { settings
                            .highlightTheme = e.target.value;
                        updateHighlightTheme();
                        saveAllSettings(); });
                }
            }

            document.getElementById('appearanceBtn').addEventListener('click', () => {
                if (openWindows['settings']) {
                    focusWindow(openWindows['settings']);
                    return;
                }
                const w = createDraggableWindow('外观设置', '', false, 'settings');
                buildSettingsSubpage(w, 'main');
            });

            function randomCode() {
                const s = ['def hello(): print("Hello, World!")', 'const x = [1,2,3].map(n => n*2);',
                    'import os\nos.system("clear")', 'fetch("/api/data").then(r => r.json())',
                    'for i in range(10):\n    print(i)', 'git commit -m "update"',
                    'docker run -d -p 8080:80 app', 'npm install --save axios',
                    'SELECT * FROM users WHERE id=1;',
                    'class Node:\n    def __init__(self, value):\n        self.value = value',
                    'body { background: #1a1a1a; }', '<div class="container"></div>',
                    '$.ajax({ url: "/api", method: "GET" })', 'console.log("Hello from console");',
                    'from flask import Flask\napp = Flask(__name__)'
                ];
                let lines = [];
                for (let i = 0; i < 40; i++) lines.push(s[Math.floor(Math.random() * s.length)]);
                return lines.join('\n');
            }

            // ================================================================
            //  6. 文件预览（原有）
            // ================================================================
            const PREVIEW_EXTS = ['txt', 'py', 'js', 'html', 'css', 'json', 'md', 'xml', 'yaml', 'yml', 'sh', 'bat', 'ini',
                'cfg', 'conf', 'log', 'java', 'c', 'cpp', 'h', 'php', 'rb', 'go', 'rs', 'swift', 'kt', 'ts', 'jsx', 'vue',
                'sql', 'r', 'pl', 'lua', 'in', 'out'
            ];
            const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg', 'ico'];

            function isPreviewableText(fn) { return PREVIEW_EXTS.includes((fn || '').split('.').pop().toLowerCase()); }

            function isImageFile(fn) { return IMAGE_EXTS.includes((fn || '').split('.').pop().toLowerCase()); }

            function fileDownload(url, filename) {
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                a.remove();
            }

            function openFileWindow(url, filename) {
                if (openWindows[url]) {
                    focusWindow(openWindows[url]);
                    return;
                }
                if (isImageFile(filename)) {
                    const w = createDraggableWindow(filename, '', false, url);
                    w.querySelector('.window-content').innerHTML =
                        `<img src="${url}" style="max-width:100%; max-height:55vh; display:block; margin:0 auto;" onerror="this.parentElement.innerHTML='<p style=\\'color:var(--fg-muted);\\'>图片加载失败，文件可能已失效。</p>'">`;
                    const dw = w.querySelector('.download-window-btn');
                    dw.style.display = 'inline-block';
                    dw.onclick = () => fileDownload(url, filename);
                    openWindows[url] = w;
                    return;
                }
                const extension = (filename || '').split('.').pop().toLowerCase();
                if (extension === 'cpp') {
                    const w = createDraggableWindow(filename, '<p style="color:var(--fg-muted);">读取中...</p>', false, url);
                    const cd = w.querySelector('.window-content');
                    const cb = w.querySelector('.copy-content-btn');
                    const dw = w.querySelector('.download-window-btn');
                    dw.style.display = 'inline-block';
                    dw.onclick = () => fileDownload(url, filename);
                    openWindows[url] = w;
                    fetch(u('/api/cpp-preview?filename=' + encodeURIComponent(filename) + '&update=' + encodeURIComponent(upd)))
                        .then(response => response.ok ? response.json() : response.json().then(body => Promise.reject(body)))
                        .then(body => {
                            const code = document.createElement('code');
                            code.className = 'language-cpp';
                            code.textContent = body.content || '';
                            const pre = document.createElement('pre');
                            pre.appendChild(code);
                            cd.replaceChildren(pre);
                            hljs.highlightElement(code);
                            cb.style.display = 'inline-block';
                            cb.onclick = () => copyToClipboard(body.content || '').then(showCopyToast).catch(() => alert('复制失败'));
                        })
                        .catch(() => { cd.innerHTML = '<p style="color:var(--error-color);">C++ 文件预览失败</p>'; });
                    return;
                }
                if (isPreviewableText(filename)) {
                    const w = createDraggableWindow(filename, '', true, url);
                    const pf = w.querySelector('.progress-fill');
                    const pt = w.querySelector('.progress-text');
                    const cd = w.querySelector('.window-content');
                    const cb = w.querySelector('.copy-content-btn');
                    const dw = w.querySelector('.download-window-btn');
                    dw.style.display = 'inline-block';
                    dw.onclick = () => fileDownload(url, filename);
                    openWindows[url] = w;
                    let xhr = new XMLHttpRequest();
                    xhr.open('GET', url, true);
                    xhr.responseType = 'text';
                    xhr.addEventListener('progress', (e) => {
                        if (e.lengthComputable) {
                            let pct = (e.loaded / e.total) * 100;
                            pf.style.width = pct + '%';
                            pt.textContent = `下载中 ${Math.round(pct)}% (${(e.loaded/1024).toFixed(1)}KB)`;
                            if (e.total > 1024 * 1024) {
                                xhr.abort();
                                pt.textContent = '文件超过1MB';
                                cd.innerHTML = '<p style="color:var(--fg-muted);">文件过大</p>';
                            }
                        }
                    });
                    xhr.addEventListener('load', () => {
                        if (xhr.status === 200) {
                            let content = xhr.responseText;
                            if (content.length > 1024 * 1024) {
                                pt.textContent = '文件超过1MB';
                                cd.innerHTML = '<p style="color:var(--fg-muted);">文件过大</p>';
                            } else {
                                pf.style.width = '100%';
                                pt.textContent = '下载完成';
                                let ext = filename.split('.').pop().toLowerCase();
                                cd.innerHTML = `<pre><code class="language-${ext}"></code></pre>`;
                                const ce = cd.querySelector('code');
                                ce.textContent = content;
                                hljs.highlightElement(ce);
                                cb.style.display = 'inline-block';
                                cb.onclick = () => {
                                    copyToClipboard(content).then(() => {
                                        cb.textContent = '已复制';
                                        showCopyToast();
                                        setTimeout(() => { cb.textContent = '复制'; }, 1500);
                                    }).catch(() => alert('复制失败'));
                                };
                            }
                        } else {
                            pt.textContent = '下载失败';
                            cd.innerHTML = '<p style="color: var(--error-color);">文件下载失败</p>';
                        }
                    });
                    xhr.addEventListener('error', () => {
                        pt.textContent = '下载出错';
                        cd.innerHTML = '<p style="color: var(--error-color);">下载出错</p>';
                    });
                    xhr.send();
                    return;
                }
                const w = createDraggableWindow(filename, '', false, url);
                const cd = w.querySelector('.window-content');
                cd.innerHTML =
                    `<div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:200px; gap:20px;"><p style="color: var(--fg-muted);">不支持在线预览</p><button class="window-btn download-btn">下载文件</button></div>`;
                w.querySelector('.download-btn').addEventListener('click', () => { const a = document.createElement(
                        'a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a); });
                const dw = w.querySelector('.download-window-btn');
                dw.style.display = 'inline-block';
                dw.onclick = () => fileDownload(url, filename);
                openWindows[url] = w;
            }

            // ================================================================
            //  7. 表情包（原有）
            // ================================================================
            function openEmojiWindow() {
                if (openWindows['emoji']) {
                    focusWindow(openWindows['emoji']);
                    return;
                }
                const w = createDraggableWindow('我的表情包', '', false, 'emoji');
                w.querySelector('.window-content').innerHTML = '<p style="color:var(--fg-muted);">加载中...</p>';
                loadEmojiList(w);
            }

            function loadEmojiList(win) {
                const cd = win.querySelector('.window-content');
                $.get(u('/chat/emoji/list/' + encodeURIComponent(currentUser) + '?update=' + encodeURIComponent(upd)), function(data) {
                    let html = '<button class="emoji-upload-btn" id="emojiUploadBtn">＋ 上传表情包</button>';
                    html += '<div class="emoji-grid">';
                    if (data && data.length > 0) {
                        data.forEach(fn => {
                            html +=
                                `<div class="emoji-item-wrapper"><img src="${u('/chat/emoji/static/')}${currentUser}/${fn}" alt="${fn}" title="${fn}" class="emoji-item" data-filename="${fn}"><span class="emoji-delete-btn" data-filename="${fn}" title="删除"><svg class="icon" aria-hidden="true"><use href="#i-x"/></svg></span></div>`;
                        });
                    } else {
                        html += '<p style="color:var(--fg-muted); grid-column:1/-1; text-align:center;">还没有表情包</p>';
                    }
                    html += '</div>';
                    cd.innerHTML = html;
                    document.getElementById('emojiUploadBtn').addEventListener('click', function() {
                        const input = document.createElement('input');
                        input.type = 'file';
                        input.accept = 'image/*';
                        input.onchange = function() {
                            const file = input.files[0];
                            if (!file) return;
                            const fd = new FormData();
                            fd.append('file', file);
                            fd.append('username', currentUser);
                            fd.append('update', upd);
                            $.ajax({
                                url: u('/chat/emoji/upload'),
                                type: 'POST',
                                data: fd,
                                processData: false,
                                contentType: false,
                                success: function(res) {
                                    if (res.success) loadEmojiList(win);
                                    else alert('上传失败: ' + res.error);
                                },
                                error: function() { alert('上传出错'); }
                            });
                        };
                        input.click();
                    });
                    document.querySelectorAll('.emoji-item').forEach(img => {
                        img.addEventListener('click', function() {
                            const fn = this.getAttribute('data-filename');
                            sendEmojiDirect(fn);
                        });
                    });
                    document.querySelectorAll('.emoji-delete-btn').forEach(btn => {
                        btn.addEventListener('click', function(e) {
                            e.stopPropagation();
                            const fn = this.getAttribute('data-filename');
                            if (confirm('确定要删除这个表情包吗？')) {
                                $.ajax({
                                    url: u('/chat/emoji/delete'),
                                    type: 'POST',
                                    data: { username: currentUser, filename: fn, update: upd },
                                    success: function(res) {
                                        if (res.success) loadEmojiList(win);
                                        else alert('删除失败: ' + res.error);
                                    },
                                    error: function() { alert('删除出错'); }
                                });
                            }
                        });
                    });
                }).fail(function() {
                    cd.innerHTML = '<p style="color:var(--fg-muted);">加载失败</p>';
                });
            }

            function sendEmojiDirect(filename) {
                const text = '::emoji::' + filename;
                if (isSending || isMuted()) return;
                isSending = true;
                stopPolling();
                sendTextMessage(text, function(ok) {
                    if (!ok) alert('发送表情包失败');
                    isSending = false;
                    startPolling();
                });
            }
            document.getElementById('emojiInputBtn').addEventListener('click', openEmojiWindow);

            // ================================================================
            //  8. @ 补全（原有）
            // ================================================================
            let allUsers = [];

            function fetchUserList() {
                $.get(u('/username-list'), function(data) {
                    if (data) allUsers = data.split('||').filter(u => u.trim() !== '');
                }).fail(function() { console.warn('获取用户名列表失败'); });
            }
            fetchUserList();

            function getFilteredUsers() {
                return allUsers.filter(u => u !== currentUser && u !== '聊天室');
            }

            function escapeHtml(text) {
                const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
                return text.replace(/[&<>"']/g, m => map[m]);
            }

            function highlightMentionIfNeeded(text, isOwn) {
                if (isOwn) return escapeHtml(text);
                const escaped = escapeHtml(text);
                const user = currentUser;
                const escapedUser = user.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const regex = new RegExp(`(?<![\\w\u4e00-\u9fff])@(${escapedUser})(?![\\w\u4e00-\u9fff])`, 'g');
                return escaped.replace(regex, '<span class="mention">@$1</span>');
            }

            const acMenu = document.querySelector('.autocomplete-menu');
            let acIndex = -1;

            function showAutocomplete(input) {
                const val = input.value;
                const cursorPos = input.selectionStart;
                const beforeCursor = val.substring(0, cursorPos);
                const match = beforeCursor.match(/@(\S*)$/);
                if (match) {
                    const query = match[1].toLowerCase();
                    const filtered = getFilteredUsers().filter(u => u.toLowerCase().startsWith(query));
                    if (filtered.length > 0) {
                        acMenu.innerHTML = '';
                        filtered.forEach((u, i) => {
                            const item = document.createElement('div');
                            item.className = 'autocomplete-item';
                            item.textContent = u;
                            item.addEventListener('click', () => {
                                insertMention(input, match.index, u);
                                acMenu.classList.remove('active');
                            });
                            acMenu.appendChild(item);
                        });
                        acMenu.classList.add('active');
                        acIndex = -1;
                    } else {
                        acMenu.classList.remove('active');
                    }
                } else {
                    acMenu.classList.remove('active');
                }
            }

            function insertMention(input, startIndex, username) {
                const val = input.value;
                const cursorPos = input.selectionStart;
                const before = val.substring(0, startIndex);
                const after = val.substring(cursorPos);
                input.value = before + '@' + username + ' ' + after;
                const newCursor = before.length + username.length + 2;
                input.setSelectionRange(newCursor, newCursor);
                input.focus();
            }

            const upft = document.getElementById('upft');
            function resizeUpft() {
                if (!upft) return;
                upft.style.height = 'auto';
                upft.style.height = Math.min(upft.scrollHeight, 120) + 'px';
            }
            upft.addEventListener('input', function() { showAutocomplete(this); resizeUpft(); });
            resizeUpft();
            upft.addEventListener('keydown', function(e) {
                if (acMenu.classList.contains('active')) {
                    const items = acMenu.querySelectorAll('.autocomplete-item');
                    if (e.key === 'ArrowDown') {
                        e.preventDefault();
                        acIndex = Math.min(acIndex + 1, items.length - 1);
                        updateAcSelection(items);
                    } else if (e.key === 'ArrowUp') {
                        e.preventDefault();
                        acIndex = Math.max(acIndex - 1, 0);
                        updateAcSelection(items);
                    } else if (e.key === 'Enter' && !e.shiftKey) {
                        if (acIndex >= 0 && items[acIndex]) {
                            e.preventDefault();
                            items[acIndex].click();
                        } else {
                            acMenu.classList.remove('active');
                        }
                    } else if (e.key === 'Escape') {
                        acMenu.classList.remove('active');
                    }
                }
            });

            function updateAcSelection(items) {
                items.forEach((item, i) => {
                    item.classList.toggle('selected', i === acIndex);
                    if (i === acIndex) item.scrollIntoView({ block: 'nearest' });
                });
            }
            document.addEventListener('click', function(e) {
                if (!acMenu.contains(e.target) && e.target !== upft) acMenu.classList.remove('active');
            });

            // ================================================================
            //  9. 聊天核心（原有，但修改了 update 以支持选择模式）
            // ================================================================
            var currentUser = window.CHAT_CONFIG.username;
            let upd = window.CHAT_CONFIG.update;
            const currentUserIsAdmin = window.CHAT_CONFIG.is_admin;
            let tc = 0;
            let lastOnlineUsersStr = null;
            let updateInterval, loginInterval, muteInterval;
            let isSending = false;
            let sessionValid = true;
            let muteUntil = window.CHAT_CONFIG.mute_until * 1000;
            let clockOffset = 0;
            let pendingReply = null;
            let knownMessageIds = null;
            let mentionAudioContext = null;

            function unlockMentionAudio() {
                if (!mentionAudioContext) {
                    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
                    if (!AudioContextClass) return;
                    mentionAudioContext = new AudioContextClass();
                }
                if (mentionAudioContext.state === 'suspended') mentionAudioContext.resume();
            }

            function playMentionNotification() {
                unlockMentionAudio();
                if (!mentionAudioContext || mentionAudioContext.state !== 'running') return;
                const now = mentionAudioContext.currentTime;
                const oscillator = mentionAudioContext.createOscillator();
                const gain = mentionAudioContext.createGain();
                oscillator.type = 'sine';
                oscillator.frequency.setValueAtTime(880, now);
                oscillator.frequency.setValueAtTime(1174, now + 0.09);
                gain.gain.setValueAtTime(0.0001, now);
                gain.gain.exponentialRampToValueAtTime(0.16, now + 0.01);
                gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.22);
                oscillator.connect(gain);
                gain.connect(mentionAudioContext.destination);
                oscillator.start(now);
                oscillator.stop(now + 0.23);
            }

            function messageMentionsCurrentUser(message) {
                if (!message || message.user === currentUser || !currentUser) return false;
                const escapedUser = currentUser.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                return new RegExp('(^|\\s)@' + escapedUser + '(?![\\w\\u4e00-\\u9fff])').test(message.content);
            }

            function notifyNewMentions(messages) {
                const currentIds = new Set(messages.map(message => message.id));
                if (knownMessageIds) {
                    const hasMention = messages.some(message => knownMessageIds.has(message.id) === false && messageMentionsCurrentUser(message));
                    if (hasMention) playMentionNotification();
                }
                knownMessageIds = currentIds;
            }

            document.addEventListener('pointerdown', unlockMentionAudio, { once: true });
            document.addEventListener('keydown', unlockMentionAudio, { once: true });

            const fileInput = document.getElementById('file-input');
            const filePickerBtn = document.getElementById('filePickerBtn');
            filePickerBtn.addEventListener('click', () => { if (!isMuted()) fileInput.click(); });
            fileInput.addEventListener('change', function() {
                const filename = this.files[0] ? this.files[0].name : '';
                document.getElementById('fileHint').textContent = filename ? '已选择: ' + filename : '';
            });

            function formatRemaining(seconds) {
                const hours = Math.floor(seconds / 3600);
                const minutes = Math.floor((seconds % 3600) / 60);
                const rest = seconds % 60;
                if (hours) return hours + '小时 ' + minutes + '分';
                if (minutes) return minutes + '分 ' + rest + '秒';
                return rest + '秒';
            }

            function isMuted() {
                return muteUntil > Date.now() + clockOffset;
            }

            function setMuteState(until, serverTime) {
                const numericUntil = Number(until || 0) * 1000;
                if (Number.isFinite(serverTime)) clockOffset = serverTime * 1000 - Date.now();
                muteUntil = Number.isFinite(numericUntil) ? numericUntil : 0;
                const status = document.getElementById('muteStatus');
                if (!status) return;
                if (isMuted()) {
                    status.classList.add('active');
                    status.textContent = '当前处于禁言状态，剩余 ' + formatRemaining(Math.max(1, Math.ceil((muteUntil - Date.now() - clockOffset) / 1000))) + '。';
                } else {
                    status.classList.remove('active');
                    status.textContent = '';
                }
                const controls = [
                    document.getElementById('upft'), document.getElementById('file-input'),
                    document.getElementById('filePickerBtn'), document.getElementById('sendBtn'),
                    document.getElementById('textFileSendBtn'), document.getElementById('emojiInputBtn')
                ];
                controls.forEach(control => { if (control) control.disabled = isMuted(); });
            }

            function updateMuteCountdown() {
                if (muteUntil && !isMuted()) setMuteState(0);
                else setMuteState(muteUntil / 1000);
            }
            setMuteState(muteUntil / 1000);
            muteInterval = setInterval(updateMuteCountdown, 1000);

            function stopPolling() {
                if (updateInterval) clearInterval(updateInterval);
                if (loginInterval) clearInterval(loginInterval);
                updateInterval = null;
                loginInterval = null;
            }

            function startPolling() {
                if (!sessionValid) return;
                stopPolling();
                updateInterval = setInterval(update, 3000);
                loginInterval = setInterval(login, 3000);
            }

            function handleAjaxError(xhr, fallback) {
                let body = xhr && xhr.responseJSON;
                if (!body && xhr && xhr.responseText) {
                    try { body = JSON.parse(xhr.responseText); } catch (_) { body = null; }
                }
                if (body && body.muted_until) setMuteState(body.muted_until);
                alert((body && body.error) || fallback);
            }

            function clearReply() {
                pendingReply = null;
                document.getElementById('replyCompose').classList.remove('active');
                document.getElementById('replyComposeText').textContent = '';
            }

            function setReplyTarget(message) {
                pendingReply = message;
                document.getElementById('replyComposeText').textContent = message.user + ': ' + messageSummary(message);
                document.getElementById('replyCompose').classList.add('active');
                document.getElementById('upft').focus();
            }
            document.getElementById('cancelReplyBtn').addEventListener('click', clearReply);

            const sendBtn = document.getElementById('sendBtn');
            const warningHint = document.getElementById('warningHint') || document.createElement('div');
            warningHint.className = 'warning-hint';
            if (!document.getElementById('warningHint')) {
                warningHint.id = 'warningHint';
                document.querySelector('#chat-combined .text-field').appendChild(warningHint);
            }

            function checkWarning() {
                const text = $('#upft').val().trim();
                warningHint.style.display = text.startsWith('::file::') || text.startsWith('::img::') || text.startsWith('::wav::') || text.startsWith('::emoji::') ? 'block' : 'none';
                warningHint.textContent = '该消息会按普通文本发送。';
            }
            $('#upft').on('input', checkWarning);

            function sendTextMessage(text, callback) {
                termLog('cmd', text);
                const t0 = performance.now();
                $.ajax({
                    url: u('/chatts-new?update=') + encodeURIComponent(upd),
                    type: 'POST',
                    data: { upload_value: text, username: currentUser, update: upd, reply_to: pendingReply ? pendingReply.id : '' },
                    success: function(body, status, xhr) {
                        upd = body.update || upd;
                        const ms = Math.round(performance.now() - t0);
                        termLog('request', 'POST /chatts-new → ' + (xhr ? xhr.status : 200) + ' OK · ' + ms + 'ms');
                        const msg = body && body.message;
                        if (msg && msg.command) {
                            const name = msg.command.name || '?';
                            if (msg.command.status === 'executed') {
                                const resultText = msg.chat || msg.content || '';
                                termLog('result', '[' + name + '] 执行成功' + (resultText ? ' → ' + resultText : '（无返回结果，已按普通消息发送）'));
                            } else if (msg.command.status === 'permission_denied') {
                                termLog('error', '[' + name + '] 权限不足，命令未执行');
                            } else {
                                termLog('result', '[' + name + '] 未知命令，已按普通消息发送');
                            }
                        } else if (msg) {
                            termLog('request', '消息内容：' + (msg.chat || msg.content || ''));
                        }
                        if (msg) echoSentMessage(msg);
                        $('#upft').val('');
                        resizeUpft();
                        clearReply();
                        callback(true);
                    },
                    error: function(xhr) {
                        const ms = Math.round(performance.now() - t0);
                        termLog('error', 'POST /chatts-new → ' + (xhr.status || '网络错误') + ' · ' + ms + 'ms');
                        handleAjaxError(xhr, '文字发送失败');
                        callback(false);
                    }
                });
            }

            if (sendBtn) {
                sendBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    if (isSending || isMuted()) return;
                    const text = $('#upft').val();
                    const file = fileInput.files[0];
                    if (!text.trim() && !file) return;
                    isSending = true;
                    stopPolling();
                    const replyId = pendingReply ? pendingReply.id : '';
                    const uploadFile = function(done) {
                        if (!file) { done(true); return; }
                        const fd = new FormData();
                        fd.append('file', file);
                        fd.append('username', currentUser);
                        fd.append('update', upd);
                        fd.append('reply_to', replyId);
                        $.ajax({
                            url: u('/chatts_file?update=') + encodeURIComponent(upd),
                            type: 'POST', data: fd, processData: false, contentType: false,
                            success: function(body) {
                                upd = body.update || upd;
                                fileInput.value = '';
                                document.getElementById('fileHint').textContent = '';
                                if (body && body.message) echoSentMessage(body.message);
                                done(true);
                            },
                            error: function(xhr) { handleAjaxError(xhr, '文件上传失败'); done(false); }
                        });
                    };
                    uploadFile(function(fileOk) {
                        if (!fileOk) { isSending = false; startPolling(); return; }
                        if (!text.trim()) {
                            clearReply();
                            isSending = false;
                            startPolling();
                            return;
                        }
                        sendTextMessage(text, function() { isSending = false; startPolling(); });
                    });
                });
                $('#upft').on('keydown', function(e) {
                    if (e.key === 'Enter' && !e.shiftKey && !acMenu.classList.contains('active')) {
                        e.preventDefault();
                        sendBtn.click();
                    }
                });
            }
            $(document).on('click', '.cmd-btn', function() {
                $('#upft').val('command: ' + $(this).data('cmd')).focus();
            });

            // ================================================================
            //  终端反馈区（快捷指令左侧；发送消息时滑出，超时自动缩回；可拖动/隐藏）
            // ================================================================
            const termPanel = document.getElementById('cmdTerminal');
            const termHeader = document.getElementById('termHeader');
            const termBody = document.getElementById('termBody');
            const termRetractSel = document.getElementById('termRetractSel');
            const termPinBtn = document.getElementById('termPinBtn');
            const termClearBtn = document.getElementById('termClearBtn');
            const termHideBtn = document.getElementById('termHideBtn');
            const termShowBtn = document.getElementById('termShowBtn');
            let termPinned = false;
            let termTimer = null;
            let termDragged = false;

            function termTime() {
                const d = new Date();
                const p = function (n) { return (n < 10 ? '0' : '') + n; };
                return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
            }

            function termIsHidden() {
                try { return localStorage.getItem('termHidden') === '1'; } catch (e) { return false; }
            }

            function termSetHidden(hidden) {
                try { localStorage.setItem('termHidden', hidden ? '1' : '0'); } catch (e) {}
            }

            function termSyncShowBtn() {
                if (termShowBtn) termShowBtn.classList.toggle('visible', termIsHidden());
            }

            function termLoadPos() {
                if (!termPanel) return;
                try {
                    const saved = localStorage.getItem('termPos');
                    if (!saved) return;
                    const pos = JSON.parse(saved);
                    if (typeof pos.left !== 'number' || typeof pos.top !== 'number') return;
                    termDragged = true;
                    termPanel.classList.add('dragged');
                    termPanel.style.left = pos.left + 'px';
                    termPanel.style.top = pos.top + 'px';
                } catch (e) {}
            }

            function termSavePos() {
                if (!termPanel || !termDragged) return;
                try {
                    localStorage.setItem('termPos', JSON.stringify({
                        left: parseInt(termPanel.style.left, 10) || 0,
                        top: parseInt(termPanel.style.top, 10) || 0,
                    }));
                } catch (e) {}
            }

            function termLog(type, text) {
                if (!termBody) return;
                const line = document.createElement('div');
                line.className = 'term-line term-' + type;
                const time = document.createElement('span');
                time.className = 'term-time';
                time.textContent = termTime();
                const content = document.createElement('span');
                content.className = 'term-text';
                content.textContent = text;
                line.appendChild(time);
                line.appendChild(content);
                termBody.appendChild(line);
                while (termBody.children.length > 200) termBody.removeChild(termBody.firstChild);
                termBody.scrollTop = termBody.scrollHeight;
                termActivity();
            }

            function termActivity() {
                if (!termPanel || termIsHidden()) return;
                termPanel.classList.add('active');
                termPanel.setAttribute('aria-hidden', 'false');
                clearTimeout(termTimer);
                const delay = parseInt(termRetractSel ? termRetractSel.value : '3000', 10) || 0;
                if (!termPinned && delay > 0) termTimer = setTimeout(termHide, delay);
            }

            function termHide() {
                if (!termPanel || termPinned) return;
                termPanel.classList.remove('active');
                termPanel.setAttribute('aria-hidden', 'true');
            }

            if (termPanel) {
                try {
                    const savedRetract = localStorage.getItem('termRetract');
                    if (savedRetract !== null && termRetractSel) termRetractSel.value = savedRetract;
                } catch (e) {}
                if (termRetractSel) {
                    termRetractSel.addEventListener('change', function () {
                        try { localStorage.setItem('termRetract', termRetractSel.value); } catch (e) {}
                        if (termPanel.classList.contains('active')) termActivity();
                    });
                }
                if (termPinBtn) {
                    termPinBtn.addEventListener('click', function () {
                        termPinned = !termPinned;
                        termPinBtn.textContent = termPinned ? '取消固定' : '固定';
                        termPinBtn.classList.toggle('active', termPinned);
                        if (termPinned) clearTimeout(termTimer);
                        else if (termPanel.classList.contains('active')) termActivity();
                    });
                }
                if (termClearBtn) {
                    termClearBtn.addEventListener('click', function () {
                        termBody.innerHTML = '';
                        termActivity();
                    });
                }
                if (termHideBtn) {
                    termHideBtn.addEventListener('click', function () {
                        termSetHidden(true);
                        clearTimeout(termTimer);
                        termPanel.classList.remove('active');
                        termPanel.setAttribute('aria-hidden', 'true');
                        termSyncShowBtn();
                    });
                }
                if (termShowBtn) {
                    termShowBtn.addEventListener('click', function () {
                        termSetHidden(false);
                        termPinned = true;
                        if (termPinBtn) {
                            termPinBtn.textContent = '取消固定';
                            termPinBtn.classList.add('active');
                        }
                        termActivity();
                        termSyncShowBtn();
                    });
                }
                if (termHeader) {
                    termHeader.addEventListener('pointerdown', function (e) {
                        if (e.button !== 0) return;
                        if (e.target.closest && e.target.closest('select,button')) return;
                        e.preventDefault();
                        const rect = termPanel.getBoundingClientRect();
                        const startX = e.clientX;
                        const startY = e.clientY;
                        const baseLeft = rect.left;
                        const baseTop = rect.top;
                        let moved = false;
                        const onMove = function (ev) {
                            const vw = window.innerWidth;
                            const vh = window.innerHeight;
                            const minVisible = 60;
                            const left = Math.max(minVisible - rect.width,
                                Math.min(baseLeft + (ev.clientX - startX), vw - minVisible));
                            const top = Math.max(0, Math.min(baseTop + (ev.clientY - startY), vh - 40));
                            if (!moved) {
                                moved = true;
                                termDragged = true;
                                termPanel.classList.add('dragged', 'dragging');
                            }
                            termPanel.style.left = left + 'px';
                            termPanel.style.top = top + 'px';
                        };
                        const onUp = function () {
                            window.removeEventListener('pointermove', onMove);
                            window.removeEventListener('pointerup', onUp);
                            termPanel.classList.remove('dragging');
                            if (moved) termSavePos();
                        };
                        window.addEventListener('pointermove', onMove);
                        window.addEventListener('pointerup', onUp);
                    });
                }
                termLoadPos();
                termSyncShowBtn();
            }
            const sessionAlert = document.getElementById('sessionAlert');
            document.getElementById('alertConfirmBtn').addEventListener('click', () => window.location.replace(BASE_PATH + '/'));

            function showSessionAlert() {
                if (!sessionAlert.classList.contains('active')) {
                    sessionAlert.classList.add('active');
                    stopPolling();
                    sessionValid = false;
                }
            }
            startPolling();

            function login() { tc += 1; }
            let last_result = null;
            let lastMessageSignature = '';
            const BASE_TIMESTAMP = Date.UTC(2026, 1, 1, 16, 0, 0);

            function parseTimeToTimestamp(s) {
                if (!s) return 0;
                let p = s.split(':');
                if (p.length === 3) return BASE_TIMESTAMP + ((+p[0] || 0) * 86400 + (+p[1] || 0) * 3600 + (+p[2] || 0) *
                60) * 1000;
                if (p.length === 5) return getBeijingTimestamp(+p[0] || 2026, +p[1] || 1, +p[2] || 1, +p[3] || 0, +p[4] ||
                    0);
                return 0;
            }

            function getBeijingTimestamp(y, m, d, h, min) { return Date.UTC(y, m - 1, d, h - 8, min); }

            function formatTimeForSeparator(ts) {
                if (!ts) return '';
                let now = Date.now(),
                    bj = now + 8 * 3600 * 1000,
                    bjD = new Date(bj);
                let msg = ts + 8 * 3600 * 1000,
                    msgD = new Date(msg);
                let sy = msgD.getUTCFullYear() === bjD.getUTCFullYear(),
                    sm = sy && msgD.getUTCMonth() === bjD.getUTCMonth(),
                    sd = sm && msgD.getUTCDate() === bjD.getUTCDate();
                let y = new Date(bj - 86400000);
                let isY = sy && msgD.getUTCMonth() === y.getUTCMonth() && msgD.getUTCDate() === y.getUTCDate();
                let h = msgD.getUTCHours().toString().padStart(2, '0'),
                    m = msgD.getUTCMinutes().toString().padStart(2, '0');
                if (sd) return `今天 ${h}:${m}`;
                if (isY) return `昨天 ${h}:${m}`;
                if (sy) return `${(msgD.getUTCMonth()+1).toString().padStart(2,'0')}-${msgD.getUTCDate().toString().padStart(2,'0')} ${h}:${m}`;
                return `${msgD.getUTCFullYear()}-${(msgD.getUTCMonth()+1).toString().padStart(2,'0')}-${msgD.getUTCDate().toString().padStart(2,'0')} ${h}:${m}`;
            }
            const TIME_THRESHOLD = 300;

            // 统一把消息时间换算成毫秒：服务器 timestamp 为秒，历史解析为毫秒
            function messageMs(message) {
                let ts = Number(message.timestamp);
                if (!ts) ts = parseTimeToTimestamp(message.time) || 0;
                return ts > 1e11 ? ts : ts * 1000;
            }

            function isResponseValid(text) {
                if (!text) return false;
                let lines = text.split('\n');
                if (lines.length < 4) return false;
                for (let i = 0; i < 4; i++) if (!lines[i].includes(' || ')) return false;
                return true;
            }

            // ---- 选择模式相关状态 ----
            let selectMode = false;
            let selectedIds = new Set(); // 存储选中消息的 id
            const messageCache = new Map();

            // ---- 消息分段渲染状态 ----
            const SEGMENT_SIZE = 200;     // 每次渲染的最大消息条数
            let windowStart = 0;          // 当前渲染的第一条消息在 payload.messages 中的下标
            let loadMoreInFlight = false; // 防止连点重复加载
            let suppressStickNextRender = false;

            // ---- 获取消息的唯一 ID ----
            function getMsgId(user, content, time) {
                // 用 btoa 编码，确保唯一性
                const raw = user + '||' + content + '||' + time;
                try {
                    return btoa(encodeURIComponent(raw));
                } catch (_) {
                    return 'msg_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6);
                }
            }

            // ---- 更新选中计数 ----
            function updateSelectedCount() {
                const count = selectedIds.size;
                document.getElementById('selectedCount').textContent = '已选: ' + count + ' 条';
                const genBtn = document.getElementById('generateShareBtn');
                if (count > 0) {
                    genBtn.disabled = false;
                    genBtn.style.color = 'var(--fg-primary)';
                } else {
                    genBtn.disabled = true;
                    genBtn.style.color = 'var(--fg-muted)';
                }
                const cancelBtn = document.getElementById('cancelSelectBtn');
                if (count > 0 && selectMode) {
                    cancelBtn.style.display = 'inline-block';
                } else {
                    cancelBtn.style.display = 'none';
                }
            }

            // ---- 切换选择模式 ----
            function toggleSelectMode() {
                selectMode = !selectMode;
                const btn = document.getElementById('selectModeBtn');
                const sd = document.getElementById('sd');
                if (selectMode) {
                    btn.classList.add('active-mode');
                    btn.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-check-square"/></svg> 退出选择';
                    sd.classList.add('select-mode');
                    // 取消选择按钮显示（如果有选中）
                    if (selectedIds.size > 0) {
                        document.getElementById('cancelSelectBtn').style.display = 'inline-block';
                    }
                } else {
                    btn.classList.remove('active-mode');
                    btn.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-check-square"/></svg> 选择消息';
                    sd.classList.remove('select-mode');
                    document.getElementById('cancelSelectBtn').style.display = 'none';
                    // 不清除选中，但生成按钮状态更新
                }
                // 重新渲染消息以显示/隐藏 checkbox
                // 但 update 会在下次轮询时自动刷新，这里强制刷新一次
                // 但由于 update 会重新绘制，我们需要保留选中状态
                // 直接调用 update 会触发网络请求，我们手动重绘已有数据
                if (last_result) {
                    renderMessages(last_result);
                }
                updateSelectedCount();
            }

            // ---- 取消所有选中 ----
            function clearSelected() {
                selectedIds.clear();
                updateSelectedCount();
                // 重新渲染
                if (last_result) {
                    renderMessages(last_result);
                }
            }


            function normalizePayload(payload) {
                if (typeof payload === 'string') {
                    try { payload = JSON.parse(payload); } catch (_) {
                        const lines = payload.split('\n');
                        if (lines.length < 4) return null;
                        const chats = lines[0].split(' || '), users = lines[1].split(' || '), colors = lines[2].split(' || '), times = lines[3].split(' || ');
                        return normalizePayload({ messages: chats.map((content, i) => ({
                            id: getMsgId(users[i] || '', content, times[i] || ''), user: users[i] || '', color: colors[i] || '#808080', time: times[i] || '', content, type: null, recalled: false, reply_to: null
                        })) });
                    }
                }
                if (Array.isArray(payload)) return normalizePayload(payload.join('\n'));
                if (!payload || !Array.isArray(payload.messages)) return null;
                const messages = payload.messages.map((message, index) => {
                    const content = String(message.content == null ? message.chat || '' : message.content);
                    return {
                        id: String(message.id || getMsgId(message.user || '', content, message.time || index)),
                        user: String(message.user || ''),
                        color: message.color || '#808080',
                        time: String(message.time || ''),
                        timestamp: Number(message.timestamp || parseTimeToTimestamp(message.time || '')) || 0,
                        content,
                        type: message.type || inferClientMessageType(content, message.user),
                        recalled: Boolean(message.recalled || message.revoked),
                        reply_to: message.reply_to ? String(message.reply_to) : null
                    };
                }).filter(message => message.user);
                return {
                    messages,
                    current_user: payload.current_user || currentUser,
                    is_admin: Boolean(payload.is_admin),
                    muted: Boolean(payload.muted),
                    muted_until: Number(payload.muted_until || 0),
                    server_time: Number(payload.server_time || 0)
                };
            }

            function inferClientMessageType(content, user) {
                if (user === 'system' || content === 'clear') return 'system';
                if (content.startsWith('::img::')) return 'image';
                if (content.startsWith('::wav::')) return 'audio';
                if (content.startsWith('::emoji::')) return 'emoji';
                if (content.startsWith('::file::')) return 'file';
                return 'text';
            }

            function attachmentName(message) {
                const prefixes = ['::img::', '::wav::', '::emoji::', '::file::'];
                const prefix = prefixes.find(value => message.content.startsWith(value));
                return prefix ? message.content.slice(prefix.length).trim() : message.content;
            }

            function messageSummary(message) {
                if (!message) return '';
                if (message.recalled) return '消息已撤回';
                if (['file', 'image', 'audio', 'emoji'].includes(message.type)) return attachmentName(message);
                return message.content.replace(/\s+/g, ' ').trim();
            }

            function appendMentionText(parent, text, isOwn) {
                if (isOwn || !currentUser) {
                    parent.appendChild(document.createTextNode(text));
                    return;
                }
                const escapedUser = currentUser.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const pattern = new RegExp('(@' + escapedUser + ')(?![\\w\\u4e00-\\u9fff])', 'g');
                let cursor = 0, match;
                while ((match = pattern.exec(text))) {
                    parent.appendChild(document.createTextNode(text.slice(cursor, match.index)));
                    const mention = document.createElement('span');
                    mention.className = 'mention';
                    mention.textContent = match[1];
                    parent.appendChild(mention);
                    cursor = match.index + match[0].length;
                }
                parent.appendChild(document.createTextNode(text.slice(cursor)));
            }

            function appendRichText(parent, raw, isOwn) {
                const urlPattern = /https?:\/\/[^\s<>"'，。！？、]+/gi;
                let cursor = 0, match;
                while ((match = urlPattern.exec(raw))) {
                    let value = match[0], trailing = '';
                    while (/[.,!?;:)}\]，。！？、]$/.test(value)) {
                        trailing = value.slice(-1) + trailing;
                        value = value.slice(0, -1);
                    }
                    appendMentionText(parent, raw.slice(cursor, match.index), isOwn);
                    const isPure = !raw.slice(0, match.index).trim() && !raw.slice(match.index + match[0].length).trim();
                    if (isPure && isLikelyImageUrl(value)) parent.appendChild(createRemoteImageLink(value));
                    else parent.appendChild(createExternalLink(value, value));
                    if (trailing) appendMentionText(parent, trailing, isOwn);
                    cursor = match.index + match[0].length;
                }
                appendMentionText(parent, raw.slice(cursor), isOwn);
            }

            // 插件渲染钩子：__chatterRenderHooks 数组由插件 JS 在 chat.js 之前注册，
            // 钩子签名 (bubble, message, payload)，返回 true 表示已接管气泡内容
            function callRenderHooks(bubble, message, payload) {
                const hooks = window.__chatterRenderHooks;
                if (!Array.isArray(hooks) || hooks.length === 0) return false;
                let handled = false;
                for (let i = 0; i < hooks.length; i++) {
                    try {
                        if (hooks[i](bubble, message, payload) === true) handled = true;
                    } catch (_) {}
                }
                return handled;
            }

            function isLikelyImageUrl(value) {
                try {
                    const url = new URL(value);
                    return /\.(?:png|jpe?g|gif|bmp|webp|svg|ico)(?:$|[?#])/i.test(url.pathname);
                } catch (_) {
                    return false;
                }
            }

            function imageFilenameFromUrl(value) {
                try {
                    const name = new URL(value).pathname.split('/').pop();
                    return name || 'image';
                } catch (_) { return 'image'; }
            }

            function createExternalLink(url, label) {
                const link = document.createElement('a');
                link.className = 'rich-link';
                link.href = url;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                link.textContent = label;
                return link;
            }

            function createRemoteImageLink(url) {
                const link = document.createElement('a');
                link.href = 'javascript:void(0)';
                link.className = 'image-preview-link remote-image-link';
                link.dataset.src = url;
                link.dataset.filename = imageFilenameFromUrl(url);
                const image = document.createElement('img');
                image.src = url;
                image.alt = url;
                image.addEventListener('error', () => link.replaceWith(createExternalLink(url, url)));
                link.appendChild(image);
                return link;
            }

            function appendAttachment(parent, message) {
                const filename = attachmentName(message);
                if (message.type === 'image') {
                    const link = document.createElement('a');
                    link.href = 'javascript:void(0)';
                    link.className = 'image-preview-link';
                    link.dataset.src = u('/static/uploads/') + encodeURIComponent(filename);
                    link.dataset.filename = filename;
                    const image = document.createElement('img');
                    image.src = link.dataset.src;
                    image.alt = filename;
                    image.style.maxWidth = '320px';
                    image.style.maxHeight = '320px';
                    link.appendChild(image);
                    parent.appendChild(link);
                } else if (message.type === 'audio') {
                    const audio = document.createElement('audio');
                    audio.controls = true;
                    audio.src = u('/static/uploads/') + encodeURIComponent(filename);
                    parent.appendChild(audio);
                } else if (message.type === 'emoji') {
                    const image = document.createElement('img');
                    image.className = 'emoji-inline';
                    image.alt = filename;
                    image.src = u('/chat/emoji/static/') + encodeURIComponent(message.user) + '/' + encodeURIComponent(filename);
                    image.addEventListener('error', () => {
                        const fallback = document.createElement('span');
                        fallback.className = 'message-fallback';
                        fallback.textContent = '表情包加载失败';
                        image.replaceWith(fallback);
                    });
                    parent.appendChild(image);
                } else {
                    const link = document.createElement('a');
                    link.href = 'javascript:void(0)';
                    link.className = 'file-link rich-link';
                    link.dataset.url = u('/static/uploads/') + encodeURIComponent(filename);
                    link.dataset.filename = filename;
                    link.textContent = '[文件] ' + filename;
                    parent.appendChild(link);
                }
            }

            function bindMessageLinks() {
                document.querySelectorAll('#message-list .file-link').forEach(link => {
                    link.addEventListener('click', event => {
                        event.preventDefault();
                        openFileWindow(link.dataset.url, link.dataset.filename);
                    });
                });
                document.querySelectorAll('#message-list .image-preview-link').forEach(link => {
                    link.addEventListener('click', event => {
                        event.preventDefault();
                        openFileWindow(link.dataset.src, link.dataset.filename || imageFilenameFromUrl(link.dataset.src));
                    });
                });
                document.querySelectorAll('#message-list .reply-reference').forEach(reference => {
                    reference.addEventListener('click', () => scrollToMessage(reference.dataset.target));
                });
            }

            // #sd 设置了 scroll-behavior: smooth，直接赋 scrollTop 会动画滚动；
            // 若期间被重渲染打断则停在半路且不再重试。这里临时关闭平滑做瞬时定位。
            function setScrollTopInstant(scroll, top) {
                const prev = scroll.style.scrollBehavior;
                scroll.style.scrollBehavior = 'auto';
                scroll.scrollTop = top;
                scroll.style.scrollBehavior = prev;
            }

            function loadMoreMessages() {
                if (loadMoreInFlight || windowStart <= 0 || !last_result) return;
                loadMoreInFlight = true;
                try {
                    const payload = normalizePayload(last_result);
                    if (!payload) return;
                    windowStart = Math.max(0, windowStart - SEGMENT_SIZE);
                    suppressStickNextRender = true;
                    renderMessages(payload);
                } finally {
                    loadMoreInFlight = false;
                }
            }

            function renderMessages(result) {
                const payload = normalizePayload(result);
                if (!payload) return;
                messageCache.clear();
                payload.messages.forEach(message => messageCache.set(message.id, message));
                const list = document.getElementById('message-list');
                const scroll = document.getElementById('sd');
                const prevScrollHeight = scroll.scrollHeight;
                const prevScrollTop = scroll.scrollTop;
                const atBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 100;
                const shouldStick = !suppressStickNextRender && atBottom;
                suppressStickNextRender = false;
                const total = payload.messages.length;
                if (shouldStick) {
                    windowStart = Math.max(0, total - SEGMENT_SIZE);
                } else {
                    windowStart = Math.min(windowStart, Math.max(0, total - SEGMENT_SIZE));
                }
                list.replaceChildren();
                if (windowStart > 0) {
                    const sentinelLi = document.createElement('li');
                    sentinelLi.className = 'load-more-row';
                    const loadBtn = document.createElement('button');
                    loadBtn.type = 'button';
                    loadBtn.className = 'load-more-btn';
                    loadBtn.textContent = '加载更早的消息（还有 ' + windowStart + ' 条）';
                    loadBtn.addEventListener('click', loadMoreMessages);
                    sentinelLi.appendChild(loadBtn);
                    list.appendChild(sentinelLi);
                }
                let lastTimestamp = null;
                const windowMessages = payload.messages.slice(windowStart);
                windowMessages.forEach((message, index) => {
                    const timestamp = messageMs(message);
                    if (timestamp && (index === 0 || (lastTimestamp !== null && (timestamp - lastTimestamp) / 1000 > TIME_THRESHOLD))) {
                        const separator = document.createElement('li');
                        separator.className = 'time-separator';
                        const separatorText = document.createElement('span');
                        separatorText.textContent = formatTimeForSeparator(timestamp);
                        separator.appendChild(separatorText);
                        list.appendChild(separator);
                    }
                    lastTimestamp = timestamp || lastTimestamp;

                    const li = document.createElement('li');
                    li.dataset.msgId = message.id;
                    if (message.type === 'system') {
                        li.className = 'system-row';
                        const systemText = document.createElement('p');
                        systemText.className = 'system-message-item';
                        systemText.textContent = message.content === 'clear' ? '--- 管理员清除了日志 ---' : message.content;
                        li.appendChild(systemText);
                        list.appendChild(li);
                        return;
                    }
                    const isOwn = message.user === currentUser;
                    if (isOwn) li.classList.add('own-message');
                    const avatar = document.createElement('div');
                    avatar.className = 'msg-avatar';
                    avatar.dataset.user = message.user;
                    avatar.textContent = message.user.charAt(0).toUpperCase();
                    avatar.style.borderColor = message.color;
                    avatar.title = message.user;
                    const content = document.createElement('div');
                    content.className = 'message-content';
                    if (!isOwn) {
                        const sender = document.createElement('div');
                        sender.className = 'message-sender';
                        sender.textContent = message.user;
                        content.appendChild(sender);
                    }
                    const bubble = document.createElement('div');
                    bubble.className = 'message-bubble';
                    if (message.recalled) {
                        bubble.classList.add('recalled-bubble');
                        bubble.textContent = '消息已撤回';
                    } else if (['file', 'image', 'audio', 'emoji'].includes(message.type)) {
                        appendAttachment(bubble, message);
                    } else if (!callRenderHooks(bubble, message, payload)) {
                        appendRichText(bubble, message.content, isOwn);
                    }
                    content.appendChild(bubble);
                    if (message.reply_to) {
                        const target = messageCache.get(message.reply_to);
                        const reference = document.createElement('button');
                        reference.type = 'button';
                        reference.className = 'reply-reference';
                        reference.dataset.target = message.reply_to;
                        reference.textContent = target ? '回复 ' + target.user + ': ' + messageSummary(target) : '回复的消息已不存在';
                        content.appendChild(reference);
                    }
                    if (selectMode) {
                        const checkboxWrap = document.createElement('div');
                        checkboxWrap.className = 'msg-checkbox-wrap';
                        const checkbox = document.createElement('input');
                        checkbox.type = 'checkbox';
                        checkbox.className = 'msg-checkbox';
                        checkbox.dataset.id = message.id;
                        checkbox.checked = selectedIds.has(message.id);
                        checkbox.addEventListener('click', event => event.stopPropagation());
                        checkbox.addEventListener('change', () => {
                            if (checkbox.checked) selectedIds.add(message.id);
                            else selectedIds.delete(message.id);
                            updateSelectedCount();
                        });
                        checkboxWrap.appendChild(checkbox);
                        if (isOwn) { li.append(content, checkboxWrap); }
                        else { li.append(checkboxWrap, avatar, content); }
                    } else {
                        li.append(avatar, content);
                    }
                    list.appendChild(li);
                });
                bindMessageLinks();
                updateSelectedCount();
                if (shouldStick) {
                    setScrollTopInstant(scroll, scroll.scrollHeight);
                    // 图片/字体/时间分隔线等异步内容加载会使列表增高；
                    // 阈值过大（200px）会在底部留下几十像素缝隙，且后续轮询不再判定为贴底，收紧为 4px
                    requestAnimationFrame(() => {
                        if (scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight > 4) {
                            setScrollTopInstant(scroll, scroll.scrollHeight);
                        }
                    });
                } else {
                    setScrollTopInstant(scroll, prevScrollTop + (scroll.scrollHeight - prevScrollHeight));
                }
            }

            // 发送成功后实时回显到聊天列表（无需等下一次轮询）
            function echoSentMessage(message) {
                if (!message || !message.id) return;
                const existing = last_result && (last_result.messages || []).some(m => m.id === message.id);
                if (existing) return;
                messageCache.set(message.id, message);
                const payload = last_result
                    ? Object.assign({}, last_result, { messages: (last_result.messages || []).concat([message]) })
                    : { messages: [message] };
                renderMessages(payload);
            }

            // ---- 更新函数：JSON 协议，保留旧四行响应的兼容解析 ----
            function update() {
                if (!sessionValid) return;
                $.ajax({
                    url: 'chattss',
                    type: 'POST',
                    data: { username: currentUser, update: upd },
                    dataType: 'json',
                    success: function(body) {
                        const payload = normalizePayload(body);
                        if (!payload) { showSessionAlert(); return; }
                        if (payload.server_time) clockOffset = payload.server_time * 1000 - Date.now();
                        setMuteState(payload.muted_until, payload.server_time);
                        notifyNewMentions(payload.messages);
                        const signature = JSON.stringify({ messages: payload.messages, muted_until: payload.muted_until });
                        last_result = payload;
                        if (signature !== lastMessageSignature) {
                            lastMessageSignature = signature;
                            renderMessages(payload);
                        }
                    },
                    error: function(xhr) {
                        if (xhr.status === 401 || xhr.status === 403) showSessionAlert();
                    }
                });

                // 在线用户
                let xhr2 = new XMLHttpRequest();
                xhr2.onreadystatechange = function() {
                    if (xhr2.readyState == 4) {
                        let os = xhr2.responseText.trim();
                        if (os !== lastOnlineUsersStr) {
                            lastOnlineUsersStr = os;
                            updateOnlineTags(os);
                        }
                    }
                };
                xhr2.open('post', 'get_online', true);
                xhr2.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
                xhr2.send('username=' + currentUser + '&update=' + upd);
            }

            function updateOnlineTags(str) {
                let c = document.getElementById('userTags');
                if (!c) return;
                let users = str.split(',').filter(u => u.trim() !== '');
                if (users.length === 0 || (users.length === 1 && users[0] === currentUser)) {
                    c.innerHTML = '<span class="alone-message">只有你在线</span>';
                    return;
                }
                let h = '';
                users.forEach(u => {
                    let s = (u === currentUser);
                    h +=
                        `<span class="user-tag ${s?'self':''}"><span class="tag-avatar" style="border-color:${s?'var(--fg-primary)':'var(--border-color)'};">${u.charAt(0).toUpperCase()}</span><span class="tag-name">${u}</span></span>`;
                });
                c.innerHTML = h;
            }

            function hideActionMenus() {
                document.getElementById('messageMenu').classList.remove('active');
                document.getElementById('avatarMenu').classList.remove('active');
            }

            function positionActionMenu(menu, x, y) {
                menu.classList.add('active');
                const rect = menu.getBoundingClientRect();
                const margin = 8;
                menu.style.left = Math.max(margin, Math.min(x, window.innerWidth - rect.width - margin)) + 'px';
                menu.style.top = Math.max(margin, Math.min(y, window.innerHeight - rect.height - margin)) + 'px';
            }

            let contextMessage = null;
            let contextUser = null;
            let contextMdAction = null;
            let dialogCallback = null;

            function openActionDialog(title, message, callback) {
                document.getElementById('actionDialogTitle').textContent = title;
                document.getElementById('actionDialogMessage').textContent = message;
                dialogCallback = callback;
                const dialog = document.getElementById('actionDialog');
                dialog.classList.add('active');
                dialog.setAttribute('aria-hidden', 'false');
            }

            function closeActionDialog() {
                const dialog = document.getElementById('actionDialog');
                dialog.classList.remove('active');
                dialog.setAttribute('aria-hidden', 'true');
                dialogCallback = null;
            }
            document.getElementById('actionDialogCancel').addEventListener('click', closeActionDialog);
            document.getElementById('actionDialogConfirm').addEventListener('click', () => {
                const callback = dialogCallback;
                closeActionDialog();
                if (callback) callback();
            });
            document.getElementById('actionDialog').addEventListener('click', event => {
                if (event.target.id === 'actionDialog') closeActionDialog();
            });

            async function postAction(url, body) {
                body = Object.assign({}, body, { username: currentUser, update: upd });
                const response = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                let result = {};
                try { result = await response.json(); } catch (_) {}
                if (!response.ok) {
                    if (result.muted_until) setMuteState(result.muted_until);
                    throw new Error(result.error || '操作失败');
                }
                return result;
            }

            function copyMessage(message) {
                const text = ['file', 'image', 'audio', 'emoji'].includes(message.type) ? attachmentName(message) : message.content;
                copyToClipboard(text).then(showCopyToast).catch(() => alert('复制失败'));
            }

            function recallContextMessage() {
                if (!contextMessage) return;
                const message = contextMessage;
                hideActionMenus();
                openActionDialog('撤回消息', '确认撤回这条消息吗？', () => {
                    postAction(u('/api/messages/' + encodeURIComponent(message.id) + '/recall'), {})
                        .then(update)
                        .catch(error => alert(error.message));
                });
            }

            function openMessageMenu(message, x, y) {
                if (!message || message.type === 'system' || message.recalled) return;
                contextMessage = message;
                contextUser = null;
                hideActionMenus();
                const menu = document.getElementById('messageMenu');
                const recallButton = menu.querySelector('[data-action="recall"]');
                recallButton.style.display = can('message.recall.any') || message.user === currentUser ? 'block' : 'none';
                // 插件菜单项：markdown 插件提供「显示原文/显示Markdown」切换
                const mdButton = menu.querySelector('[data-action="md-toggle"]');
                const pluginEntry = pluginMessageMenuEntry(message);
                contextMdAction = pluginEntry ? pluginEntry.action : null;
                if (mdButton) {
                    mdButton.style.display = pluginEntry ? 'block' : 'none';
                    if (pluginEntry) mdButton.textContent = pluginEntry.label;
                }
                positionActionMenu(menu, x, y);
            }

            // 插件可在 window.__chatterMessageMenu 注册菜单项提供器：
            // 函数签名 (message) => { label, action } | null
            function pluginMessageMenuEntry(message) {
                const providers = window.__chatterMessageMenu;
                if (!Array.isArray(providers) || providers.length === 0) return null;
                for (let i = 0; i < providers.length; i++) {
                    try {
                        const entry = providers[i](message);
                        if (entry) return entry;
                    } catch (_) {}
                }
                return null;
            }

            function openAvatarMenu(username, x, y) {
                const muteVisible = can('moderation.mute');
                const unmuteVisible = can('moderation.unmute');
                if ((!muteVisible && !unmuteVisible) || !username || username === currentUser) return;
                document.getElementById('avatarMuteBtn').style.display = muteVisible ? 'block' : 'none';
                document.getElementById('avatarUnmuteBtn').style.display = unmuteVisible ? 'block' : 'none';
                contextUser = username;
                contextMessage = null;
                hideActionMenus();
                positionActionMenu(document.getElementById('avatarMenu'), x, y);
            }

            document.getElementById('messageMenu').addEventListener('click', event => {
                const action = event.target.dataset.action;
                if (!action || !contextMessage) return;
                if (action === 'reply') {
                    setReplyTarget(contextMessage);
                    hideActionMenus();
                } else if (action === 'copy') {
                    copyMessage(contextMessage);
                    hideActionMenus();
                } else if (action === 'recall') {
                    recallContextMessage();
                } else if (action === 'md-toggle') {
                    const mdAction = contextMdAction;
                    hideActionMenus();
                    if (mdAction) mdAction();
                }
            });

            document.getElementById('avatarMenu').addEventListener('click', event => {
                const action = event.target.dataset.action;
                const username = contextUser;
                if (!action || !username) return;
                hideActionMenus();
                if (action === 'mute') {
                    const answer = window.prompt('禁言时长（1-86400 秒）', '60');
                    if (answer === null) return;
                    const duration = Number.parseInt(answer, 10);
                    if (!Number.isInteger(duration) || duration < 1 || duration > 86400) {
                        alert('禁言时长必须为 1-86400 秒');
                        return;
                    }
                    postAction(u('/api/mute'), { target: username, duration })
                        .then(update)
                        .catch(error => alert(error.message));
                } else if (action === 'unmute') {
                    openActionDialog('解除禁言', '确认解除 ' + username + ' 的禁言吗？', () => {
                        postAction(u('/api/unmute'), { target: username })
                            .then(update)
                            .catch(error => alert(error.message));
                    });
                }
            });

            document.addEventListener('click', event => {
                if (!event.target.closest('.message-menu') && !event.target.closest('.avatar-menu')) hideActionMenus();
            });
            window.addEventListener('resize', hideActionMenus);
            window.addEventListener('scroll', hideActionMenus, true);

            const messageList = document.getElementById('message-list');
            let longPressTimer = null;
            let longPressStart = null;
            function cancelLongPress() {
                if (longPressTimer) clearTimeout(longPressTimer);
                longPressTimer = null;
                longPressStart = null;
            }
            function openPointerMenu(event) {
                const bubble = event.target.closest('.message-bubble');
                const avatar = event.target.closest('.msg-avatar');
                const li = event.target.closest('li[data-msg-id]');
                if (bubble && li) openMessageMenu(messageCache.get(li.dataset.msgId), event.clientX, event.clientY);
                else if (avatar) openAvatarMenu(avatar.dataset.user, event.clientX, event.clientY);
            }
            messageList.addEventListener('contextmenu', event => {
                const target = event.target.closest('.message-bubble, .msg-avatar');
                if (!target) return;
                event.preventDefault();
                openPointerMenu(event);
            });
            messageList.addEventListener('pointerdown', event => {
                if (event.pointerType !== 'touch') return;
                const target = event.target.closest('.message-bubble, .msg-avatar');
                if (!target) return;
                longPressStart = { x: event.clientX, y: event.clientY };
                longPressTimer = setTimeout(() => {
                    openPointerMenu(event);
                    longPressTimer = null;
                }, 550);
            });
            messageList.addEventListener('pointermove', event => {
                if (!longPressStart) return;
                if (Math.hypot(event.clientX - longPressStart.x, event.clientY - longPressStart.y) > 12) cancelLongPress();
            });
            ['pointerup', 'pointercancel', 'pointerleave'].forEach(type => messageList.addEventListener(type, cancelLongPress));

            function scrollToMessage(messageId) {
                const element = Array.from(document.querySelectorAll('#message-list li[data-msg-id]')).find(item => item.dataset.msgId === messageId);
                if (!element) return;
                element.scrollIntoView({ block: 'center', behavior: 'smooth' });
                element.classList.remove('message-highlight');
                void element.offsetWidth;
                element.classList.add('message-highlight');
                setTimeout(() => element.classList.remove('message-highlight'), 1900);
            }

            // ================================================================
            //  10. 分享工具栏事件绑定
            // ================================================================
            document.getElementById('selectModeBtn').addEventListener('click', toggleSelectMode);

            document.getElementById('cancelSelectBtn').addEventListener('click', function() {
                clearSelected();
                // 如果选中数为0，隐藏取消按钮
                if (selectedIds.size === 0) {
                    this.style.display = 'none';
                }
                updateSelectedCount();
            });

            // ---- 生成分享图片 ----
            document.getElementById('generateShareBtn').addEventListener('click', function() {
                if (selectedIds.size === 0) {
                    alert('请至少选择一条消息');
                    return;
                }
                // 收集选中的消息数据
                const selectedMsgs = [];
                if (last_result && Array.isArray(last_result.messages)) {
                    last_result.messages.forEach(message => {
                        if (selectedIds.has(message.id)) {
                            selectedMsgs.push({
                                user: message.user,
                                content: message.content,
                                color: message.color || '#666',
                                time: message.time || '',
                                type: message.type,
                                recalled: message.recalled
                            });
                        }
                    });
                }
                if (selectedMsgs.length === 0) {
                    alert('未找到选中的消息，请重新选择');
                    return;
                }
                // 按时间排序（时间字符串排序可能不准确，但大致可用）
                // 由于时间格式是 "HH:MM:SS" 或 "Y-M-D H:M"，直接字符串排序大致可用
                // 更准确：用 parseTimeToTimestamp
                selectedMsgs.sort((a, b) => {
                    const ta = parseTimeToTimestamp(a.time);
                    const tb = parseTimeToTimestamp(b.time);
                    return ta - tb;
                });

                // 创建预览窗口
                const previewWin = createDraggableWindow('<svg class="icon" aria-hidden="true"><use href="#i-camera"/></svg> 分享预览', '', false);
                const contentArea = previewWin.querySelector('.window-content');
                contentArea.style.padding = '0';
                contentArea.style.background = 'var(--preview-bg)';
                contentArea.style.maxHeight = '70vh';

                // 构建预览 HTML
                let previewHtml = `<div class="share-preview-container" id="sharePreviewContainer">`;
                previewHtml +=
                    `<div class="preview-header"><svg class="icon" aria-hidden="true"><use href="#i-star"/></svg> syh's chatter · 分享 <svg class="icon" aria-hidden="true"><use href="#i-star"/></svg></div>`;
                previewHtml += `<div id="previewMessages">`;

                selectedMsgs.forEach((msg, idx) => {
                    const isOwn = (msg.user === currentUser);
                    const avatar = msg.user.charAt(0).toUpperCase();
                    let contentHtml = '';
                    let single = false;
                    const raw = msg.content;
                    if (raw.slice(0, 8) === '::file::') {
                        const fn = raw.substr(8);
                        contentHtml =
                            `<a href="javascript:void(0);" class="file-link" style="color:var(--link-color);text-decoration:none;">[文件] ${fn}</a>`;
                        single = (raw.trim() === '::file::' + fn);
                    } else if (raw.slice(0, 7) === '::img::') {
                        const iname = raw.substr(7);
                        contentHtml =
                            `<a href="javascript:void(0);" class="image-preview-link"><img src="./static/uploads/${iname}" style="max-width:180px;"></a>`;
                        single = (raw.trim() === '::img::' + iname);
                    } else if (raw.slice(0, 7) === '::wav::') {
                        const wn = raw.substr(7);
                        contentHtml = `<audio controls src="./static/uploads/${wn}" style="width:100%;"></audio>`;
                        single = (raw.trim() === '::wav::' + wn);
                    } else if (raw.slice(0, 9) === '::emoji::') {
                        const emojiName = raw.substr(9);
                        contentHtml =
                            `<img src="${u('/chat/emoji/static/')}${msg.user}/${emojiName}" class="emoji-inline" style="max-width:120px; max-height:120px; width:auto; height:auto;" onerror="this.parentElement.innerHTML='<span style=\\'color:var(--fg-muted);\\'>表情包加载失败</span>'">`;
                        single = (raw.trim() === '::emoji::' + emojiName);
                    } else {
                        contentHtml = highlightMentionIfNeeded(raw, isOwn);
                    }
                    const bubbleClass = 'preview-bubble' + (single ? ' single-attachment' : '');
                    previewHtml += `
                        <div class="preview-message">
                            <div class="preview-avatar" style="border-color:${msg.color};">${avatar}</div>
                            <div class="preview-body">
                                <div class="preview-sender">${msg.user}</div>
                                <div class="${bubbleClass}">${contentHtml}</div>
                            </div>
                        </div>
                    `;
                });

                previewHtml += `</div>`;
                previewHtml +=
                    `<div class="share-preview-footer"><button class="share-btn primary" id="downloadShareImgBtn"><svg class="icon" aria-hidden="true"><use href="#i-download"/></svg> 下载图片</button><button class="share-btn" id="closePreviewBtn">关闭</button></div>`;
                previewHtml += `</div>`;
                contentArea.innerHTML = previewHtml;

                // 关闭预览
                previewWin.querySelector('#closePreviewBtn').addEventListener('click', () => {
                    closeDraggableWindow(previewWin);
                });

                // 下载图片
                previewWin.querySelector('#downloadShareImgBtn').addEventListener('click', function() {
                    const container = document.getElementById('sharePreviewContainer');
                    if (!container) {
                        alert('预览容器未找到');
                        return;
                    }

                    // 1. 克隆容器，避免滚动干扰
                    const clone = container.cloneNode(true);
                    const computedStyle = getComputedStyle(container);

                    // 2. 设置克隆样式：完全展开，无滚动，固定定位（离开屏幕）
                    clone.style.position = 'fixed';
                    clone.style.left = '-9999px';
                    clone.style.top = '0';
                    clone.style.width = container.scrollWidth + 'px';
                    clone.style.height = 'auto';
                    clone.style.maxHeight = 'none';
                    clone.style.overflow = 'visible';
                    clone.style.background = computedStyle.backgroundColor || '#1a1a1a';
                    // 强制所有子元素展开
                    clone.querySelectorAll('*').forEach(el => {
                        el.style.maxHeight = 'none';
                        el.style.overflow = 'visible';
                    });

                    // 3. 添加到 body
                    document.body.appendChild(clone);

                    // 4. 等待一帧后截图
                    requestAnimationFrame(() => {
                        html2canvas(clone, {
                            scale: 2,
                            useCORS: true,
                            allowTaint: true,
                            backgroundColor: computedStyle.backgroundColor || '#1a1a1a',
                            logging: false,
                            width: clone.scrollWidth,
                            height: clone.scrollHeight,
                        }).then(canvas => {
                            document.body.removeChild(clone); // 清理克隆
                            // 下载图片
                            const link = document.createElement('a');
                            link.download = 'chatter_share_' + Date.now() + '.png';
                            link.href = canvas.toDataURL('image/png');
                            document.body.appendChild(link);
                            link.click();
                            document.body.removeChild(link);
                            showCopyToast();
                        }).catch(err => {
                            document.body.removeChild(clone);
                            console.error('截图失败:', err);
                            alert('生成图片失败: ' + err.message);
                        });
                    });
                });

                // 窗口关闭时清理
                const origClose = previewWin.querySelector('.close-window-btn');
                origClose.addEventListener('click', () => {
                    closeDraggableWindow(previewWin);
                });
            });

            // 文本文件发送（原有）
            const textFileSendBtn = document.getElementById('textFileSendBtn');
            if (textFileSendBtn) textFileSendBtn.addEventListener('click', openTextFileSendWindow);

            function openTextFileSendWindow() {
                if (openWindows['textfile-send']) {
                    focusWindow(openWindows['textfile-send']);
                    return;
                }
                const w = createDraggableWindow('发送文本文件', '', false, 'textfile-send');
                const c = w.querySelector('.window-content');
                c.innerHTML =
                    `<div style="display:flex; flex-direction:column; gap:12px;"><input type="text" id="txtFileName" placeholder="文件名（含后缀）" style="background:transparent; border:1px solid var(--border-color); padding:8px; color:var(--fg-primary);"><textarea id="txtFileContent" rows="8" placeholder="文件内容..." style="background:transparent; border:1px solid var(--border-color); padding:8px; color:var(--fg-primary); resize:vertical;"></textarea><button id="txtSendBtn" style="background:transparent; border:2px solid var(--border-color); color:var(--fg-primary); padding:8px; cursor:pointer;">发送</button></div>`;
                c.querySelector('#txtSendBtn').addEventListener('click', () => {
                    if (isMuted()) return;
                    const name = c.querySelector('#txtFileName').value.trim();
                    const content = c.querySelector('#txtFileContent').value;
                    if (!name || !content) return;
                    const blob = new Blob([content], { type: 'text/plain' });
                    const fd = new FormData();
                    fd.append('file', blob, name);
                    fd.append('username', currentUser);
                    fd.append('update', upd);
                    fd.append('reply_to', pendingReply ? pendingReply.id : '');
                    $.ajax({
                        url: u('/chatts_file?update=') + encodeURIComponent(upd),
                        type: 'POST',
                        data: fd,
                        processData: false,
                        contentType: false,
                        success: function(body) { upd = body.update || upd;
                            clearReply();
                            document.body.removeChild(w); },
                        error: function(xhr) { handleAjaxError(xhr, '发送失败'); }
                    });
                });
            }

            // ================================================================
            //  10.5 管理面板（Phase 6）：adminEntryBtn -> 弹窗加载 admin_content
            // ================================================================
            const adminEntryBtn = document.getElementById('adminEntryBtn');
            if (adminEntryBtn) adminEntryBtn.addEventListener('click', openAdminPanel);

            function openAdminPanel() {
                if (openWindows['admin']) {
                    focusWindow(openWindows['admin']);
                    return;
                }
                const w = createDraggableWindow('<svg class="icon" aria-hidden="true"><use href="#i-shield"/></svg> 管理面板', '<div class="admin-loading">加载中...</div>', false, 'admin');
                w.style.width = '900px';
                const c = w.querySelector('.window-content');
                fetch(u('/admin/content?update=') + encodeURIComponent(upd))
                    .then(r => {
                        if (!r.ok) throw new Error('HTTP ' + r.status);
                        return r.text();
                    })
                    .then(html => {
                        c.innerHTML = html;
                        if (window.ChatterAdmin) {
                            window.ChatterAdmin.init();
                            return;
                        }
                        const s = document.createElement('script');
                        s.src = u('/static/js/admin.js');
                        s.onload = () => {
                            if (window.ChatterAdmin) window.ChatterAdmin.init();
                        };
                        document.head.appendChild(s);
                    })
                    .catch(err => {
                        c.innerHTML = '<div class="admin-error">管理面板加载失败：' + err.message + '</div>';
                    });
            }

            // ================================================================
            //  11. 初始化：加载消息 + 选择模式状态恢复
            // ================================================================
            // 初始加载时，如果选择模式开启，需要渲染 checkbox
            // 但一开始 selectMode = false，所以正常渲染
            // 用户点击按钮后切换

            // 另外，如果页面刷新时 localStorage 保存了选择模式状态，可以恢复
            // 但我们不保存选择模式状态，默认关闭

            // 将 update 中的渲染逻辑替换为 renderMessages
            // 但 update 中已经调用了 renderMessages，所以不需要额外操作

            // 暴露一些变量给调试
            window.__chat = {
                selectMode: () => selectMode,
                selectedIds: selectedIds,
                toggleSelectMode: toggleSelectMode,
                clearSelected: clearSelected,
                renderMessages: renderMessages,
            };

            update();
            console.log('选择消息生成分享图片功能已加载');
        });
    