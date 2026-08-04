import { FormEvent, KeyboardEvent, PointerEvent as ReactPointerEvent, ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import remarkBreaks from 'remark-breaks'
import remarkGfm from 'remark-gfm'
import {
  Archive,
  Ban,
  Bell,
  Bookmark,
  Check,
  ChevronLeft,
  Copy,
  Download,
  FileUp,
  Flag,
  Forward,
  Hash,
  LogOut,
  MessageCircle,
  Moon,
  MoreHorizontal,
  Palette,
  Paperclip,
  Pin,
  Pencil,
  Plus,
  Search,
  Send,
  Settings,
  Sun,
  Smile,
  Trash2,
  UserRound,
  Users,
  VolumeX,
  X,
  Zap,
} from 'lucide-react'
import { formatTime, initials, markerFilename } from './utils'
import './styles.css'

const PUBLIC_CONVERSATION = 'public'

type User = {
  username: string
  display_name: string
  color: string
  avatar_url?: string | null
  status?: string
  bio?: string
  role?: string
  blocked?: boolean
  blocked_by?: boolean
}

type Reaction = { count: number; users: string[]; reacted: boolean }

type Attachment = {
  id?: string | null
  name: string
  mime?: string
  size?: number
  url: string
}

type PreviewTarget = {
  id?: string | null
  name: string
  mime?: string
  url: string
  kind: 'text' | 'image'
}

type HighlightEngine = {
  getLanguage: (language: string) => unknown
  highlight: (code: string, options: { language: string; ignoreIllegals?: boolean }) => { value: string }
  highlightAuto: (code: string) => { value: string; language?: string }
}

declare global {
  interface Window {
    hljs?: HighlightEngine
  }
}

type CustomEmoji = {
  name: string
  url: string
}

type Message = {
  id: string
  conversation_id: string
  user: string
  display_name?: string
  color?: string
  time: string
  timestamp: number
  created_at: number
  content: string
  format?: 'markdown' | 'plain'
  type: string
  recalled?: boolean
  edited?: boolean
  edited_at?: number
  reply_to?: string | null
  reactions?: Record<string, Reaction>
  attachments?: Attachment[]
  forwarded_from?: { message_id?: string; conversation_id?: string; user?: string } | null
  bookmarked?: boolean
  pinned?: boolean
}

type Conversation = {
  id: string
  kind: 'public' | 'direct'
  title: string
  participants: User[]
  unread: number
  last_message?: Message | null
  pinned?: boolean
  muted?: boolean
  archived?: boolean
  hidden?: boolean
  blocked?: boolean
}

type Notification = {
  id: string
  kind: string
  actor?: string
  message_id?: string
  conversation_id?: string
  created_at: number
  read?: boolean
}

type SearchResult = { message: Message; snippet: string }

let csrfToken = ''
let floatingWindowZIndex = 100
let highlightLoading: Promise<HighlightEngine | null> | null = null

const textPreviewExtensions = new Set([
  'txt', 'text', 'md', 'markdown', 'rst', 'log', 'csv', 'tsv', 'json', 'jsonl', 'yaml', 'yml', 'xml', 'html', 'htm',
  'css', 'scss', 'less', 'js', 'mjs', 'cjs', 'ts', 'tsx', 'jsx', 'vue', 'svelte', 'py', 'pyw', 'rb', 'php', 'java',
  'c', 'cc', 'cpp', 'cxx', 'h', 'hh', 'hpp', 'cs', 'go', 'rs', 'swift', 'kt', 'kts', 'scala', 'sh', 'bash', 'zsh',
  'fish', 'bat', 'cmd', 'ps1', 'psm1', 'ini', 'cfg', 'conf', 'toml', 'env', 'sql', 'r', 'pl', 'pm', 'lua', 'make',
  'gradle', 'properties', 'gitignore', 'dockerfile', 'in', 'out',
])

const languageAliases: Record<string, string> = {
  html: 'xml', htm: 'xml', vue: 'xml', svelte: 'xml', xml: 'xml',
  md: 'markdown', markdown: 'markdown', yml: 'yaml', json: 'json', jsonl: 'json',
  js: 'javascript', mjs: 'javascript', cjs: 'javascript', jsx: 'javascript',
  ts: 'typescript', tsx: 'typescript',
  py: 'python', pyw: 'python', rb: 'ruby', rs: 'rust', cs: 'csharp',
  c: 'c', cc: 'cpp', cpp: 'cpp', cxx: 'cpp', h: 'cpp', hh: 'cpp', hpp: 'cpp',
  sh: 'bash', bash: 'bash', zsh: 'bash', fish: 'bash', bat: 'dos', cmd: 'dos', ps1: 'powershell', psm1: 'powershell',
  kt: 'kotlin', kts: 'kotlin', pl: 'perl', pm: 'perl', lua: 'lua', sql: 'sql',
  css: 'css', scss: 'scss', less: 'less', java: 'java', go: 'go', swift: 'swift', php: 'php',
  yaml: 'yaml', toml: 'ini', ini: 'ini', cfg: 'ini', conf: 'ini', properties: 'properties',
  dockerfile: 'dockerfile', gradle: 'gradle', r: 'r',
}

function nextFloatingWindowZIndex() {
  floatingWindowZIndex += 1
  return floatingWindowZIndex
}

function fileExtension(filename: string) {
  const base = filename.split(/[\\/]/).pop()?.toLowerCase() || ''
  if (base === 'dockerfile' || base === '.gitignore') return base.slice(0, 1) === '.' ? base.slice(1) : base
  return base.split('.').pop() || ''
}

function isTextPreviewFile(filename: string, mime = '') {
  return mime.startsWith('text/') || mime.includes('json') || mime.includes('javascript') || mime.includes('xml') || textPreviewExtensions.has(fileExtension(filename))
}

function languageForFilename(filename: string) {
  return languageAliases[fileExtension(filename)] || 'plaintext'
}

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character] || character)
}

function loadHighlightEngine() {
  if (window.hljs) return Promise.resolve(window.hljs)
  if (highlightLoading) return highlightLoading
  highlightLoading = new Promise((resolve) => {
    const existing = document.querySelector('script[data-hzx-highlight]')
    if (existing) {
      existing.addEventListener('load', () => resolve(window.hljs || null), { once: true })
      existing.addEventListener('error', () => resolve(null), { once: true })
      return
    }
    const script = document.createElement('script')
    script.src = '/static/js/highlight.js/highlight.min.js'
    script.dataset.hzxHighlight = 'true'
    script.onload = () => resolve(window.hljs || null)
    script.onerror = () => resolve(null)
    document.head.appendChild(script)
  })
  return highlightLoading
}

async function highlightSource(content: string, filename: string) {
  const engine = await loadHighlightEngine()
  if (!engine) return escapeHtml(content)
  const language = languageForFilename(filename)
  try {
    if (language !== 'plaintext' && engine.getLanguage(language)) {
      return engine.highlight(content, { language, ignoreIllegals: true }).value
    }
    return engine.highlightAuto(content).value || escapeHtml(content)
  } catch {
    return escapeHtml(content)
  }
}

