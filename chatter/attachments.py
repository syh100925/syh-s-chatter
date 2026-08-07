"""附件上传、C++ 预览与表情包目录。"""
import os

from werkzeug.utils import secure_filename

from . import state

IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'bmp', 'gif', 'webp', 'svg', 'ico'}
AUDIO_EXTENSIONS = {'mp3', 'wav', 'flac', 'ogg', 'm4a'}
CPP_PREVIEW_LIMIT = 1024 * 1024


def upload_dir():
    return os.path.join(state.STATIC_DIR, 'uploads')


def safe_upload_path(filename):
    safe_name = secure_filename(os.path.basename(filename or ''))
    if not safe_name or safe_name in {'.', '..'}:
        return None, None
    os.makedirs(upload_dir(), exist_ok=True)
    return upload_dir(), safe_name


def attachment_filename(message):
    content = message.get('content', message.get('chat', ''))
    for prefix in ('::img::', '::wav::', '::file::'):
        if str(content).startswith(prefix):
            return str(content)[len(prefix):].strip()
    return None


def delete_attachment(message):
    filename = attachment_filename(message)
    if not filename:
        return
    path = os.path.abspath(os.path.join(upload_dir(), os.path.basename(filename)))
    if os.path.dirname(path) != os.path.abspath(upload_dir()):
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def decode_cpp(raw_bytes, label=''):
    """解码 .cpp 源码字节为文本，返回 (内容, 编码)。

    注意：GB18030 是 GBK/GB2312/Big5 的兼容超集，charset-normalizer 常把
    大陆 C++ 源码误判为 cp949/cp1252 等，导致中文注释乱码。因此只要检测
    结果命中常见中文字符集（含 cp949 等误判），一律优先按 gb18030 重解码。
    """
    ctx = ('[decode_cpp %s] ' % label) if label else '[decode_cpp] '
    detected = None
    decoded = None
    try:
        from charset_normalizer import from_bytes
        match = from_bytes(raw_bytes).best()
        if match is not None:
            detected = (match.encoding or '').lower()
            decoded = str(match)
    except Exception as exc:
        state.logger.warning('%scharset-normalizer 编码检测失败，回退 gb18030/utf-8：%s', ctx, exc)
    if detected in {'big5', 'cp950', 'gbk', 'gb2312', 'gb18030', 'cp949'}:
        try:
            mainland_text = raw_bytes.decode('gb18030')
            if any('\u4e00' <= char <= '\u9fff' for char in mainland_text):
                state.logger.info('%s检测为 %s，按 gb18030 重解码成功，返回 gb18030', ctx, detected)
                return mainland_text, 'gb18030'
            state.logger.info('%s检测为 %s，gb18030 重解码无中文字符，保留原检测结果', ctx, detected)
        except UnicodeDecodeError as exc:
            state.logger.warning('%s检测为 %s，但 gb18030 解码失败：%s，保留原检测结果', ctx, detected, exc)
    if decoded is not None:
        state.logger.info('%s使用 charset-normalizer 检测结果：%s', ctx, detected)
        return decoded, (detected or 'unknown')
    state.logger.warning('%s无可用检测结果，回退 utf-8（replace）', ctx)
    return raw_bytes.decode('utf-8', errors='replace'), 'utf-8'


def cpp_path(filename):
    if not filename or not filename.lower().endswith('.cpp'):
        return None
    # 不能用 secure_filename：上传去重后缀形如 "main (1).cpp"（含空格/括号），
    # 安全化后与磁盘上的真实文件名不一致会导致预览 404。
    path = os.path.abspath(os.path.join(upload_dir(), os.path.basename(filename)))
    return path if os.path.dirname(path) == os.path.abspath(upload_dir()) else None


def emoji_directory(username):
    safe_user = secure_filename(username or '')
    if not safe_user:
        return None
    root = os.path.abspath(os.path.join(state.STATIC_DIR, 'emoji'))
    path = os.path.abspath(os.path.join(root, safe_user))
    return path if os.path.dirname(path) == root else None
