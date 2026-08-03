"""Read-only legacy database and attachment integrity scanner.

Usage:
    python migration_scan.py
    python migration_scan.py --mongo-uri mongodb://127.0.0.1:27017 --database chats

The command never updates MongoDB or files. A non-zero exit code means the
result contains errors and should block a migration run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pymongo import MongoClient


MESSAGE_FIELDS = {
    '_id', 'id', 'chat', 'content', 'user', 'color', 'time', 'timestamp',
    'created_at', 'type', 'recalled', 'revoked', 'reply_to', 'recalled_at',
    'conversation_id', 'format', 'edited', 'edited_at', 'reactions',
    'attachments',
    'forwarded_from',
}


def _timestamp(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def scan(database, base_dir: str | os.PathLike[str]) -> dict[str, Any]:
    root = Path(base_dir).resolve()
    upload_root = root / 'static' / 'uploads'
    emoji_root = root / 'static' / 'emoji'
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    type_counts: Counter[str] = Counter()
    attachment_count = 0
    emoji_count = 0
    messages = list(database.find().sort('_id', 1))

    for index, document in enumerate(messages):
        identifier = str(document.get('id') or document.get('_id') or index)
        unknown = sorted(set(document) - MESSAGE_FIELDS)
        if unknown:
            warnings.append({'id': identifier, 'kind': 'unknown_fields', 'fields': unknown})
        user = str(document.get('user') or '')
        if not user:
            errors.append({'id': identifier, 'kind': 'missing_user'})
        content = document.get('content', document.get('chat', ''))
        if content is None:
            content = ''
        content = str(content)
        if 'content' in document and 'chat' in document and str(document['content']) != str(document['chat']):
            warnings.append({'id': identifier, 'kind': 'content_chat_mismatch'})
        if document.get('created_at') is not None and _timestamp(document.get('created_at')) <= 0:
            warnings.append({'id': identifier, 'kind': 'invalid_created_at'})

        message_type = str(document.get('type') or '')
        markers = (
            ('::img::', 'image'),
            ('::wav::', 'audio'),
            ('::file::', 'file'),
            ('::emoji::', 'emoji'),
        )
        for marker, detected_type in markers:
            if content.startswith(marker):
                message_type = detected_type
                filename = content[len(marker):].strip()
                if not filename:
                    errors.append({'id': identifier, 'kind': 'empty_attachment_name', 'type': detected_type})
                    break
                if detected_type == 'emoji':
                    emoji_count += 1
                    path = emoji_root / user / Path(filename).name
                else:
                    attachment_count += 1
                    path = upload_root / Path(filename).name
                if not path.is_file():
                    errors.append({'id': identifier, 'kind': 'missing_attachment', 'path': str(path), 'type': detected_type})
                break
        type_counts[message_type or 'text'] += 1

    return {
        'safe_to_migrate': not errors,
        'messages': len(messages),
        'type_counts': dict(type_counts),
        'attachment_references': attachment_count,
        'emoji_references': emoji_count,
        'errors': errors,
        'warnings': warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Scan legacy chats.values and attachment paths without modifying them.')
    parser.add_argument('--mongo-uri', default='', help='Optional MongoDB URI; defaults to server.py configuration.')
    parser.add_argument('--database', default='chats', help='MongoDB database name.')
    parser.add_argument('--collection', default='values', help='MongoDB message collection name.')
    parser.add_argument('--json', action='store_true', help='Emit JSON instead of a human summary.')
    args = parser.parse_args()

    if args.mongo_uri:
        client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=3000)
        database = client[args.database][args.collection]
        base_dir = Path(__file__).resolve().parent
    else:
        import server
        database = server.client[args.database][args.collection]
        base_dir = server.BASE_DIR

    result = scan(database, base_dir)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print('messages:', result['messages'])
        print('types:', result['type_counts'])
        print('attachment references:', result['attachment_references'])
        print('emoji references:', result['emoji_references'])
        print('warnings:', len(result['warnings']))
        print('errors:', len(result['errors']))
        print('safe_to_migrate:', result['safe_to_migrate'])
    return 0 if result['safe_to_migrate'] else 2


if __name__ == '__main__':
    sys.exit(main())