async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  const method = (options.method || 'GET').toUpperCase()
  const isForm = options.body instanceof FormData
  if (!isForm && options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (csrfToken && method !== 'GET' && method !== 'HEAD') {
    headers.set('X-CSRF-Token', csrfToken)
  }
  const response = await fetch(path, { ...options, headers, credentials: 'include' })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const error = new Error(payload.error || `请求失败 (${response.status})`) as Error & { status?: number }
    error.status = response.status
    throw error
  }
  return payload as T
}

function jsonRequest(data: unknown): RequestInit {
  return { method: 'POST', body: JSON.stringify(data) }
}

function LoginView({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [theme, setTheme] = useState(localStorage.getItem('hzx-theme') === 'light' ? 'light' : 'graphite')

  useEffect(() => {
    localStorage.setItem('hzx-theme', theme)
  }, [theme])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = await api<{ user: User; csrf_token: string }>('/api/v2/auth/login', jsonRequest({ username, password }))
      csrfToken = result.csrf_token
      onLogin(result.user)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '登录失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-page" data-theme={theme}>
      <button className="theme-toggle" type="button" onClick={() => setTheme(theme === 'light' ? 'graphite' : 'light')}><span>{theme === 'light' ? '亮' : '暗'}</span><span>主题</span></button>
      <section className="auth-panel">
        <div className="auth-brand"><span className="brand-dash" /><span className="brand-cycle"><i>SECURE</i><i>ENCRYPT</i></span><span className="brand-dash" /></div>
        <div className="auth-title"><h1>HZX-CR</h1><span className="title-divider" /><p>hzx chat · 登录</p></div>
        <form onSubmit={submit} className="auth-form">
          <label className="auth-field"><input value={username} onChange={(event) => setUsername(event.target.value)} placeholder=" " autoComplete="username" required /><span>USERNAME</span></label>
          <label className="auth-field"><input value={password} onChange={(event) => setPassword(event.target.value)} placeholder=" " type="password" autoComplete="current-password" required /><span>PASSWORD</span></label>
          {error && <div className="form-error">{error}</div>}
          <button className="auth-submit" disabled={busy}>{busy ? '// 验证 //' : '// 进入 //'}</button>
        </form>
        <div className="auth-footer"><span>modern im</span><span className="footer-dot" /><span>private chat</span><a href="/register">没有账号？立即注册</a></div>
      </section>
    </main>
  )
}

function FloatingWindow({ title, eyebrow, className = '', modal = false, actions, onClose, children }: { title: string; eyebrow?: string; className?: string; modal?: boolean; actions?: ReactNode; onClose: () => void; children: ReactNode }) {
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null)
  const [zIndex, setZIndex] = useState(() => nextFloatingWindowZIndex())
  const drag = useRef<{ offsetX: number; offsetY: number; width: number; height: number } | null>(null)

  useEffect(() => {
    const move = (event: PointerEvent) => {
      const current = drag.current
      if (!current) return
      const left = Math.min(Math.max(8, event.clientX - current.offsetX), Math.max(8, window.innerWidth - current.width - 8))
      const top = Math.min(Math.max(8, event.clientY - current.offsetY), Math.max(8, window.innerHeight - current.height - 8))
      setPosition({ left, top })
    }
    const stop = () => { drag.current = null }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
    }
  }, [])

  function startDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.target instanceof Element && event.target.closest('button')) return
    const panel = event.currentTarget.closest('.floating-window')
    if (!(panel instanceof HTMLElement)) return
    const rect = panel.getBoundingClientRect()
    event.preventDefault()
    setZIndex(nextFloatingWindowZIndex())
    drag.current = { offsetX: event.clientX - rect.left, offsetY: event.clientY - rect.top, width: rect.width, height: rect.height }
    setPosition({ left: rect.left, top: rect.top })
  }

  const panel = (
    <section className={`floating-window ${className}`} style={{ ...(position ? { left: position.left, top: position.top, right: 'auto', bottom: 'auto', transform: 'none' } : {}), zIndex }} onPointerDown={() => setZIndex(nextFloatingWindowZIndex())} onClick={(event) => { if (modal) event.stopPropagation() }}>
      <div className="floating-window-titlebar" onPointerDown={startDrag}>
        <div className="floating-window-heading">{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2>{title}</h2></div>
        <div className="floating-window-controls">
          {actions && <div className="floating-window-actions">{actions}</div>}
          <button className="floating-window-close" type="button" title="关闭" aria-label="关闭窗口" onPointerDown={(event) => event.stopPropagation()} onClick={onClose}><X size={16} /></button>
        </div>
      </div>
      {children}
    </section>
  )

  return modal ? <div className="modal-backdrop" onClick={onClose}>{panel}</div> : panel
}

function Avatar({ user, size = 'normal' }: { user?: Partial<User> | null; size?: 'small' | 'normal' | 'large' }) {
  const label = user?.display_name || user?.username || '?'
  return user?.avatar_url ? (
    <img className={`avatar ${size}`} src={user.avatar_url} alt={label} />
  ) : (
    <span className={`avatar ${size}`} style={{ borderColor: user?.color || '#6f8cff' }}>{initials(label)}</span>
  )
}

function MarkdownBody({ message }: { message: Message }) {
  if (message.type === 'emoji') {
    const filename = markerFilename(message.content, '::emoji::')
    if (filename) {
      return <img className="emoji-message" src={`/chat/emoji/static/${encodeURIComponent(message.user)}/${encodeURIComponent(filename)}`} alt={filename} />
    }
  }
  if (message.format === 'plain') return <pre className="plain-content">{message.content}</pre>
  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]} rehypePlugins={[rehypeSanitize]}>
        {message.content}
      </ReactMarkdown>
    </div>
  )
}

