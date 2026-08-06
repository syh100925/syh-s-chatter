// markdown 渲染插件（注入于 chat.js 之前，注册渲染钩子接管文本消息气泡）。
// 能力：标题/粗斜体/删除线/行内码/围栏代码块(hljs 高亮)/链接/图片/列表/引用/分割线/段落/表格；
// 超过 10 行的代码块默认折叠；每条消息下方「原文」圆点切换显示原文。
// XSS 防护：先整体 HTML 转义，再解析；链接仅放行 http/https/mailto。
(function () {
    'use strict';

    var cache = new Map();    // message.id -> 渲染结果 HTML
    var rawIds = new Set();   // 已切换为「原文」显示的消息 id
    var formatOff = new Set(); // 已关闭智能格式化的代码块（键：消息id@块序号）
    var currentUser = '';

    // ---------------- 基础工具 ----------------

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function imageFilenameFromUrl(url) {
        try {
            var name = new URL(url).pathname.split('/').pop();
            return name || 'image';
        } catch (_) {
            return 'image';
        }
    }

    // 链接仅放行 http/https/mailto，其余按纯文本展示
    function safeLink(label, url) {
        var u = url.trim();
        if (/^(https?|mailto):/i.test(u)) {
            return '<a class="rich-link" href="' + u + '" target="_blank" rel="noopener noreferrer">' + label + '</a>';
        }
        return label + '（' + u + '）';
    }

    // 图片仅放行 http(s) 且带常见图片扩展名；预览复用聊天页 image-preview-link 逻辑
    function safeImage(alt, url) {
        var u = url.trim();
        var path = u;
        try {
            path = new URL(u).pathname;
        } catch (_) {}
        if (/^https?:\/\//i.test(u) && /\.(png|jpe?g|gif|bmp|webp|svg|ico)(?:$|[?#])/i.test(path)) {
            return '<a class="image-preview-link remote-image-link" href="javascript:void(0)" data-src="' + u +
                '" data-filename="' + escapeHtml(imageFilenameFromUrl(u)) + '">' +
                '<img class="md-img" src="' + u + '" alt="' + alt + '" loading="lazy"></a>';
        }
        return '![' + alt + '](' + u + ')';
    }

    // @当前用户 提及高亮（与聊天页 appendMentionText 规则一致）
    function mentionify(text) {
        if (!currentUser) return text;
        var escapedUser = currentUser.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        var pattern = new RegExp('(@' + escapedUser + ')(?![\\w\\u4e00-\\u9fff])', 'g');
        return text.replace(pattern, '<span class="mention">$1</span>');
    }

    // 行内解析：输入须已 HTML 转义；代码段先占位，避免内部再做格式解析
    function inline(text) {
        var codes = [];
        text = text.replace(/`([^`\n]+)`/g, function (m, c) {
            codes.push('<code>' + c + '</code>');
            return '\u0000' + (codes.length - 1) + '\u0000';
        });
        text = text.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
        text = text.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, '$1<em>$2</em>');
        text = text.replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, '$1<em>$2</em>');
        text = text.replace(/~~([^~\n]+)~~/g, '<del>$1</del>');
        text = text.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, function (m, alt, url) {
            return safeImage(alt, url);
        });
        text = text.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, function (m, label, url) {
            return safeLink(label, url);
        });
        text = text.replace(/(^|[\s(])(https?:\/\/[^\s<>"'，。！？、]+)/g, function (m, pre, url) {
            var value = url, trailing = '';
            while (/[.,!?;:)}\]，。！？、]$/.test(value)) {
                trailing = value.slice(-1) + trailing;
                value = value.slice(0, -1);
            }
            return pre + '<a class="rich-link" href="' + value + '" target="_blank" rel="noopener noreferrer">' +
                value + '</a>' + trailing;
        });
        text = mentionify(text);
        text = text.replace(/\u0000(\d+)\u0000/g, function (m, i) {
            return codes[+i] || '';
        });
        return text;
    }

    // ---------------- 代码块 ----------------

    function highlightCode(code, lang) {
        if (window.hljs) {
            try {
                if (lang && hljs.getLanguage(lang)) {
                    return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
                }
                return hljs.highlightAuto(code).value;
            } catch (_) {}
        }
        return escapeHtml(code);
    }

    // ---------------- 智能格式化（token 级：运算符空格 + 模板识别 + 深度缩进 + 超长自动换行，Tab=4） ----------------

    // 适用花括号式缩进规范化的语言（css/html/sql/yml 等按原样保留，仅 Tab 展开）
    var C_LIKE_RE = /^(js|jsx|ts|tsx|json|java|c|cpp|h|hpp|cs|csharp|php|go|golang|rust|rs|kt|kotlin|swift|dart|objc|objectivec)$/i;

    var MAX_LINE = 80;      // 超长自动换行宽度
    var INDENT4 = '    ';   // Tab=4，每层 4 空格

    var KEYWORD_SET = {};
    ('if else for while do switch case default break continue return new delete throw try catch finally ' +
        'class struct enum union namespace using template typename typedef const constexpr static extern ' +
        'inline volatile register auto int long short char float double void unsigned signed bool true false ' +
        'null nullptr this sizeof typeof instanceof in of public private protected virtual override final ' +
        'abstract extends implements interface function var let import export from as async await yield goto')
        .split(' ').forEach(function (k) { KEYWORD_SET[k] = true; });

    var TYPE_KW = {};
    ('int long short char float double void unsigned signed bool auto const constexpr static extern volatile ' +
        'register struct class enum union typedef typename template decltype')
        .split(' ').forEach(function (k) { TYPE_KW[k] = true; });

    var CONTROL_KW = {};
    ('if for while switch catch return new delete throw else do case default when')
        .split(' ').forEach(function (k) { CONTROL_KW[k] = true; });

    // 二元/需要两侧空格的运算符（+ - * & < > 等在规则里单独处理）
    var BINARY_SPACED = {};
    ('= == === !== != <= >= && || << >> < > / % += -= *= /= %= &= |= ^= <<= >>= ** **= ?? ??= ||= &&= => <=> >>> >>>=')
        .split(' ').forEach(function (o) { BINARY_SPACED[o] = true; });

    var MULTI_OPS = ['<<=', '>>=', '<=>', '>>>=', '===', '!==', '==', '!=', '<=', '>=', '&&', '||', '++', '--',
        '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=', '**=', '||=', '&&=', '??=', '->*', '->', '::', '=>',
        '??', '?.', '**', '<<', '>>', '>>>', '...'];
    var PUNCT_SET = {};
    '(){}[],;:?.'.split('').forEach(function (c) { PUNCT_SET[c] = true; });
    var NO_SPACE_SINGLE = {}; // @ 装饰器 / # 私有字段：# 与 @ 后不空格
    '#@'.split('').forEach(function (c) { NO_SPACE_SINGLE[c] = true; });

    function isWs(t) { return t.t === 'ws'; }
    function isNl(t) { return t.t === 'nl'; }
    function isSig(t) { return !!t && !isWs(t) && !isNl(t); }

    // ---------------- 词法器（字符串/块注释/原始字符串/预处理行整体为不可分割 token） ----------------

    function lexNumber(src, i) {
        var j = i;
        if (src[j] === '0' && (src[j + 1] === 'x' || src[j + 1] === 'X')) {
            j += 2;
            while (j < src.length && /[0-9a-fA-F_]/.test(src[j])) j++;
        } else if (src[j] === '0' && (src[j + 1] === 'b' || src[j + 1] === 'B')) {
            j += 2;
            while (j < src.length && /[01_]/.test(src[j])) j++;
        } else {
            while (j < src.length && /[0-9_]/.test(src[j])) j++;
            if (src[j] === '.' && src[j + 1] !== '.') {
                j++;
                while (j < src.length && /[0-9_]/.test(src[j])) j++;
            }
            if (src[j] === 'e' || src[j] === 'E') {
                var k = j + 1;
                if (src[k] === '+' || src[k] === '-') k++;
                if (/[0-9]/.test(src[k] || '')) {
                    j = k;
                    while (j < src.length && /[0-9_]/.test(src[j])) j++;
                }
            }
        }
        while (j < src.length && /[a-zA-Z_]/.test(src[j])) j++; // 后缀 u/l/f 等
        return j;
    }

    function tokenize(src) {
        var tokens = [], i = 0, n = src.length, lineStart = true;
        while (i < n) {
            var c = src[i];
            if (c === '\n') { tokens.push({ t: 'nl' }); i++; lineStart = true; continue; }
            if (c === ' ' || c === '\t' || c === '\r') { i++; continue; }
            if (lineStart && c === '#') {
                var eol = src.indexOf('\n', i);
                if (eol === -1) eol = n;
                tokens.push({ t: 'pp', s: src.slice(i, eol) });
                i = eol;
                continue;
            }
            lineStart = false;
            if (c === '/' && src[i + 1] === '/') {
                var e2 = src.indexOf('\n', i);
                if (e2 === -1) e2 = n;
                tokens.push({ t: 'lc', s: src.slice(i, e2) });
                i = e2;
                continue;
            }
            if (c === '/' && src[i + 1] === '*') {
                var end = src.indexOf('*/', i + 2);
                var e3 = end === -1 ? n : end + 2;
                tokens.push({ t: 'bc', s: src.slice(i, e3) });
                i = e3;
                continue;
            }
            if ((c === 'R' || c === 'r') && src[i + 1] === '"') {
                var rawM = /^R"([^()\s\\]{0,16})\(([\s\S]*?)\)\1"/.exec(src.slice(i));
                if (rawM) { tokens.push({ t: 'str', s: rawM[0] }); i += rawM[0].length; continue; }
            }
            if (c === '"' || c === "'" || c === '`') {
                var q = c, k2 = i + 1, body = q;
                while (k2 < n) {
                    var c2 = src[k2];
                    if (c2 === '\\' && k2 + 1 < n) { body += c2 + src[k2 + 1]; k2 += 2; continue; }
                    body += c2; k2++;
                    if (c2 === q) break;
                }
                tokens.push({ t: 'str', s: body });
                i = k2;
                continue;
            }
            if (/[0-9]/.test(c) || (c === '.' && /[0-9]/.test(src[i + 1] || ''))) {
                var jn = (c === '.') ? i + 1 : i;
                var je = lexNumber(src, jn);
                tokens.push({ t: 'num', s: src.slice(i, je) });
                i = je;
                continue;
            }
            if (/[A-Za-z_$]/.test(c)) {
                var j3 = i + 1;
                while (j3 < n && /[A-Za-z0-9_$]/.test(src[j3])) j3++;
                var word = src.slice(i, j3);
                tokens.push({ t: 'id', s: word, k: !!KEYWORD_SET[word] });
                i = j3;
                continue;
            }
            var matchedOp = null;
            for (var oi = 0; oi < MULTI_OPS.length; oi++) {
                if (src.substr(i, MULTI_OPS[oi].length) === MULTI_OPS[oi]) { matchedOp = MULTI_OPS[oi]; break; }
            }
            if (matchedOp) { tokens.push({ t: 'op', s: matchedOp }); i += matchedOp.length; continue; }
            if (PUNCT_SET[c]) { tokens.push({ t: 'op', s: c }); i++; continue; }
            tokens.push({ t: 'op', s: c });
            i++;
        }
        return tokens;
    }

    // ---------------- 模板区域识别：`map<int,int>`、`vector<vector<int>>` 的 <...> 不加空格 ----------------

    function detectTemplateRegions(tokens) {
        var regions = [];
        var lines = [];
        var lineStart = 0, i;
        for (i = 0; i < tokens.length; i++) {
            if (tokens[i].t === 'nl') { lines.push([lineStart, i]); lineStart = i + 1; }
        }
        lines.push([lineStart, tokens.length]);
        lines.forEach(function (range) {
            var lo = range[0], hi = range[1];
            var sigIdx = [];
            for (var k = lo; k < hi; k++) if (isSig(tokens[k])) sigIdx.push(k);
            for (var a = 0; a < sigIdx.length; a++) {
                var idx = sigIdx[a];
                if (tokens[idx].t !== 'op' || tokens[idx].s !== '<' || a === 0) continue;
                var prev = tokens[sigIdx[a - 1]];
                if (prev.t !== 'id') continue;
                var depth = 1, closeIdx = -1;
                for (var b = a + 1; b < sigIdx.length; b++) {
                    var tk = tokens[sigIdx[b]];
                    if (tk.t !== 'op') continue;
                    if (tk.s === '<') depth++;
                    else if (tk.s === '>') { depth--; if (depth === 0) { closeIdx = sigIdx[b]; break; } }
                    else if (tk.s === '>>') { depth -= 2; if (depth === 0) { closeIdx = sigIdx[b]; break; } if (depth < 0) break; }
                }
                if (closeIdx === -1) continue;
                var ok = true, hasNesting = false;
                for (var c = a + 1; c < sigIdx.length && sigIdx[c] < closeIdx; c++) {
                    var ct = tokens[sigIdx[c]];
                    if (ct.t === 'id' || ct.t === 'num') continue;
                    if (ct.t === 'op' && '::,<>()*&...='.indexOf(ct.s) !== -1) {
                        if (ct.s === ',' || ct.s === '<' || ct.s === '>' || ct.s === '>>' || ct.s === '::') hasNesting = true;
                        continue;
                    }
                    ok = false;
                    break;
                }
                if (!ok) continue;
                var afterIdx = closeIdx + 1;
                var after = null;
                while (afterIdx < hi && !isSig(tokens[afterIdx])) afterIdx++;
                if (afterIdx < hi) after = tokens[afterIdx];
                var afterOk = false;
                if (after === null) {
                    // 行尾闭合：要求内容含逗号/嵌套模板/::，避免 `a < b` 误判
                    afterOk = hasNesting;
                } else if (after.t === 'id') {
                    afterOk = true;
                } else if (after.t === 'op' && '([*&::>{=,'.indexOf(after.s) !== -1) {
                    afterOk = true;
                }
                if (prev.k && (prev.s === 'template' || prev.s === 'typename' || prev.s === 'class')) afterOk = true;
                if (afterOk) regions.push([sigIdx[a], closeIdx]);
            }
        });
        return regions;
    }

    // ---------------- 括号配对与对象字面量 ----------------

    function detectBracePairs(tokens) {
        var pair = {};
        var stack = [];
        for (var i = 0; i < tokens.length; i++) {
            var t = tokens[i];
            if (t.t === 'str' || t.t === 'bc' || t.t === 'lc' || t.t === 'pp' || t.t !== 'op') continue;
            if (t.s === '{' || t.s === '[') stack.push(i);
            else if (t.s === '}' || t.s === ']') {
                if (stack.length && ((t.s === '}' && tokens[stack[stack.length - 1]].s === '{') ||
                    (t.s === ']' && tokens[stack[stack.length - 1]].s === '['))) {
                    var o = stack.pop();
                    pair[o] = i;
                    pair[i] = o;
                }
            }
        }
        return pair;
    }

    function detectObjects(tokens, pair) {
        var objects = {};
        for (var i = 0; i < tokens.length; i++) {
            var t = tokens[i];
            if (t.t !== 'op' || t.s !== '{' || pair[i] === undefined) continue;
            var m1 = i + 1;
            while (m1 < tokens.length && !isNl(tokens[m1]) && !isSig(tokens[m1])) m1++;
            if (m1 >= tokens.length || isNl(tokens[m1])) continue;
            var first = tokens[m1];
            var okFirst = first.t === 'id' || first.t === 'str';
            var m2 = m1 + 1;
            while (m2 < tokens.length && !isNl(tokens[m2]) && !isSig(tokens[m2])) m2++;
            if (m2 >= tokens.length || isNl(tokens[m2])) continue;
            var okSecond = tokens[m2].t === 'op' && tokens[m2].s === ':';
            var prev = null;
            for (var k = i - 1; k >= 0 && !isNl(tokens[k]); k--) {
                if (isSig(tokens[k])) { prev = tokens[k]; break; }
            }
            var afterImport = !!prev && prev.t === 'id' && (prev.s === 'import' || prev.s === 'export');
            if ((okFirst && okSecond) || afterImport) objects[i] = true;
        }
        return objects;
    }

    // ---------------- 空格规范化（单遍扫描，输出含归一化空白 token 的流） ----------------

    function normalizeSpacing(tokens) {
        var regions = detectTemplateRegions(tokens);
        var pair = detectBracePairs(tokens);
        var objects = detectObjects(tokens, pair);
        var objectClose = {};
        Object.keys(objects).forEach(function (i) {
            if (pair[+i] !== undefined) objectClose[pair[+i]] = true;
        });

        function inRegion(i) {
            for (var r = 0; r < regions.length; r++) {
                if (i >= regions[r][0] && i <= regions[r][1]) return true;
            }
            return false;
        }

        var out = [];
        var prev = null;
        var tDepth = 0;        // 未闭合三元 ? 计数
        var tDepthStack = [];  // 进入 {} 时暂存并清零（对象冒号不受外部三元影响）
        var parenStack = [];
        var forParen = false;  // 是否处于 for(...) 圆括号内（范围 for 的冒号）
        var stmtFirst = null;  // 当前语句第一个 token（基类列表冒号判断）

        function resolve(t, i) {
            if (t.t === 'id') {
                return { cls: 'wordy', controlKw: !!t.k && !!CONTROL_KW[t.s], typeKw: !!t.k && !!TYPE_KW[t.s], op: null };
            }
            if (t.t === 'num' || t.t === 'str' || t.t === 'lc' || t.t === 'bc') return { cls: 'wordy', op: null };
            if (t.t === 'pp') return { cls: 'none', op: null };
            var s = t.s;
            if (s === ')' || s === ']' || s === '}') return { cls: 'wordy', op: s };
            if (s === '(' || s === '[' || s === '{') return { cls: 'open', op: s };
            if (s === '++' || s === '--') {
                var nx = null;
                for (var k = i + 1; k < tokens.length; k++) {
                    if (isNl(tokens[k])) break;
                    if (isSig(tokens[k])) { nx = tokens[k]; break; }
                }
                if (nx && (nx.t === 'id' || nx.t === 'num')) return { cls: 'unary', op: s };
                return { cls: 'wordy', op: s };
            }
            if (s === '!' || s === '~') return { cls: 'unary', op: s };
            if (s === '+' || s === '-') {
                if (prev && prev.cls === 'wordy' && !prev.controlKw && !prev.typeKw) return { cls: 'binary', op: s };
                return { cls: 'unary', op: s };
            }
            if (s === '*' || s === '&') {
                if (prev && (prev.typeKw || (prev.cls === 'wordy' && prev.region))) return { cls: 'unary', op: s }; // 指针/引用：后不空格
                if (prev && prev.cls === 'wordy' && !prev.controlKw && !prev.typeKw) return { cls: 'binary', op: s };
                return { cls: 'unary', op: s };
            }
            if (s === '<') return inRegion(i) ? { cls: 'open', op: s } : { cls: 'binary', op: s };
            if (s === '>' || s === '>>') return inRegion(i) ? { cls: 'wordy', region: true, op: s } : { cls: 'binary', op: s };
            if (s === '.' || s === '->' || s === '::' || s === '?.' || s === '...' || s === '->*' || NO_SPACE_SINGLE[s]) {
                return { cls: 'none', op: s };
            }
            if (s === ',' || s === ';' || s === '?' || s === ':') return { cls: 'binary', op: s };
            if (BINARY_SPACED[s]) return { cls: 'binary', op: s };
            return { cls: 'none', op: s };
        }

        function needSpace(t, i) {
            if (!prev) return false;
            if (t.t === 'lc') return true;
            if (t.t === 'bc') return prev.cls === 'wordy' || prev.cls === 'binary';
            if (t.t === 'pp') return true;
            var s = t.t === 'op' ? t.s : null;
            if (s === '(') return prev.controlKw || prev.cls === 'binary';
            if (s === '[') return prev.controlKw || prev.cls === 'binary';
            if (s === '{') {
                if (prev.cls === 'open' || prev.cls === 'unary' || prev.cls === 'none') return false;
                return true;
            }
            if (s === '}') return !!objectClose[i];
            if (s === ')' || s === ']' || s === ',' || s === ';') return false;
            if (s === '.' || s === '->' || s === '::' || s === '?.' || s === '...' || s === '->*' || NO_SPACE_SINGLE[s]) return false;
            if (s === '?') return prev.cls === 'wordy' || prev.cls === 'binary';
            if (s === ':') {
                if (tDepth > 0) return prev.cls === 'wordy' || prev.cls === 'binary';   // 三元
                if (forParen && (prev.cls === 'wordy' || prev.cls === 'binary')) return true; // 范围 for
                if (stmtFirst && (stmtFirst.s === 'class' || stmtFirst.s === 'struct')) return true; // 基类列表
                return false; // 对象/标签
            }
            if (s === '++' || s === '--') {
                var nx = null;
                for (var k = i + 1; k < tokens.length; k++) {
                    if (isNl(tokens[k])) break;
                    if (isSig(tokens[k])) { nx = tokens[k]; break; }
                }
                if (nx && (nx.t === 'id' || nx.t === 'num')) return prev.cls === 'binary' || prev.cls === 'wordy';
                return false;
            }
            if (s === '!' || s === '~') return prev.cls === 'wordy' || prev.cls === 'binary';
            if (s === '+' || s === '-') {
                if (prev.cls === 'wordy' && !prev.controlKw && !prev.typeKw) return true; // 二元
                if (s === '-' && prev.cls === 'unary' && prev.op === '-') return true;   // a - -b 防粘连
                if (s === '+' && prev.cls === 'unary' && prev.op === '+') return true;   // a + +b 防粘连
                if (prev.controlKw || prev.typeKw) return true;                          // return -5 / case -1
                return prev.cls === 'binary';
            }
            if (s === '*' || s === '&') {
                if (prev.typeKw || (prev.cls === 'wordy' && prev.region)) return true;   // 指针/引用
                if (prev.cls === 'wordy' && !prev.controlKw && !prev.typeKw) return true; // 二元
                if (prev.cls === 'binary') return true;                                   // 一元（= *p、, &x）
                if (prev.controlKw) return true;                                          // return *p
                return false;
            }
            if (BINARY_SPACED[s]) {
                if (inRegion(i) && (s === '<' || s === '>' || s === '>>')) return false;
                return prev.cls === 'wordy' || prev.cls === 'binary';
            }
            if (t.t === 'id' || t.t === 'num' || t.t === 'str') {
                if (t.t === 'str' && t.s.charAt(0) === '`' && prev.cls === 'wordy') return false; // 标签模板
                return prev.cls === 'wordy' || prev.cls === 'binary';
            }
            return true;
        }

        for (var i = 0; i < tokens.length; i++) {
            var t = tokens[i];
            if (t.t === 'nl') { out.push(t); prev = null; continue; }
            var rs = resolve(t, i);
            if (prev && needSpace(t, i)) out.push({ t: 'ws', s: ' ' });
            out.push(t);
            if (t.t === 'op' && t.s === '{' && objects[i]) out.push({ t: 'ws', s: ' ' }); // 对象字面量填充
            if (t.t === 'op') {
                var os = t.s;
                if (os === '(') { parenStack.push(forParen); forParen = !!(prev && prev.controlKw && prev.s === 'for'); }
                else if (os === ')') { if (parenStack.length) forParen = parenStack.pop(); }
                else if (os === '{') { tDepthStack.push(tDepth); tDepth = 0; stmtFirst = null; }
                else if (os === '}') { if (tDepthStack.length) tDepth = tDepthStack.pop(); stmtFirst = null; }
                else if (os === ';' && parenStack.length === 0) { tDepth = 0; stmtFirst = null; }
                else if (os === '?') tDepth++;
                else if (os === ':' && tDepth > 0) tDepth--;
            }
            if (stmtFirst === null) stmtFirst = t;
            prev = rs;
            prev.op = t.t === 'op' ? t.s : null;
        }
        return out;
    }

    // ---------------- 超长自动换行（>80 字符的 { } / [ ] 单行内容按顶层分隔符拆成多行） ----------------

    function wrapLongLines(tokens) {
        var guard = 0;
        while (guard++ < 1000) {
            var depthBefore = [];
            var d = 0, i;
            for (i = 0; i < tokens.length; i++) {
                var t = tokens[i];
                depthBefore.push(d);
                if (t.t === 'op' && (t.s === '{' || t.s === '[')) d++;
                else if (t.t === 'op' && (t.s === '}' || t.s === ']')) { d--; if (d < 0) d = 0; }
            }
            var pair = detectBracePairs(tokens);
            var lines = [];
            var ls = 0;
            for (i = 0; i < tokens.length; i++) if (tokens[i].t === 'nl') { lines.push([ls, i]); ls = i + 1; }
            lines.push([ls, tokens.length]);
            var changed = false;
            for (var li = 0; li < lines.length && !changed; li++) {
                var lo = lines[li][0], hi = lines[li][1];
                var base = depthBefore[lo];
                for (var kb = lo; kb < hi; kb++) {
                    var tb = tokens[kb];
                    if (tb.t !== 'op' || (tb.s !== '}' && tb.s !== ']')) break;
                    base = Math.max(0, base - 1);
                }
                var len = 4 * base;
                for (var kc = lo; kc < hi; kc++) len += tokens[kc].t === 'ws' ? 1 : tokens[kc].s.length;
                if (len <= MAX_LINE) continue;
                var openIdx = -1, closeIdx = -1, kd = lo;
                while (kd < hi) {
                    openIdx = -1;
                    for (; kd < hi; kd++) {
                        var td = tokens[kd];
                        if (td.t === 'op' && (td.s === '{' || td.s === '[') && pair[kd] !== undefined && pair[kd] < hi) {
                            openIdx = kd;
                            closeIdx = pair[kd];
                            break;
                        }
                    }
                    if (openIdx === -1) break;
                    var sepType = null, seps = [];
                    var nest = 0;
                    for (var ke = openIdx + 1; ke < closeIdx; ke++) {
                        var te = tokens[ke];
                        if (te.t === 'str' || te.t === 'bc' || te.t === 'lc') continue;
                        if (te.t !== 'op') continue;
                        if (te.s === '(' || te.s === '{' || te.s === '[') nest++;
                        else if (te.s === ')' || te.s === '}' || te.s === ']') { nest--; if (nest < 0) nest = 0; }
                        else if (nest === 0 && (te.s === ';' || te.s === ',')) {
                            if (te.s === ';') { if (sepType !== ';') { sepType = ';'; seps = []; } seps.push(ke); }
                            else { if (sepType === null) sepType = ','; seps.push(ke); }
                        }
                    }
                    if (!sepType) { kd = openIdx + 1; continue; } // 该块无可拆分隔符，试下一个块
                    var items = [];
                    var itemStart = openIdx + 1;
                    seps.forEach(function (sp) {
                        if (sp > itemStart) items.push([itemStart, sp + 1]); // 分隔符随前一项
                        itemStart = sp + 1;
                    });
                    if (itemStart < closeIdx) items.push([itemStart, closeIdx]);
                    var newT = [];
                    for (var kf = lo; kf <= openIdx; kf++) newT.push(tokens[kf]);
                    newT.push({ t: 'nl' });
                    items.forEach(function (it) {
                        for (var kg = it[0]; kg < it[1]; kg++) newT.push(tokens[kg]);
                        newT.push({ t: 'nl' });
                    });
                    for (var kh = closeIdx; kh < hi; kh++) newT.push(tokens[kh]);
                    tokens = tokens.slice(0, lo).concat(newT, tokens.slice(hi));
                    changed = true;
                    break;
                }
            }
            if (!changed) break;
        }
        return tokens;
    }

    // ---------------- 深度缩进渲染（每层 4 空格，行首闭合括号先减深度） ----------------

    function renderIndented(tokens) {
        var out = '', depth = 0, lineStart = true, buf = '', pendingCloses = 0, i;
        for (i = 0; i < tokens.length; i++) {
            var t = tokens[i];
            if (t.t === 'nl') {
                out += buf.replace(/\s+$/, '') + '\n';
                buf = '';
                lineStart = true;
                pendingCloses = 0;
                continue;
            }
            if (t.t === 'ws') {
                if (!lineStart) buf += ' ';
                continue;
            }
            if (lineStart) {
                var c2 = i, closes = 0;
                while (c2 < tokens.length && tokens[c2].t === 'op' &&
                    (tokens[c2].s === '}' || tokens[c2].s === ']')) {
                    closes++;
                    c2++;
                }
                depth = Math.max(0, depth - closes);
                pendingCloses = closes;
                buf += INDENT4.repeat(depth);
                lineStart = false;
            }
            if (t.t === 'op' && (t.s === '{' || t.s === '[')) depth++;
            else if (t.t === 'op' && (t.s === '}' || t.s === ']')) {
                if (pendingCloses > 0) pendingCloses--;
                else depth = Math.max(0, depth - 1);
            }
            buf += t.s;
        }
        return out + buf.replace(/\s+$/, '');
    }

    function formatCode(src, lang) {
        var text = String(src).replace(/\t/g, '    ');
        var langKey = String(lang || '').toLowerCase();
        if (!C_LIKE_RE.test(langKey)) return text;
        var tokens = tokenize(text);
        tokens = normalizeSpacing(tokens);
        tokens = wrapLongLines(tokens);
        return renderIndented(tokens);
    }

    // 超过 10 行默认折叠；头部提供「格式化」开关、「复制」与「展开/收起」按钮
    function buildCodeBlock(rawCode, lang, msgKey, blockIndex) {
        var lines = rawCode.replace(/\n$/, '').split('\n');
        var langClass = /^[A-Za-z0-9_+\-.#]+$/.test(lang) ? lang : '';
        var collapsed = lines.length > 10;
        var key = (msgKey || '') + '@' + blockIndex;
        var fmtActive = !formatOff.has(key);
        var displayCode = fmtActive ? formatCode(rawCode, langClass) : rawCode;
        var head = '<div class="md-code-head">' +
            '<span class="md-code-lang">' + escapeHtml(langClass || 'code') + '</span>' +
            '<span class="md-code-count">' + lines.length + ' 行</span>' +
            '<button type="button" class="md-code-fmt' + (fmtActive ? ' active' : '') + '" title="智能格式化：缩进/运算符空格/模板识别/超长自动换行（Tab=4），影响显示与复制">格式化</button>' +
            '<button type="button" class="md-code-copy">复制</button>' +
            (collapsed ? '<button type="button" class="md-code-toggle">展开</button>' : '') +
            '</div>';
        var body = '<pre class="md-code-body' + (collapsed ? ' collapsed' : '') + '">' +
            '<code class="hljs' + (langClass ? ' language-' + langClass : '') + '" data-md-raw="' + escapeHtml(rawCode) + '">' +
            highlightCode(displayCode, langClass) + '</code></pre>';
        return '<div class="md-codeblock" data-md-key="' + key + '">' + head + body + '</div>';
    }

    // ---------------- 表格 ----------------

    function splitCells(line) {
        return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|');
    }

    function parseAligns(separatorLine) {
        return splitCells(separatorLine).map(function (cell) {
            var c = cell.trim();
            if (!/^:?-{1,}:?$/.test(c)) return '';
            if (c.charAt(0) === ':' && c.charAt(c.length - 1) === ':') return 'center';
            if (c.charAt(c.length - 1) === ':') return 'right';
            return 'left';
        });
    }

    function buildTable(rows) {
        var aligns = parseAligns(rows[1]);
        var html = '<div class="md-table-wrap"><table class="md-table"><thead><tr>';
        splitCells(rows[0]).forEach(function (cell, i) {
            html += '<th' + (aligns[i] ? ' style="text-align:' + aligns[i] + '"' : '') + '>' +
                inline(cell.trim()) + '</th>';
        });
        html += '</tr></thead><tbody>';
        for (var i = 2; i < rows.length; i++) {
            html += '<tr>';
            splitCells(rows[i]).forEach(function (cell, j) {
                html += '<td' + (aligns[j] ? ' style="text-align:' + aligns[j] + '"' : '') + '>' +
                    inline(cell.trim()) + '</td>';
            });
            html += '</tr>';
        }
        return html + '</tbody></table></div>';
    }

    function isTableSeparator(line) {
        var cells = splitCells(line);
        if (cells.length < 2) return false;
        return cells.every(function (c) {
            return /^:?-{1,}:?$/.test(c.trim());
        });
    }

    // ---------------- 块级解析 ----------------

    function isBlockStart(line) {
        if (!line.trim()) return true;
        if (/^```/.test(line)) return true;
        if (/^(#{1,6})\s/.test(line)) return true;
        if (/^>\s?/.test(line)) return true;
        if (/^\s*[-*+]\s/.test(line)) return true;
        if (/^\s*\d+[.)]\s/.test(line)) return true;
        if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) return true;
        return false;
    }

    function renderMarkdown(src, msgKey) {
        var lines = String(src).split(/\r?\n/);
        var html = '';
        var i = 0;
        var blockIndex = 0;
        while (i < lines.length) {
            var line = lines[i];

            // 围栏代码块
            var fenceMatch = line.match(/^```([\w+\-.#]*)\s*$/);
            if (fenceMatch) {
                var codeLines = [];
                i++;
                while (i < lines.length && !/^```\s*$/.test(lines[i])) {
                    codeLines.push(lines[i]);
                    i++;
                }
                i++;
                html += buildCodeBlock(codeLines.join('\n'), fenceMatch[1], msgKey, blockIndex++);
                continue;
            }

            // 表格（当前行含 |，下一行为分隔行）
            if (line.indexOf('|') !== -1 && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
                var rows = [line];
                i++;
                while (i < lines.length && lines[i].indexOf('|') !== -1) {
                    rows.push(lines[i]);
                    i++;
                }
                html += buildTable(rows);
                continue;
            }

            if (!line.trim()) {
                i++;
                continue;
            }

            // 标题
            var headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
            if (headingMatch) {
                var level = headingMatch[1].length;
                html += '<h' + level + '>' + inline(escapeHtml(headingMatch[2])) + '</h' + level + '>';
                i++;
                continue;
            }

            // 分割线
            if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
                html += '<hr>';
                i++;
                continue;
            }

            // 引用
            if (/^>\s?/.test(line)) {
                var quoteLines = [];
                while (i < lines.length && /^>\s?/.test(lines[i])) {
                    quoteLines.push(lines[i].replace(/^>\s?/, ''));
                    i++;
                }
                html += '<blockquote>' + quoteLines.map(function (l) {
                    return inline(escapeHtml(l));
                }).join('\n') + '</blockquote>';
                continue;
            }

            // 无序列表
            var ulMatch = line.match(/^\s*[-*+]\s+(.*)$/);
            if (ulMatch) {
                var ulItems = [ulMatch[1]];
                i++;
                while (i < lines.length && (ulMatch = lines[i].match(/^\s*[-*+]\s+(.*)$/))) {
                    ulItems.push(ulMatch[1]);
                    i++;
                }
                html += '<ul>' + ulItems.map(function (it) {
                    return '<li>' + inline(escapeHtml(it)) + '</li>';
                }).join('') + '</ul>';
                continue;
            }

            // 有序列表
            var olMatch = line.match(/^\s*\d+[.)]\s+(.*)$/);
            if (olMatch) {
                var olItems = [olMatch[1]];
                i++;
                while (i < lines.length && (olMatch = lines[i].match(/^\s*\d+[.)]\s+(.*)$/))) {
                    olItems.push(olMatch[1]);
                    i++;
                }
                html += '<ol>' + olItems.map(function (it) {
                    return '<li>' + inline(escapeHtml(it)) + '</li>';
                }).join('') + '</ol>';
                continue;
            }

            // 段落：收集到下一个块元素
            var para = [line];
            i++;
            while (i < lines.length && !isBlockStart(lines[i])) {
                para.push(lines[i]);
                i++;
            }
            html += '<p>' + inline(escapeHtml(para.join('\n'))) + '</p>';
        }
        return html;
    }

    // 是否含 Markdown 语法标记（否则保持原生纯文本渲染）
    var MD_SYNTAX_RE = /(?:^|\n)[^\S\n]*(?:#{1,6}\s|```|>\s|[-*+]\s|\d+[.)]\s|(?:-{3,}|\*{3,}|_{3,})\s*$)|(?:\*\*|__|~~|`[^`\n]+`|!\[[^\]]*\]\([^)\s]+\)|\[[^\]]+\]\([^)\s]+\)|https?:\/\/|\|[^|\n]*\|)/;

    // ---------------- 气泡渲染与「原文」开关 ----------------

    function renderBubble(bubble, message, raw) {
        var id = message.id;
        if (raw) {
            bubble.textContent = message.content;
            return;
        }
        var html = cache.get(id);
        if (html === undefined) {
            html = renderMarkdown(message.content, id);
            cache.set(id, html);
            if (cache.size > 500) cache.delete(cache.keys().next().value);
        }
        bubble.innerHTML = html;
    }

    function hook(bubble, message, payload) {
        if (!message || typeof message.content !== 'string' || !message.content) return false;
        if (message.type === 'system') return false;
        if (message.recalled) return false;
        if (['file', 'image', 'audio', 'emoji'].indexOf(message.type) !== -1) return false;

        var raw = message.content;
        var id = message.id;
        if (rawIds.has(id)) {
            bubble.textContent = raw;
        } else if (MD_SYNTAX_RE.test(raw)) {
            renderBubble(bubble, message, false);
        } else {
            bubble.innerHTML = inline(escapeHtml(raw));
        }

        bubble.classList.add('md-rendered');
        return true;
    }

    // 选择器转义：优先 CSS.escape，降级为反斜杠转义非字母数字字符
    function escapeSelector(id) {
        if (window.CSS && window.CSS.escape) return window.CSS.escape(id);
        return String(id).replace(/[^a-zA-Z0-9_-]/g, function (c) {
            return '\\' + c;
        });
    }

    // 「原文」切换改到消息右键菜单：__chatterMessageMenu 提供器
    var menuProviders = window.__chatterMessageMenu = window.__chatterMessageMenu || [];
    menuProviders.push(function (message) {
        if (!message || typeof message.content !== 'string' || !message.content) return null;
        if (message.type === 'system' || message.recalled) return null;
        if (['file', 'image', 'audio', 'emoji'].indexOf(message.type) !== -1) return null;
        var id = message.id;
        var nowRaw = rawIds.has(id);
        return {
            label: nowRaw ? '显示Markdown' : '显示原文',
            action: function () {
                if (nowRaw) rawIds.delete(id);
                else {
                    rawIds.add(id);
                    if (rawIds.size > 2000) rawIds.delete(rawIds.values().next().value);
                }
                var li = document.querySelector('#message-list li[data-msg-id="' + escapeSelector(id) + '"]');
                if (!li) return;
                var bubble = li.querySelector('.message-bubble');
                if (bubble) renderBubble(bubble, message, !nowRaw);
            }
        };
    });

    // ---------------- 复制与代码块交互（事件委托，重渲染后依然有效） ----------------

    function copyText(text) {
        if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(text);
        }
        return new Promise(function (resolve, reject) {
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            try {
                document.execCommand('copy');
                resolve();
            } catch (e) {
                reject(e);
            } finally {
                document.body.removeChild(ta);
            }
        });
    }

    function setCopyFeedback(btn, text) {
        btn.textContent = text;
        setTimeout(function () {
            btn.textContent = '复制';
        }, 1500);
    }

    document.addEventListener('click', function (event) {
        if (!event.target || !event.target.closest) return;
        // 格式化开关：开=智能格式化（缩进+空格，Tab=4，默认），关=原样显示/复制
        var fmtBtn = event.target.closest('.md-code-fmt');
        if (fmtBtn) {
            var fmtBlock = fmtBtn.closest('.md-codeblock');
            var fmtKey = fmtBlock ? fmtBlock.dataset.mdKey : '';
            if (formatOff.has(fmtKey)) {
                formatOff.delete(fmtKey);
                fmtBtn.classList.add('active');
            } else {
                formatOff.add(fmtKey);
                fmtBtn.classList.remove('active');
                if (formatOff.size > 1000) formatOff.delete(formatOff.keys().next().value);
            }
            if (fmtKey) cache.delete(String(fmtKey).split('@')[0]); // 下次重渲染按新状态构建
            // 立即按新状态重渲染当前代码块
            var fmtCodeEl = fmtBlock ? fmtBlock.querySelector('code') : null;
            if (fmtCodeEl) {
                var fmtRaw = fmtCodeEl.dataset.mdRaw !== undefined ? fmtCodeEl.dataset.mdRaw : fmtCodeEl.textContent;
                var fmtLang = '';
                var fmtLangMatch = /(?:^|\s)language-([\w+#.-]+)/.exec(fmtCodeEl.className || '');
                if (fmtLangMatch) fmtLang = fmtLangMatch[1];
                fmtCodeEl.innerHTML = highlightCode(formatOff.has(fmtKey) ? fmtRaw : formatCode(fmtRaw, fmtLang), fmtLang);
            }
            return;
        }
        // 复制：格式化开启时复制智能格式化后的代码
        var copyBtn = event.target.closest('.md-code-copy');
        if (copyBtn) {
            var block = copyBtn.closest('.md-codeblock');
            var codeEl = block ? block.querySelector('code') : null;
            var raw = codeEl && codeEl.dataset.mdRaw !== undefined ? codeEl.dataset.mdRaw : (codeEl ? codeEl.textContent : '');
            var lang = '';
            if (codeEl) {
                var langMatch = /(?:^|\s)language-([\w+#.-]+)/.exec(codeEl.className || '');
                if (langMatch) lang = langMatch[1];
            }
            var text = formatOff.has(block.dataset.mdKey) ? raw : formatCode(raw, lang);
            copyText(text).then(function () {
                setCopyFeedback(copyBtn, '已复制');
            }).catch(function () {
                setCopyFeedback(copyBtn, '复制失败');
            });
            return;
        }
        var toggleBtn = event.target.closest('.md-code-toggle');
        if (toggleBtn) {
            var block = toggleBtn.closest('.md-codeblock');
            var body = block.querySelector('.md-code-body');
            var expanded = body.classList.toggle('expanded');
            toggleBtn.textContent = expanded ? '收起' : '展开';
            return;
        }
        var bodyEl = event.target.closest('.md-code-body.collapsed:not(.expanded)');
        if (bodyEl) {
            bodyEl.classList.add('expanded');
            var btn = bodyEl.closest('.md-codeblock').querySelector('.md-code-toggle');
            if (btn) btn.textContent = '收起';
        }
    });

    // ---------------- 注册渲染钩子 ----------------

    var hooks = window.__chatterRenderHooks = window.__chatterRenderHooks || [];
    hooks.push(function (bubble, message, payload) {
        if (payload && payload.current_user) currentUser = payload.current_user;
        return hook(bubble, message, payload);
    });

    // 供自测使用的格式化入口
    window.__markdownPlugin = window.__markdownPlugin || {};
    window.__markdownPlugin.formatCode = formatCode;
})();
