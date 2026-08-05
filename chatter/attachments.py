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


def decode_cpp(raw_bytes):
    try:
        from charset_normalizer import from_bytes
        match = from_bytes(raw_bytes).best()
        if match is not None:
            detected = (match.encoding or '').lower()
            decoded = str(match)
            # 短 GB2312 样本与 Big5 难以区分；GB18030 是兼容超集，
            # 可保持常见大陆 C++ 源码可读。
            if detected in {'big5', 'cp950', 'gbk', 'gb2312', 'gb18030'}:
                try:
                    mainland_text = raw_bytes.decode('gb18030')
                    if any('\u4e00' <= char <= '\u9fff' for char in mainland_text):
                        return mainland_text, 'gb18030'
                except UnicodeDecodeError:
                    pass
            return decoded, (match.encoding or 'unknown')
    except Exception as exc:  # pragma: no cover - dependency/runtime fallback
        state.logger.warning('charset-normalizer failed: %s', exc)
    return raw_bytes.decode('utf-8', errors='replace'), 'utf-8'


def cpp_path(filename):
    safe = secure_filename(os.path.basename(filename or ''))
    if not safe or not safe.lower().endswith('.cpp'):
        return None
    path = os.path.abspath(os.path.join(upload_dir(), safe))
    return path if os.path.dirname(path) == os.path.abspath(upload_dir()) else None


def emoji_directory(username):
    safe_user = secure_filename(username or '')
    if not safe_user:
        return None
    root = os.path.abspath(os.path.join(state.STATIC_DIR, 'emoji'))
    path = os.path.abspath(os.path.join(root, safe_user))
    return path if os.path.dirname(path) == root else None