function AttachmentView({ message, onOpenPreview }: { message: Message; onOpenPreview: (file: PreviewTarget) => void }) {
  const attachments = message.attachments || []
  if (!attachments.length) {
    const image = markerFilename(message.content, '::img::')
    const audio = markerFilename(message.content, '::wav::')
    const file = markerFilename(message.content, '::file::')
    if (image) {
      const target = { name: image, url: `/static/uploads/${encodeURIComponent(image)}`, mime: 'image/*', kind: 'image' as const }
      return <button className="attachment-image-button" type="button" title={`预览 ${image}`} onClick={() => onOpenPreview(target)}><img className="attachment-image" src={target.url} alt={image} /></button>
    }
    if (audio) return <audio controls src={`/static/uploads/${encodeURIComponent(audio)}`} />
    if (file) {
      const target = { name: file, url: `/static/uploads/${encodeURIComponent(file)}`, mime: 'application/octet-stream', kind: 'text' as const }
      if (isTextPreviewFile(file)) return <button className="file-attachment" type="button" title={`预览 ${file}`} onClick={() => onOpenPreview(target)}><FileUp size={16} />[文件] {file}</button>
      return <a className="file-attachment" href={target.url} download><FileUp size={16} />[文件] {file}</a>
    }
    return null
  }
  return (
    <div className="attachment-list">
      {attachments.map((attachment) => {
        const mime = attachment.mime || ''
        const target = { id: attachment.id, name: attachment.name, mime, url: attachment.url, kind: mime.startsWith('image/') ? 'image' as const : 'text' as const }
        if (mime.startsWith('image/')) return <button className="attachment-image-button" type="button" title={`预览 ${attachment.name}`} onClick={() => onOpenPreview(target)} key={attachment.id || attachment.url}><img className="attachment-image" src={attachment.url} alt={attachment.name} /></button>
        if (mime.startsWith('audio/')) return <audio controls src={attachment.url} key={attachment.id || attachment.url} />
        if (mime.startsWith('video/')) return <video controls className="attachment-video" src={attachment.url} key={attachment.id || attachment.url} />
        if (isTextPreviewFile(attachment.name, mime)) return <button className="file-attachment" type="button" title={`预览 ${attachment.name}`} onClick={() => onOpenPreview(target)} key={attachment.id || attachment.url}><FileUp size={16} />[文件] {attachment.name}</button>
        return <a className="file-attachment" href={attachment.url} download={attachment.name} key={attachment.id || attachment.url}><FileUp size={16} />[文件] {attachment.name}</a>
      })}
    </div>
  )
}

function FilePreviewWindow({ file, onClose }: { file: PreviewTarget; onClose: () => void }) {
  const [content, setContent] = useState('')
  const [highlighted, setHighlighted] = useState('')
  const [encoding, setEncoding] = useState('')
  const [loading, setLoading] = useState(file.kind === 'text')
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let cancelled = false
    setContent('')
    setHighlighted('')
    setEncoding('')
    setError('')
    setCopied(false)
    if (file.kind === 'image') {
      setLoading(false)
      return () => { cancelled = true }
    }
    setLoading(true)
    const path = file.id
      ? `/api/v2/files/${encodeURIComponent(file.id)}/preview`
      : `/api/v2/files/legacy-preview?filename=${encodeURIComponent(file.name)}`
    const previewRequest = api<{ kind: string; content?: string; encoding?: string }>(path).catch(async (reason) => {
      const status = reason instanceof Error ? (reason as Error & { status?: number }).status : undefined
      if (file.id || status !== 404) throw reason
      const response = await fetch(file.url, { credentials: 'include' })
      if (!response.ok) throw reason
      return { kind: 'text', content: await response.text(), encoding: 'utf-8' }
    })
    previewRequest
      .then(async (result) => {
        if (cancelled) return
        if (result.kind !== 'text') throw new Error('该文件不是可预览的文本文件')
        const nextContent = result.content || ''
        const nextHighlighted = await highlightSource(nextContent, file.name)
        if (cancelled) return
        setContent(nextContent)
        setHighlighted(nextHighlighted)
        setEncoding(result.encoding || '')
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '文件预览失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [file])

  async function copyContent() {
    if (!content) return
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(content)
      } else {
        const textarea = document.createElement('textarea')
        textarea.value = content
        textarea.style.position = 'fixed'
        textarea.style.opacity = '0'
        document.body.appendChild(textarea)
        textarea.select()
        document.execCommand('copy')
        textarea.remove()
      }
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1400)
    } catch {
      setError('复制失败，请手动选择文本')
    }
  }

  function downloadFile() {
    const anchor = document.createElement('a')
    anchor.href = file.url
    anchor.download = file.name
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  }

  const actions = (
    <>
      {file.kind === 'text' && <button className="floating-window-action" type="button" disabled={loading || !content} title="复制文本" onPointerDown={(event) => event.stopPropagation()} onClick={() => void copyContent()}><Copy size={14} />{copied ? '已复制' : '复制'}</button>}
      <button className="floating-window-action" type="button" title="下载文件" onPointerDown={(event) => event.stopPropagation()} onClick={downloadFile}><Download size={14} />下载</button>
    </>
  )

  return (
    <FloatingWindow title={file.name} eyebrow={file.kind === 'text' ? (languageForFilename(file.name) === 'plaintext' ? 'TEXT' : languageForFilename(file.name).toUpperCase()) : 'IMAGE'} className="file-preview-window" actions={actions} onClose={onClose}>
      <div className="file-preview-body">
        {file.kind === 'image' && <img className="file-preview-image" src={file.url} alt={file.name} />}
        {file.kind === 'text' && loading && <div className="file-preview-status">正在读取文件…</div>}
        {file.kind === 'text' && !loading && error && <div className="file-preview-status error">{error}</div>}
        {file.kind === 'text' && !loading && !error && <><div className="file-preview-meta">{encoding && `编码 · ${encoding}`}</div><pre className="file-preview-code"><code dangerouslySetInnerHTML={{ __html: highlighted || escapeHtml(content) }} /></pre></>}
      </div>
    </FloatingWindow>
  )
}

function MessageRow({
  message,
  replyMessage,
  currentUser,
  onReply,
  onEdit,
  onRecall,
  onHide,
  onReact,
  onBookmark,
  onPin,
  onMore,
  onJumpToMessage,
  onOpenPreview,
}: {
  message: Message
  replyMessage?: Message
  currentUser: User
  onReply: (message: Message) => void
  onEdit: (message: Message) => void
  onRecall: (message: Message) => void
  onHide: (message: Message) => void
  onReact: (message: Message, emoji: string) => void
  onBookmark: (message: Message) => void
  onPin: (message: Message) => void
  onMore: (message: Message) => void
  onJumpToMessage: (messageId: string) => void
  onOpenPreview: (file: PreviewTarget) => void
}) {
  const own = message.user === currentUser.username
  const canRecall = own || currentUser.role === 'owner' || currentUser.role === 'admin'
  const replyAuthor = replyMessage?.display_name || replyMessage?.user || ''
  const replyContent = replyMessage?.content || (replyMessage ? `[${replyMessage.type}]` : `消息 #${message.reply_to?.slice(0, 6) || ''}`)
  return (
    <article className={`message-row ${own ? 'own' : ''}`} id={`message-${message.id}`}>
      <Avatar user={{ username: message.user, display_name: message.display_name || message.user, color: message.color }} size="small" />
      <div className="message-stack">
        <div className="message-meta"><strong>{message.display_name || message.user}</strong><span>{formatTime(message.created_at || message.timestamp)}</span>{message.edited && <em>已编辑</em>}{message.pinned && <Pin size={11} />}{message.bookmarked && <Bookmark size={11} />}</div>
        {message.reply_to && <button className="reply-chip" type="button" title="跳转到被回复的消息" onClick={() => onJumpToMessage(message.reply_to || '')}><MessageCircle size={13} /><span>{replyAuthor ? `回复 ${replyAuthor}: ${replyContent}` : replyContent}</span></button>}
        <div className="message-bubble">
          <AttachmentView message={message} onOpenPreview={onOpenPreview} />
          {message.content && !['image', 'audio', 'voice', 'file', 'emoji'].includes(message.type) && <MarkdownBody message={message} />}
        </div>
        <div className="message-actions">
          <button title="回复" onClick={() => onReply(message)}><MessageCircle size={14} /></button>
          <button title="添加赞" onClick={() => onReact(message, '👍')}>👍</button>
          <button className={message.bookmarked ? 'selected' : ''} title="收藏" onClick={() => onBookmark(message)}><Bookmark size={14} /></button>
          <button className={message.pinned ? 'selected' : ''} title="置顶" onClick={() => onPin(message)}><Pin size={14} /></button>
          {own && <button title="编辑" onClick={() => onEdit(message)}><Pencil size={14} /></button>}
          {canRecall && <button title="撤回" onClick={() => onRecall(message)}><Trash2 size={14} /></button>}
          <button title="仅自己隐藏" onClick={() => onHide(message)}><Archive size={14} /></button>
          <button title="更多操作" onClick={() => onMore(message)}><MoreHorizontal size={14} /></button>
        </div>
        {Object.entries(message.reactions || {}).length > 0 && (
          <div className="reactions">
            {Object.entries(message.reactions || {}).map(([emoji, reaction]) => <button className={reaction.reacted ? 'reacted' : ''} key={emoji} onClick={() => onReact(message, emoji)}>{emoji} {reaction.count}</button>)}
          </div>
        )}
      </div>
    </article>
  )
}

