"""Read-only migration smoke test for the legacy hzx-chat data layout.

The test connects to MongoDB, projects every legacy message into the v2
message shape, and checks that referenced uploads and user Emoji files are
available from the supplied legacy server directory. It never writes to
MongoDB or changes the source files.

Examples:
    python migration_smoke_test.py --source C:\\old-chat --mongo-uri mongodb://127.0.0.1:27017
    python migration_smoke_test.py --source C:\\old-chat --mongo-uri mongodb://... --json
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from pymongo import MongoClient


PUBLIC_CONVERSATION = 'public'
KNOWN_MESSAGE_FIELDS = {
    '_id', 'id', 'chat', 'content', 'user', 'color', 'time', 'timestamp',
    'created_at', 'type', 'recalled', 'revoked', 'reply_to', 'recalled_at',
    'conversation_id', 'format', 'edited', 'edited_at', 'reactions',
    'attachments', 'forwarded_from',
}
MARKERS = {
    '::img::': 'image',
    '::wav::': 'audio',
    '::file::': 'file',
    '::emoji::': 'emoji',
}
TEXT_EXTENSIONS = {
    'txt', 'text', 'md', 'markdown', 'rst', 'log', 'csv', 'tsv', 'json', 'jsonl',
    'yaml', 'yml', 'xml', 'html', 'htm', 'css', 'scss', 'less', 'js', 'mjs',
    'cjs', 'ts', 'tsx', 'jsx', 'vue', 'svelte', 'py', 'pyw', 'rb', 'php', 'java',
    'c', 'cc', 'cpp', 'cxx', 'h', 'hh', 'hpp', 'cs', 'go', 'rs', 'swift', 'kt',
    'kts', 'scala', 'sh', 'bash', 'zsh', 'fish', 'bat', 'cmd', 'ps1', 'psm1',
    'ini', 'cfg', 'conf', 'toml', 'env', 'sql', 'r', 'pl', 'pm', 'lua', 'make',
    'gradle', 'properties', 'gitignore', 'dockerfile', 'in', 'out',
}


def as_text(value: Any) -> str:
    return '' if value is None else str(value)


def parse_timestamp(value: Any) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        return float(value or 0)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        return datetime.strptime(str(value), '%Y:%m:%d:%H:%M').timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def message_id(document: dict[str, Any], index: int) -> str:
    if document.get('id'):
        return str(document['id'])
    if document.get('_id') is not None:
        return 'legacy-' + str(document['_id'])
    return 'legacy-' + str(index)


def infer_type(content: str, stored_type: Any, user: str) -> str:
    if user == 'system' or content == 'clear':
        return 'system'
    for marker, kind in MARKERS.items():
        if content.startswith(marker):
            return kind
    return as_text(stored_type) or 'text'


def safe_filename(value: Any) -> str | None:
    filename = as_text(value).strip()
    if not filename or filename in {'.', '..'} or Path(filename).name != filename:
        return None
    if '/' in filename or '\\' in filename:
        return None
    return filename


def attachment_from_marker(content: str, user: str) -> tuple[dict[str, Any] | None, str | None]:
    for marker, kind in MARKERS.items():
        if not content.startswith(marker):
            continue
        filename = safe_filename(content[len(marker):])
        if not filename:
            return None, kind
        if kind == 'emoji':
            url = '/chat/emoji/static/%s/%s' % (user, filename)
        else:
            url = '/static/uploads/' + filename
        return {
            'id': None,
            'name': filename,
            'mime': mimetypes.guess_type(filename)[0] or 'application/octet-stream',
            'url': url,
        }, None
    return None, None


def project_message(document: dict[str, Any], index: int) -> dict[str, Any]:
    content = as_text(document.get('content', document.get('chat', '')))
    user = as_text(document.get('user'))
    kind = infer_type(content, document.get('type'), user)
    attachments = list(document.get('attachments') or []) if isinstance(document.get('attachments'), list) else []
    marker_attachment, marker_error = attachment_from_marker(content, user)
    if not attachments and marker_attachment:
        attachments = [marker_attachment]
    created_at = parse_timestamp(document.get('created_at', document.get('timestamp', document.get('time'))))
    return {
        'id': message_id(document, index),
        'conversation_id': as_text(document.get('conversation_id')) or PUBLIC_CONVERSATION,
        'user': user,
        'color': as_text(document.get('color')) or '#888888',
        'time': as_text(document.get('time')),
        'timestamp': created_at,
        'created_at': created_at,
        'content': content,
        'format': as_text(document.get('format')) or ('plain' if kind != 'text' else 'markdown'),
        'type': kind,
        'recalled': bool(document.get('recalled', document.get('revoked', False))),
        'reply_to': as_text(document.get('reply_to')) or None,
        'attachments': attachments,
        '_marker_error': marker_error,
    }


def read_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding='utf-8-sig', errors='replace').splitlines() if line.strip()]


def add_issue(result: dict[str, Any], kind: str, message: str, **details: Any) -> None:
    item = {'kind': kind, 'message': message}
    item.update(details)
    result['errors'].append(item)


def add_warning(result: dict[str, Any], kind: str, message: str, **details: Any) -> None:
    item = {'kind': kind, 'message': message}
    item.update(details)
    result['warnings'].append(item)


def scan(source: str | os.PathLike[str], documents: list[dict[str, Any]], metadata_documents: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    root = Path(source).resolve()
    result: dict[str, Any] = {
        'source': str(root),
        'messages': 0,
        'users': 0,
        'emoji_files': 0,
        'upload_files': 0,
        'type_counts': {},
        'attachment_references': 0,
        'emoji_references': 0,
        'conversion_projection': 0,
        'errors': [],
        'warnings': [],
    }
    upload_root = root / 'static' / 'uploads'
    emoji_root = root / 'static' / 'emoji'
    if not root.is_dir():
        add_issue(result, 'source_missing', 'source directory does not exist')
        return result
    if not upload_root.is_dir():
        add_issue(result, 'uploads_missing', 'static/uploads directory does not exist')
    if not emoji_root.is_dir():
        add_warning(result, 'emoji_root_missing', 'static/emoji directory does not exist')

    usernames = read_lines(root / 'usernames.list')
    passwords = read_lines(root / 'passwords.list')
    colors = read_lines(root / 'colors.list')
    result['users'] = len(usernames)
    if not usernames:
        add_issue(result, 'users_missing', 'usernames.list is empty or missing')
    if len(passwords) < len(usernames):
        add_issue(result, 'passwords_short', 'passwords.list has fewer entries than usernames.list', usernames=len(usernames), passwords=len(passwords))
    if len(colors) < len(usernames):
        add_warning(result, 'colors_short', 'colors.list has fewer entries; missing users will use the default color', usernames=len(usernames), colors=len(colors))
    duplicates = sorted(name for name, count in Counter(usernames).items() if count > 1)
    if duplicates:
        add_issue(result, 'duplicate_users', 'usernames.list contains duplicate usernames', users=duplicates)

    projections: list[dict[str, Any]] = []
    ids: set[str] = {message_id(document, index) for index, document in enumerate(documents) if isinstance(document, dict)}
    raw_ids: set[str] = {
        as_text(value)
        for document in documents
        if isinstance(document, dict)
        for value in (document.get('id'), document.get('_id'))
        if value is not None
    }
    referenced_uploads: set[str] = set()
    referenced_emojis: set[tuple[str, str]] = set()
    type_counts: Counter[str] = Counter()
    known_users = set(usernames)
    if not documents:
        add_issue(result, 'messages_empty', 'message collection is empty')
    valid_document_count = sum(1 for document in documents if isinstance(document, dict))
    if len(ids) != valid_document_count:
        add_issue(result, 'duplicate_message_ids', 'multiple messages would receive the same v2 message id', documents=valid_document_count, unique_ids=len(ids))
    for index, document in enumerate(documents):
        if not isinstance(document, dict):
            add_issue(result, 'invalid_document', 'message document is not an object', index=index)
            continue
        result['messages'] += 1
        identifier = message_id(document, index)
        unknown = sorted(set(document) - KNOWN_MESSAGE_FIELDS)
        if unknown:
            add_warning(result, 'unknown_fields', 'message contains fields not represented in the v2 projection', id=identifier, fields=unknown)
        projection = project_message(document, index)
        projections.append(projection)
        result['conversion_projection'] += 1
        type_counts[projection['type']] += 1
        if not projection['user']:
            add_issue(result, 'missing_user', 'message has no user', id=identifier)
        elif known_users and projection['user'] not in known_users:
            add_warning(result, 'unknown_user', 'message user is not in usernames.list', id=identifier, user=projection['user'])
        if projection['_marker_error']:
            add_issue(result, 'invalid_marker_filename', 'attachment marker has an invalid filename', id=identifier, type=projection['_marker_error'])
        if document.get('content') is not None and document.get('chat') is not None and as_text(document['content']) != as_text(document['chat']):
            add_warning(result, 'content_chat_mismatch', 'content and chat fields differ; content wins in v2', id=identifier)
        if projection['created_at'] <= 0:
            add_warning(result, 'invalid_timestamp', 'message timestamp could not be normalized', id=identifier)
        reply_to = projection['reply_to']
        if reply_to and reply_to not in raw_ids and reply_to not in ids and 'legacy-' + reply_to not in ids:
            add_issue(result, 'missing_reply_target', 'reply_to points to a message not present in the source collection', id=identifier, reply_to=reply_to)
        for attachment in projection['attachments']:
            if not isinstance(attachment, dict):
                add_issue(result, 'invalid_attachment', 'attachment entry is not an object', id=identifier)
                continue
            result['attachment_references'] += 1
            name = safe_filename(attachment.get('name'))
            if not name:
                add_issue(result, 'invalid_attachment_name', 'attachment has an unsafe or empty filename', id=identifier)
                continue
            if projection['type'] == 'emoji' or '/chat/emoji/static/' in as_text(attachment.get('url')):
                result['emoji_references'] += 1
                referenced_emojis.add((projection['user'], name))
            else:
                referenced_uploads.add(name)

    for projection in projections:
        if projection['id'] not in ids:
            add_issue(result, 'projection_id_missing', 'converted message did not receive a stable id', id=projection['id'])
        if projection['content'] is None:
            add_issue(result, 'projection_content_missing', 'converted message lost content', id=projection['id'])

    for filename in sorted(referenced_uploads):
        path = upload_root / filename
        if not path.is_file():
            add_issue(result, 'missing_upload', 'referenced upload does not exist', path=str(path), filename=filename)
        else:
            try:
                with path.open('rb') as stream:
                    stream.read(1)
            except OSError as exc:
                add_issue(result, 'unreadable_upload', 'referenced upload cannot be read', path=str(path), filename=filename, detail=str(exc))
    for username, filename in sorted(referenced_emojis):
        path = emoji_root / username / filename
        if not path.is_file():
            add_issue(result, 'missing_emoji', 'referenced Emoji file does not exist', path=str(path), username=username, filename=filename)
        else:
            try:
                with path.open('rb') as stream:
                    stream.read(1)
            except OSError as exc:
                add_issue(result, 'unreadable_emoji', 'referenced Emoji file cannot be read', path=str(path), username=username, filename=filename, detail=str(exc))

    if upload_root.is_dir():
        result['upload_files'] = sum(1 for item in upload_root.iterdir() if item.is_file())
        for item in upload_root.iterdir():
            if item.is_file() and item.name not in referenced_uploads:
                add_warning(result, 'orphan_upload', 'upload exists but is not referenced by a message', filename=item.name)
    if emoji_root.is_dir():
        result['emoji_files'] = sum(1 for item in emoji_root.rglob('*') if item.is_file())
        for item in emoji_root.rglob('*'):
            if not item.is_file():
                continue
            username = item.parent.name
            if (username, item.name) not in referenced_emojis:
                add_warning(result, 'orphan_emoji', 'Emoji file exists but is not referenced by a message', username=username, filename=item.name)

    metadata_documents = metadata_documents or []
    metadata_by_id = {as_text(item.get('file_id')): item for item in metadata_documents if item.get('file_id')}
    for document in documents:
        if not isinstance(document, dict):
            continue
        attachments = document.get('attachments') if isinstance(document.get('attachments'), list) else []
        for attachment in attachments:
            if not isinstance(attachment, dict) or not attachment.get('id'):
                continue
            file_id = as_text(attachment.get('id'))
            if file_id not in metadata_by_id:
                add_warning(result, 'missing_file_metadata', 'v2 attachment id has no v2 file metadata record; it may be a legacy reference', file_id=file_id)
                continue
            metadata = metadata_by_id[file_id]
            if metadata.get('storage') == 'disk':
                path = Path(as_text(metadata.get('path'))).resolve()
                if not path.is_file():
                    add_issue(result, 'missing_v2_upload', 'v2 disk attachment metadata points to a missing file', file_id=file_id, path=str(path))

    result['type_counts'] = dict(type_counts)
    result['safe_to_migrate'] = not result['errors']
    return result


def connect_collection(uri: str, database: str, collection: str):
    client = MongoClient(uri, serverSelectionTimeoutMS=3_000)
    client.admin.command('ping')
    db = client[database]
    return client, db[collection], db['v2_file_metadata']


def print_summary(result: dict[str, Any]) -> None:
    print('Migration smoke test')
    print('source:', result['source'])
    print('messages:', result['messages'])
    print('users:', result['users'])
    print('types:', result['type_counts'])
    print('upload files:', result['upload_files'])
    print('emoji files:', result['emoji_files'])
    print('attachment references:', result['attachment_references'])
    print('emoji references:', result['emoji_references'])
    print('conversion projections:', result['conversion_projection'])
    print('warnings:', len(result['warnings']))
    print('errors:', len(result['errors']))
    print('safe_to_migrate:', result['safe_to_migrate'])
    for item in result['errors'][:20]:
        print('ERROR:', item.get('kind'), item.get('message'), json.dumps({key: value for key, value in item.items() if key not in {'kind', 'message'}}, ensure_ascii=False, default=str))
    for item in result['warnings'][:10]:
        print('WARN:', item.get('kind'), item.get('message'), json.dumps({key: value for key, value in item.items() if key not in {'kind', 'message'}}, ensure_ascii=False, default=str))
    if len(result['errors']) > 20 or len(result['warnings']) > 10:
        print('Additional issues are available with --json or --report.')


def run_self_test() -> int:
    import tempfile

    import mongomock

    with tempfile.TemporaryDirectory(prefix='hzx-migration-smoke-') as temporary:
        root = Path(temporary)
        (root / 'static' / 'uploads').mkdir(parents=True)
        (root / 'static' / 'emoji' / 'alice').mkdir(parents=True)
        (root / 'usernames.list').write_text('alice\nbob\n', encoding='utf-8')
        (root / 'passwords.list').write_text('hash-a\nhash-b\n', encoding='utf-8')
        (root / 'colors.list').write_text('#fff\n#000\n', encoding='utf-8')
        (root / 'static' / 'uploads' / 'starway_ac.cpp').write_text('#include <bits/stdc++.h>\nint main() { return 0; }\n', encoding='utf-8')
        (root / 'static' / 'emoji' / 'alice' / 'wave.png').write_bytes(bytes([137, 80, 78, 71]))
        collection = mongomock.MongoClient().chats.values
        collection.insert_many([
            {'id': 'm1', 'chat': '::file::starway_ac.cpp', 'user': 'alice', 'time': '2026:08:04:12:00'},
            {'id': 'm2', 'chat': '::emoji::wave.png', 'user': 'alice', 'time': '2026:08:04:12:01', 'reply_to': 'm1'},
        ])
        passed = scan(root, list(collection.find().sort('_id', 1)))
        if not passed['safe_to_migrate'] or passed['attachment_references'] != 2:
            print('SELF-TEST FAILED: complete fixture was rejected')
            print(json.dumps(passed, ensure_ascii=False, indent=2, default=str))
            return 1
        (root / 'static' / 'uploads' / 'starway_ac.cpp').unlink()
        failed = scan(root, list(collection.find().sort('_id', 1)))
        if failed['safe_to_migrate'] or not any(item['kind'] == 'missing_upload' for item in failed['errors']):
            print('SELF-TEST FAILED: missing upload was not detected')
            print(json.dumps(failed, ensure_ascii=False, indent=2, default=str))
            return 1
    print('SELF-TEST PASSED: complete and missing-asset fixtures behaved as expected')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Read-only smoke test for legacy hzx-chat migration compatibility.')
    parser.add_argument('--source', default=str(Path(__file__).resolve().parent), help='Legacy server root containing static/ and user lists.')
    parser.add_argument('--mongo-uri', default='mongodb://127.0.0.1:27017', help='MongoDB URI for the legacy database.')
    parser.add_argument('--database', default='chats', help='MongoDB database name.')
    parser.add_argument('--collection', default='values', help='Legacy message collection name.')
    parser.add_argument('--json', action='store_true', help='Print the full report as JSON.')
    parser.add_argument('--report', help='Also write the JSON report to this path.')
    parser.add_argument('--self-test', action='store_true', help='Run isolated in-memory fixtures instead of connecting to MongoDB.')
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    try:
        client, collection, metadata_collection = connect_collection(args.mongo_uri, args.database, args.collection)
        documents = list(collection.find().sort('_id', 1))
        metadata_documents = list(metadata_collection.find())
    except Exception as exc:
        result = {
            'source': str(Path(args.source).resolve()),
            'safe_to_migrate': False,
            'messages': 0,
            'errors': [{'kind': 'database_unavailable', 'message': str(exc), 'mongo_uri': args.mongo_uri}],
            'warnings': [],
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            print('Migration smoke test failed: MongoDB is unavailable')
            print(str(exc))
        return 2
    finally:
        if 'client' in locals():
            client.close()

    result = scan(args.source, documents, metadata_documents)
    if args.report:
        Path(args.report).resolve().write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print_summary(result)
    return 0 if result['safe_to_migrate'] else 2


if __name__ == '__main__':
    sys.exit(main())