function PinnedBar({ messages, onSelect, onMore }: { messages: Message[]; onSelect: (messageId: string) => void; onMore: () => void }) {
  return (
    <div className="pinned-bar">
      <div className="pinned-label"><Pin size={14} /><span>置顶消息</span><b>{messages.length}</b></div>
      <div className="pinned-items">
        {messages.slice(0, 3).map((message) => <button className="pinned-item" type="button" key={message.id} title="跳转到置顶消息" onClick={() => onSelect(message.id)}><strong>{message.display_name || message.user}</strong><span>{message.content || `[${message.type}]`}</span></button>)}
      </div>
      <button className="pinned-more" type="button" title="查看全部置顶消息" onClick={onMore}><MoreHorizontal size={16} /></button>
    </div>
  )
}

function ChatShell({ currentUser, onLogout, onUserUpdated }: { currentUser: User; onLogout: () => void; onUserUpdated: (user: User) => void }) {
  const [users, setUsers] = useState<User[]>([])
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState(PUBLIC_CONVERSATION)
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [replyTo, setReplyTo] = useState<Message | null>(null)
  const [editing, setEditing] = useState<Message | null>(null)
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [typingUsers, setTypingUsers] = useState<string[]>([])
  const [notificationCount, setNotificationCount] = useState(0)
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [showNotifications, setShowNotifications] = useState(false)
  const [showConversationMenu, setShowConversationMenu] = useState(false)
  const [showPins, setShowPins] = useState(false)
  const [pins, setPins] = useState<Message[]>([])
  const [showSearch, setShowSearch] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [searchBusy, setSearchBusy] = useState(false)
  const [showProfile, setShowProfile] = useState(false)
  const [profileDraft, setProfileDraft] = useState({ display_name: currentUser.display_name, status: currentUser.status || '', bio: currentUser.bio || '' })
  const [profileBusy, setProfileBusy] = useState(false)
  const [actionMessage, setActionMessage] = useState<Message | null>(null)
  const [forwardTargets, setForwardTargets] = useState<string[]>([PUBLIC_CONVERSATION])
  const [reportReason, setReportReason] = useState('')
  const [showEmojiPicker, setShowEmojiPicker] = useState(false)
  const [customEmojis, setCustomEmojis] = useState<CustomEmoji[]>([])
  const [previewFile, setPreviewFile] = useState<PreviewTarget | null>(null)
  const [showToken, setShowToken] = useState(false)
  const [tokenValue, setTokenValue] = useState('')
  const [tokenBusy, setTokenBusy] = useState(false)
  const [theme, setTheme] = useState(localStorage.getItem('hzx-theme') || 'graphite')
  const [density, setDensity] = useState(localStorage.getItem('hzx-density') || 'comfortable')
  const [mobileSidebar, setMobileSidebar] = useState(false)
  const lastTyping = useRef(0)
  const [beforeCursor, setBeforeCursor] = useState<string | null>(null)
  const activeConversation = conversations.find((conversation) => conversation.id === activeId) || conversations[0]
  const directTarget = users.find((user) => user.username === activeConversation?.title) || activeConversation?.participants?.find((participant) => participant.username !== currentUser.username)
  const themeNames = ['graphite', 'light', 'ocean', 'forest', 'rose', 'oled']
  const themeLabels: Record<string, string> = { graphite: '石墨', light: '明亮', ocean: '海洋', forest: '森林', rose: '玫瑰', oled: '纯黑' }

  const filteredUsers = useMemo(() => users.filter((user) => `${user.display_name} ${user.username}`.toLowerCase().includes(search.toLowerCase())), [users, search])

  async function loadConversations() {
    const result = await api<{ conversations: Conversation[] }>('/api/v2/conversations')
    setConversations(result.conversations)
  }

  async function loadMessages(conversationId = activeId) {
    const result = await api<{ messages: Message[]; cursors?: { before?: string | null } }>(`/api/v2/conversations/${encodeURIComponent(conversationId)}/messages?limit=50`)
    setMessages(result.messages)
    setBeforeCursor(result.cursors?.before || null)
    const last = result.messages[result.messages.length - 1]
    if (last) void api(`/api/v2/conversations/${encodeURIComponent(conversationId)}/read`, jsonRequest({ message_id: last.id }))
  }

  async function loadEmojis() {
    try {
      const result = await api<{ emojis: CustomEmoji[] }>('/api/v2/emojis')
      setCustomEmojis(result.emojis || [])
    } catch {
      setCustomEmojis([])
    }
  }

  async function loadOlderMessages() {
    if (!beforeCursor || !activeId) return
    const result = await api<{ messages: Message[]; cursors?: { before?: string | null } }>(`/api/v2/conversations/${encodeURIComponent(activeId)}/messages?limit=50&before=${encodeURIComponent(beforeCursor)}`)
    setMessages((value) => [...result.messages, ...value])
    setBeforeCursor(result.cursors?.before || null)
  }

  useEffect(() => {
    Promise.all([api<{ users: User[] }>('/api/v2/users'), loadConversations(), loadEmojis()])
      .then(([userResult]) => setUsers(userResult.users))
      .catch(() => onLogout())
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!activeId) return
    setBeforeCursor(null)
    setPins([])
    loadMessages(activeId).catch(() => undefined)
    loadPinnedMessages(activeId).catch(() => setPins([]))
  }, [activeId])

  useEffect(() => {
    const source = new EventSource('/api/v2/events')
    const reload = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data)
        const conversationId = data.message?.conversation_id || data.conversation_id
        if (conversationId === activeId || data.message?.conversation_id === activeId) {
          void loadMessages(activeId)
          void loadPinnedMessages(activeId)
        } else if (event.type === 'message.pinned') {
          void loadPinnedMessages(activeId)
        }
        void loadConversations()
      } catch {
        // An invalid event should not break the live connection.
      }
    }
    source.addEventListener('message.created', reload)
    source.addEventListener('message.updated', reload)
    source.addEventListener('message.deleted', reload)
    source.addEventListener('reaction.updated', reload)
    source.addEventListener('message.pinned', reload)
    source.addEventListener('conversation.updated', reload)
    source.addEventListener('notification', (event) => {
      setNotificationCount((value) => value + 1)
      try { setNotifications((value) => [{ ...JSON.parse((event as MessageEvent).data), read: false }, ...value]) } catch { /* ignore */ }
    })
    source.addEventListener('typing', (event) => {
      try {
        const data = JSON.parse((event as MessageEvent).data)
        if (data.username === currentUser.username) return
        setTypingUsers((value) => data.active ? Array.from(new Set([...value, data.username])) : value.filter((name) => name !== data.username))
        if (data.active) window.setTimeout(() => setTypingUsers((value) => value.filter((name) => name !== data.username)), 3500)
      } catch { /* ignore */ }
    })
    return () => source.close()
  }, [activeId, currentUser.username])

  useEffect(() => {
    localStorage.setItem('hzx-theme', theme)
    localStorage.setItem('hzx-density', density)
  }, [theme, density])

  useEffect(() => {
    document.body.dataset.appTheme = theme
    return () => { delete document.body.dataset.appTheme }
  }, [theme])

  async function sendMessage() {
    const content = draft.trim()
    if (!content || sending) return
    setSending(true)
    try {
      if (editing) {
        await api(`/api/v2/messages/${editing.id}`, { method: 'PATCH', body: JSON.stringify({ content, format: 'markdown' }) })
        setEditing(null)
      } else {
        await api(`/api/v2/conversations/${encodeURIComponent(activeId)}/messages`, jsonRequest({ content, format: 'markdown', reply_to: replyTo?.id || null }))
        setReplyTo(null)
      }
      setDraft('')
      await loadMessages(activeId)
      await loadConversations()
    } finally {
      setSending(false)
    }
  }

  async function sendCustomEmoji(emoji: CustomEmoji) {
    if (sending || activeConversation?.blocked) return
    setSending(true)
    try {
      await api(`/api/v2/conversations/${encodeURIComponent(activeId)}/messages`, jsonRequest({ content: `::emoji::${emoji.name}`, type: 'emoji', format: 'plain' }))
      setShowEmojiPicker(false)
      await loadMessages(activeId)
      await loadConversations()
    } finally {
      setSending(false)
    }
  }

  async function uploadEmoji(file: File) {
    if (!file.type.startsWith('image/')) {
      window.alert('表情包必须是图片文件')
      return
    }
    const form = new FormData()
    form.append('file', file)
    try {
      const result = await api<{ emoji: CustomEmoji }>('/api/v2/emojis', { method: 'POST', body: form })
      setCustomEmojis((value) => [...value.filter((item) => item.name !== result.emoji.name), result.emoji].sort((left, right) => left.name.localeCompare(right.name)))
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : '表情包上传失败')
    }
  }

  async function deleteEmoji(emoji: CustomEmoji) {
    if (!window.confirm(`确定删除表情包“${emoji.name}”吗？`)) return
    try {
      await api(`/api/v2/emojis/${encodeURIComponent(emoji.name)}`, { method: 'DELETE' })
      setCustomEmojis((value) => value.filter((item) => item.name !== emoji.name))
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : '表情包删除失败')
    }
  }

  function handleComposerKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter' || event.shiftKey) return
    const mention = /(?:^|\s)@([^\s]*)$/.exec(draft)
    if (mention && filteredUsers.length) {
      event.preventDefault()
      const start = mention.index + mention[0].lastIndexOf('@')
      setDraft(`${draft.slice(0, start)}@${filteredUsers[0].username} `)
      return
    }
    event.preventDefault()
    void sendMessage()
  }

  function handleDraftChange(value: string) {
    setDraft(value)
    const now = Date.now()
    if (now - lastTyping.current > 900) {
      lastTyping.current = now
      void api(`/api/v2/conversations/${encodeURIComponent(activeId)}/typing`, jsonRequest({ active: true })).catch(() => undefined)
    }
  }

  async function uploadFile(file: File) {
    if (file.size > 8 * 1024 * 1024) {
      const initialized = await api<{ upload_id: string; chunk_size: number }>('/api/v2/uploads/init', jsonRequest({ filename: file.name, size: file.size, mime: file.type }))
      for (let offset = 0, index = 0; offset < file.size; offset += initialized.chunk_size, index += 1) {
        const chunk = file.slice(offset, Math.min(file.size, offset + initialized.chunk_size))
        await api(`/api/v2/uploads/${initialized.upload_id}/chunks/${index}`, { method: 'PUT', headers: { 'Content-Type': 'application/octet-stream', 'X-Chunk-Offset': String(offset) }, body: chunk })
      }
      const completed = await api<{ attachment: Attachment }>(`/api/v2/uploads/${initialized.upload_id}/complete`, jsonRequest({}))
      await api(`/api/v2/conversations/${encodeURIComponent(activeId)}/messages`, jsonRequest({ attachments: [completed.attachment], content: '', type: file.type.startsWith('image/') ? 'image' : file.type.startsWith('audio/') ? 'audio' : file.type.startsWith('video/') ? 'video' : 'file', format: 'plain' }))
      await loadMessages(activeId)
      await loadConversations()
      return
    }
    const form = new FormData()
    form.append('file', file)
    const uploaded = await api<{ attachment: Attachment }>('/api/v2/uploads', { method: 'POST', body: form })
    await api(`/api/v2/conversations/${encodeURIComponent(activeId)}/messages`, jsonRequest({ attachments: [uploaded.attachment], content: '', type: file.type.startsWith('image/') ? 'image' : file.type.startsWith('audio/') ? 'audio' : file.type.startsWith('video/') ? 'video' : 'file', format: 'plain' }))
    await loadMessages(activeId)
    await loadConversations()
  }

  async function addReaction(message: Message, emoji: string) {
    const reacted = message.reactions?.[emoji]?.reacted
    await api(`/api/v2/messages/${message.id}/reactions`, jsonRequest({ emoji, action: reacted ? 'remove' : 'add' }))
    await loadMessages(activeId)
  }

  async function recall(message: Message) {
    if (!window.confirm('撤回后消息和附件将被直接删除，继续吗？')) return
    await api(`/api/v2/messages/${message.id}/recall`, jsonRequest({}))
    await loadMessages(activeId)
  }

  async function hideMessage(message: Message) {
    await api(`/api/v2/messages/${message.id}`, { method: 'DELETE' })
    setMessages((value) => value.filter((item) => item.id !== message.id))
  }

  async function bookmarkMessage(message: Message) {
    await api(`/api/v2/messages/${message.id}/bookmark`, message.bookmarked ? { method: 'DELETE' } : jsonRequest({}))
    await loadMessages(activeId)
  }

  async function pinMessage(message: Message) {
    await api(`/api/v2/messages/${message.id}/pin`, message.pinned ? { method: 'DELETE' } : jsonRequest({}))
    await loadMessages(activeId)
    await loadPinnedMessages(activeId)
  }

  async function loadPinnedMessages(conversationId = activeId) {
    const result = await api<{ pins: Message[] }>(`/api/v2/conversations/${encodeURIComponent(conversationId)}/pins`)
    setPins(result.pins || [])
  }

  async function loadPins() {
    await loadPinnedMessages(activeId)
    setShowPins(true)
  }

  function jumpToMessage(messageId: string) {
    if (!messageId) return
    const target = document.getElementById(`message-${messageId}`)
    if (!target) return
    target.scrollIntoView({ behavior: 'smooth', block: 'center' })
    target.classList.remove('message-highlight')
    window.requestAnimationFrame(() => target.classList.add('message-highlight'))
    window.setTimeout(() => target.classList.remove('message-highlight'), 1800)
  }

  async function updateConversationPreference(key: 'pinned' | 'muted' | 'archived' | 'hidden') {
    if (!activeConversation) return
    await api(`/api/v2/conversations/${encodeURIComponent(activeId)}/preferences`, jsonRequest({ [key]: !activeConversation[key] }))
    await loadConversations()
    setShowConversationMenu(false)
  }

  async function toggleBlock() {
    if (!directTarget) return
    await api(`/api/v2/users/${encodeURIComponent(directTarget.username)}/block`, directTarget.blocked ? { method: 'DELETE' } : jsonRequest({}))
    const userResult = await api<{ users: User[] }>('/api/v2/users')
    setUsers(userResult.users)
    await loadConversations()
  }

  async function runSearch(event?: FormEvent) {
    event?.preventDefault()
    if (!searchQuery.trim()) return
    setSearchBusy(true)
    try {
      const params = new URLSearchParams({ q: searchQuery.trim(), limit: '50' })
      if (activeId) params.set('conversation_id', activeId)
      const result = await api<{ results: SearchResult[] }>(`/api/v2/search?${params.toString()}`)
      setSearchResults(result.results)
    } finally {
      setSearchBusy(false)
    }
  }

  function openProfile() {
    setProfileDraft({ display_name: currentUser.display_name, status: currentUser.status || '', bio: currentUser.bio || '' })
    setShowProfile(true)
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault()
    setProfileBusy(true)
    try {
      const result = await api<{ user: User }>('/api/v2/profile', { method: 'PATCH', body: JSON.stringify(profileDraft) })
      onUserUpdated(result.user)
      setShowProfile(false)
    } finally {
      setProfileBusy(false)
    }
  }

  async function reportMessage() {
    if (!actionMessage || !reportReason.trim()) return
    await api(`/api/v2/messages/${actionMessage.id}/reports`, jsonRequest({ reason: reportReason.trim() }))
    setReportReason('')
    setActionMessage(null)
  }

  async function forwardMessage() {
    if (!actionMessage || !forwardTargets.length) return
    await api(`/api/v2/messages/${actionMessage.id}/forward`, jsonRequest({ conversation_ids: forwardTargets }))
    setActionMessage(null)
  }

  async function openNotifications() {
    setShowNotifications((value) => !value)
    if (!notifications.length) {
      const result = await api<{ notifications: Notification[] }>('/api/v2/notifications')
      setNotifications(result.notifications)
    }
    setNotificationCount(0)
  }

  async function createBotToken(replace = false) {
    setTokenBusy(true)
    try {
      const result = await api<{ token: string }>('/api/v2/bot/token', jsonRequest({ replace }))
      setTokenValue(result.token)
    } catch (reason) {
      if (reason instanceof Error && reason.message.includes('一个有效 token')) {
        if (window.confirm('已有 token，是否立即替换？旧 token 会失效。')) void createBotToken(true)
      }
    } finally {
      setTokenBusy(false)
    }
  }

  async function revokeBotToken() {
    await api('/api/v2/bot/token', { method: 'DELETE' })
    setTokenValue('')
  }

  if (loading) return <main className="loading-page"><Zap size={20} />正在加载聊天室…</main>

  return (
    <div className="app-shell" data-theme={theme} data-density={density}>
      <aside className={`sidebar ${mobileSidebar ? 'mobile-open' : ''}`}>
        <div className="brand-row"><div><span className="brand-mark"><Zap size={14} /></span><strong>hzx chat</strong><small>modern</small></div><button className="icon-button mobile-close" title="关闭侧栏" onClick={() => setMobileSidebar(false)}><X size={17} /></button></div>
        <button className="user-card" title="编辑个人资料" onClick={openProfile}><Avatar user={currentUser} size="normal" /><div><strong>{currentUser.display_name}</strong><span>@{currentUser.username}</span></div><span className="presence-dot" /></button>
        <div className="sidebar-search"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="筛选用户" /></div>
        <div className="section-label">会话 <span>{conversations.length}</span></div>
        <nav className="conversation-list">
          {conversations.filter((item) => item.id === PUBLIC_CONVERSATION).map((conversation) => <ConversationRow key={conversation.id} conversation={conversation} active={activeId === conversation.id} onClick={() => { setActiveId(conversation.id); setMobileSidebar(false) }} publicChat />)}
          {filteredUsers.map((user) => {
            const conversation = conversations.find((item) => item.title === user.username && item.kind === 'direct') || { id: '', kind: 'direct' as const, title: user.username, participants: [user], unread: 0 }
            const id = conversation.id || directIdFallback(currentUser.username, user.username)
            return <ConversationRow key={user.username} conversation={{ ...conversation, id }} active={activeId === id} onClick={() => { setActiveId(id); setMobileSidebar(false) }} user={user} />
          })}
        </nav>
        <div className="sidebar-footer">
          <button className="footer-action" onClick={openProfile}><Settings size={16} />个人资料</button>
          <button className="footer-action" onClick={() => setShowToken(true)}><Zap size={16} />机器人 Token</button>
          <button className="footer-action" onClick={() => setTheme(themeNames[(themeNames.indexOf(theme) + 1) % themeNames.length])}><Palette size={16} />主题 · {themeLabels[theme] || theme}</button>
          <button className="footer-action" onClick={onLogout}><LogOut size={16} />退出登录</button>
        </div>
      </aside>

      <main className="chat-panel">
        <header className="chat-header">
          <button className="icon-button mobile-menu" title="打开会话列表" onClick={() => setMobileSidebar(true)}><ChevronLeft size={19} /></button>
          <div className="conversation-heading"><div className="heading-icon">{activeConversation?.kind === 'public' ? <Hash size={18} /> : <UserRound size={18} />}</div><div><h1>{activeConversation?.title || '公共聊天室'}</h1><span>{activeConversation?.kind === 'public' ? '所有人可见' : '私聊 · 仅会话成员可见'}</span></div></div>
          <div className="header-actions"><button className="icon-button" title="切换亮暗主题" aria-label="切换亮暗主题" onClick={() => setTheme(theme === 'light' ? 'graphite' : 'light')}>{theme === 'light' ? <Moon size={17} /> : <Sun size={17} />}</button><button className="icon-button" title="搜索当前会话" onClick={() => { setShowSearch(true); setSearchResults([]) }}><Search size={18} /></button><button className="icon-button" title="查看置顶" onClick={() => void loadPins()}><Pin size={18} /></button><button className="icon-button notification-button" title="通知" onClick={() => void openNotifications()}><Bell size={18} />{notificationCount > 0 && <b>{notificationCount > 9 ? '9+' : notificationCount}</b>}</button><button className="icon-button" title="会话设置" onClick={() => setShowConversationMenu((value) => !value)}><MoreHorizontal size={18} /></button></div>
          {showNotifications && <FloatingWindow title="通知" className="notification-window" onClose={() => setShowNotifications(false)}><div className="notification-list">{notifications.length ? notifications.slice(0, 8).map((item) => <div className="notification-item" key={item.id}><Bell size={14} /><span>{item.actor || '有人'} 提到了你</span><time>{formatTime(item.created_at)}</time></div>) : <div className="empty-state">暂无通知</div>}</div></FloatingWindow>}
          {showConversationMenu && <FloatingWindow title="会话设置" className="conversation-window" onClose={() => setShowConversationMenu(false)}><div className="floating-window-menu"><button onClick={() => void updateConversationPreference('pinned')}><Pin size={14} />{activeConversation?.pinned ? '取消置顶' : '置顶会话'}</button><button onClick={() => void updateConversationPreference('muted')}><VolumeX size={14} />{activeConversation?.muted ? '取消免打扰' : '免打扰'}</button><button onClick={() => void updateConversationPreference('archived')}><Archive size={14} />{activeConversation?.archived ? '取消归档' : '归档会话'}</button>{directTarget && <button onClick={() => void toggleBlock()}><Ban size={14} />{directTarget.blocked ? '解除屏蔽' : '屏蔽对方'}</button>}</div></FloatingWindow>}
        </header>

        {pins.length > 0 && <PinnedBar messages={pins} onSelect={jumpToMessage} onMore={() => void loadPins()} />}

        <section className="message-scroller" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); const file = event.dataTransfer.files[0]; if (file) void uploadFile(file) }}>
          <div className="message-intro"><span className="intro-icon">{activeConversation?.kind === 'public' ? <Hash size={19} /> : <UserRound size={19} />}</span><h2>{activeConversation?.title || '公共聊天室'}</h2><p>{activeConversation?.kind === 'public' ? '这是所有人都能参与的公共空间。' : activeConversation?.blocked ? '该会话已屏蔽，无法继续发送。' : '这是你和对方的私密对话。'}</p></div>
          {beforeCursor && <button className="load-older" onClick={() => void loadOlderMessages()}>加载更早消息</button>}
          {messages.length === 0 && <div className="empty-state large"><MessageCircle size={22} /><span>还没有消息，发起对话吧。</span></div>}
          <div className="messages-list">{messages.map((message) => <MessageRow key={message.id} message={message} replyMessage={messages.find((item) => item.id === message.reply_to)} currentUser={currentUser} onReply={setReplyTo} onEdit={(item) => { setEditing(item); setDraft(item.content) }} onRecall={(item) => void recall(item)} onHide={(item) => void hideMessage(item)} onReact={(item, emoji) => void addReaction(item, emoji)} onBookmark={(item) => void bookmarkMessage(item)} onPin={(item) => void pinMessage(item)} onMore={(item) => { setActionMessage(item); setForwardTargets([activeId]); setReportReason('') }} onJumpToMessage={jumpToMessage} onOpenPreview={setPreviewFile} />)}</div>
          {typingUsers.length > 0 && <div className="typing-indicator"><span className="typing-dots"><i /><i /><i /></span>{typingUsers.join('、')} 正在输入…</div>}
        </section>

        <footer className="composer-area">
          {(replyTo || editing) && <div className="compose-context"><div><span>{editing ? '编辑消息' : '回复消息'}</span><strong>{(editing || replyTo)?.content.slice(0, 100)}</strong></div><button className="icon-button" title="取消" onClick={() => { setReplyTo(null); setEditing(null); setDraft('') }}><X size={16} /></button></div>}
          <div className="composer">
            <label className="icon-button attach-button" title="上传文件"><Paperclip size={18} /><input type="file" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadFile(file); event.currentTarget.value = '' }} /></label>
            <button className="icon-button" title="打开我的表情包" onClick={() => setShowEmojiPicker((value) => !value)}><Smile size={18} /></button>
            <textarea disabled={activeConversation?.blocked} value={draft} onChange={(event) => handleDraftChange(event.target.value)} onBlur={() => { void api(`/api/v2/conversations/${encodeURIComponent(activeId)}/typing`, jsonRequest({ active: false })).catch(() => undefined) }} onKeyDown={handleComposerKey} placeholder={activeConversation?.blocked ? '该会话已屏蔽' : '写点什么…  Shift + Enter 换行'} rows={1} />
            <button className="send-button" disabled={sending || !!activeConversation?.blocked || !draft.trim()} onClick={() => void sendMessage()} title="发送"><Send size={17} /><span>发送</span></button>
          </div>
          {showEmojiPicker && <FloatingWindow title="我的表情包" className="emoji-floating-window" onClose={() => setShowEmojiPicker(false)}>
            <div className="emoji-picker">
              <div className="emoji-picker-header"><span>点击图片发送</span><label className="emoji-upload-button">＋ 上传<input type="file" accept="image/*" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadEmoji(file); event.currentTarget.value = '' }} /></label></div>
              <div className="emoji-grid">
                {customEmojis.length ? customEmojis.map((emoji) => <div className="custom-emoji-item" key={emoji.name}><button className="custom-emoji-button" title={emoji.name} onClick={() => void sendCustomEmoji(emoji)}><img src={emoji.url} alt={emoji.name} /></button><button className="emoji-delete-button" type="button" title="删除表情包" onClick={(event) => { event.stopPropagation(); void deleteEmoji(emoji) }}><X size={12} /></button></div>) : <div className="emoji-empty">还没有表情包</div>}
              </div>
            </div>
          </FloatingWindow>}
          <div className="composer-hint"><span><Check size={13} /> Markdown 已启用</span><span><Paperclip size={13} />拖拽文件到消息区</span><span className="density-control"><button onClick={() => setDensity(density === 'comfortable' ? 'compact' : 'comfortable')}>{density === 'comfortable' ? '舒适间距' : '紧凑间距'}</button></span></div>
        </footer>
      </main>

      {showProfile && <FloatingWindow title="个人资料" eyebrow="PROFILE" className="profile-window" onClose={() => setShowProfile(false)}><form className="profile-form" onSubmit={(event) => void saveProfile(event)}><label>显示名称<input value={profileDraft.display_name} onChange={(event) => setProfileDraft((value) => ({ ...value, display_name: event.target.value }))} maxLength={80} required /></label><label>状态<input value={profileDraft.status} onChange={(event) => setProfileDraft((value) => ({ ...value, status: event.target.value }))} maxLength={160} placeholder="例如：忙碌中" /></label><label>个人简介<textarea value={profileDraft.bio} onChange={(event) => setProfileDraft((value) => ({ ...value, bio: event.target.value }))} maxLength={1000} rows={4} /></label><button className="primary-button full" disabled={profileBusy}>{profileBusy ? '正在保存…' : '保存资料'}<Check size={15} /></button></form></FloatingWindow>}
      {showSearch && <FloatingWindow title="搜索当前会话" eyebrow="SEARCH" className="search-window" onClose={() => setShowSearch(false)}><form className="search-form" onSubmit={(event) => void runSearch(event)}><Search size={16} /><input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="搜索消息内容或发送者" autoFocus /><button className="primary-button" disabled={searchBusy}>{searchBusy ? '搜索中…' : '搜索'}</button></form><div className="search-results">{searchResults.length ? searchResults.map((result) => <button className="search-result" type="button" key={`${result.message.conversation_id}-${result.message.id}`} onClick={() => { setActiveId(result.message.conversation_id); setShowSearch(false) }}><div><strong>{result.message.display_name || result.message.user}</strong><span>{formatTime(result.message.created_at)}</span></div><p>{result.snippet}</p></button>) : <div className="empty-state">输入关键词开始搜索</div>}</div></FloatingWindow>}
      {showPins && <FloatingWindow title="置顶消息" eyebrow="PINNED" className="pins-window" onClose={() => setShowPins(false)}><div className="pin-list">{pins.length ? pins.map((message) => <button className="pin-item" type="button" key={message.id} onClick={() => { setShowPins(false); jumpToMessage(message.id) }}><Pin size={14} /><span>{message.display_name || message.user}: {message.content || `[${message.type}]`}</span></button>) : <div className="empty-state">暂无置顶消息</div>}</div></FloatingWindow>}
      {actionMessage && <FloatingWindow title="消息操作" eyebrow="MESSAGE" className="action-window" onClose={() => setActionMessage(null)}><div className="action-preview">{actionMessage.content || `[${actionMessage.type}]`}</div><div className="action-grid"><button onClick={() => { setReplyTo(actionMessage); setActionMessage(null) }}><MessageCircle size={15} />回复</button><button onClick={() => void bookmarkMessage(actionMessage).then(() => setActionMessage(null))}><Bookmark size={15} />{actionMessage.bookmarked ? '取消收藏' : '收藏'}</button><button onClick={() => void pinMessage(actionMessage).then(() => setActionMessage(null))}><Pin size={15} />{actionMessage.pinned ? '取消置顶' : '置顶'}</button></div><div className="forward-box"><strong><Forward size={15} />转发到会话</strong><div className="target-list"><button className={forwardTargets.includes(PUBLIC_CONVERSATION) ? 'target selected' : 'target'} onClick={() => setForwardTargets((value) => value.includes(PUBLIC_CONVERSATION) ? value.filter((item) => item !== PUBLIC_CONVERSATION) : [...value, PUBLIC_CONVERSATION])}><Hash size={14} />公共聊天室</button>{users.map((user) => { const conversation = conversations.find((item) => item.kind === 'direct' && item.title === user.username); const id = conversation?.id || directIdFallback(currentUser.username, user.username); return <button key={user.username} className={forwardTargets.includes(id) ? 'target selected' : 'target'} onClick={() => setForwardTargets((value) => value.includes(id) ? value.filter((item) => item !== id) : [...value, id])}><Avatar user={user} size="small" />{user.display_name}</button> })}</div><button className="primary-button full" disabled={!forwardTargets.length} onClick={() => void forwardMessage()}><Forward size={15} />转发</button></div><div className="report-box"><strong><Flag size={15} />举报消息</strong><textarea value={reportReason} onChange={(event) => setReportReason(event.target.value)} maxLength={500} rows={3} placeholder="请说明原因" /><button className="danger-button full" disabled={!reportReason.trim()} onClick={() => void reportMessage()}><Flag size={15} />提交举报</button></div></FloatingWindow>}
      {showToken && <FloatingWindow title="机器人 Token" eyebrow="BOT ACCESS" className="token-window" onClose={() => setShowToken(false)}><p className="muted">每个账号只保留一个有效 token。替换后旧 token 立即失效，明文只显示一次。</p>{tokenValue ? <div className="token-result"><code>{tokenValue}</code><button className="primary-button" onClick={() => void navigator.clipboard?.writeText(tokenValue)}>复制</button></div> : <button className="primary-button full" disabled={tokenBusy} onClick={() => void createBotToken()}>{tokenBusy ? '正在创建…' : '创建 Token'}<Plus size={16} /></button>}<button className="danger-button full" onClick={() => void revokeBotToken()}><Trash2 size={15} />撤销当前 Token</button></FloatingWindow>}
      {previewFile && <FilePreviewWindow file={previewFile} onClose={() => setPreviewFile(null)} />}
    </div>
  )
}

function ConversationRow({ conversation, active, onClick, user, publicChat = false }: { conversation: Conversation; active: boolean; onClick: () => void; user?: User; publicChat?: boolean }) {
  return <button className={`conversation-row ${active ? 'active' : ''}`} onClick={onClick}><div className="conversation-avatar">{publicChat ? <Hash size={17} /> : <Avatar user={user || conversation.participants[0]} size="small" />}</div><div className="conversation-copy"><strong>{publicChat ? '公共聊天室' : user?.display_name || conversation.title}</strong><span>{publicChat ? '所有人' : user?.status || `@${conversation.title}`}</span></div>{conversation.pinned && <Pin size={12} className="row-state-icon" />}{conversation.muted && <VolumeX size={12} className="row-state-icon" />}{conversation.unread > 0 && <b className="unread-badge">{conversation.unread > 9 ? '9+' : conversation.unread}</b>}</button>
}

function directIdFallback(first: string, second: string) {
  const values = JSON.stringify([first, second].sort())
  const bytes = new TextEncoder().encode(values)
  let binary = ''
  bytes.forEach((byte) => { binary += String.fromCharCode(byte) })
  return `dm:${btoa(binary).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')}`
}

function App() {
  const [user, setUser] = useState<User | null>(null)
  const [booting, setBooting] = useState(true)
  useEffect(() => {
    api<{ user: User; csrf_token?: string }>('/api/v2/auth/me')
      .then((result) => { setUser(result.user); csrfToken = result.csrf_token || '' })
      .catch(() => undefined)
      .finally(() => setBooting(false))
  }, [])
  if (booting) return <main className="loading-page"><Zap size={20} />正在连接…</main>
  if (!user) return <LoginView onLogin={setUser} />
  return <ChatShell currentUser={user} onLogout={() => { void api('/api/v2/auth/logout', { method: 'POST' }).catch(() => undefined); setUser(null); csrfToken = '' }} onUserUpdated={setUser} />
}

export default App

const root = document.getElementById('root')
if (root) createRoot(root).render(<App />)
