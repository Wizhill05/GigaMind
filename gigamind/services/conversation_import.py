"""Pure normalization of conversation exports into immutable source versions."""
import hashlib
import json

MAX_BYTES = 20_000_000
MAX_CONVERSATIONS = 5000


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if 'parts' in value:
            return _text(value['parts'])
        return _text(value.get('text', ''))
    if isinstance(value, list):
        return '\n'.join(t for item in value if (t := _text(item)))
    return ''


def _message(msg, node_id=None):
    if not isinstance(msg, dict):
        raise ValueError('Message must be an object')
    author = msg.get('author')
    role = author.get('role') if isinstance(author, dict) else msg.get('role', msg.get('sender'))
    role = {'human': 'user'}.get(role, role)
    if not isinstance(role, str) or not role:
        role = 'unknown'
    content = _text(msg.get('content')) or _text(msg.get('text'))
    if not content:
        return None
    result = {'role': role, 'content': content}
    identifier = node_id if node_id is not None else msg.get('uuid', msg.get('id'))
    if identifier is not None:
        result['id'] = identifier
    timestamp = msg.get('create_time', msg.get('created_at'))
    if timestamp is not None:
        result['created_at'] = timestamp
    return result


def _branch(conv):
    mapping = conv['mapping']
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError('ChatGPT mapping must be a nonempty object')
    for key, node in mapping.items():
        if not isinstance(key, str) or not isinstance(node, dict):
            raise ValueError('Invalid ChatGPT node')
    current = conv.get('current_node')
    if current is None:
        parents = {n.get('parent') for n in mapping.values() if n.get('parent') is not None}
        leaves = set(mapping) - parents
        if len(leaves) != 1:
            raise ValueError('ChatGPT branch is ambiguous or cyclic')
        current = next(iter(leaves))
        # An unselected export must contain exactly one branch.
        require_all = True
    else:
        require_all = False
    seen, nodes = set(), []
    while current is not None:
        if not isinstance(current, str) or current not in mapping:
            raise ValueError('ChatGPT branch references a missing ancestor')
        if current in seen:
            raise ValueError('ChatGPT branch contains a cycle')
        seen.add(current)
        node = mapping[current]
        nodes.append((current, node))
        current = node.get('parent')
    if require_all and len(seen) != len(mapping):
        raise ValueError('ChatGPT branch is ambiguous or cyclic')
    messages = []
    for key, node in reversed(nodes):
        if node.get('message') is not None:
            msg = _message(node['message'], key)
            if msg:
                messages.append(msg)
    return messages


def normalize_conversations(raw, default_platform=None):
    try:
        if isinstance(raw, (bytes, bytearray)):
            if len(raw) > MAX_BYTES:
                raise ValueError('Import exceeds size limit')
            raw = raw.decode('utf-8')
        if isinstance(raw, str):
            if len(raw.encode('utf-8')) > MAX_BYTES:
                raise ValueError('Import exceeds size limit')
            raw = json.loads(raw)
        else:
            encoded = json.dumps(raw, ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(encoded) > MAX_BYTES:
                raise ValueError('Import exceeds size limit')
    except (UnicodeError, TypeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('Invalid JSON import') from exc
    conversations = [raw] if isinstance(raw, dict) else raw
    if not isinstance(conversations, list) or len(conversations) > MAX_CONVERSATIONS:
        raise ValueError('Import must be a bounded list or object')
    result = []
    for conv in conversations:
        if not isinstance(conv, dict):
            raise ValueError('Conversation must be an object')
        if 'mapping' in conv:
            platform, agent, title = 'chatgpt', 'gpt', conv.get('title')
            messages = _branch(conv)
        elif 'chat_messages' in conv or 'messages' in conv:
            claude = 'chat_messages' in conv
            platform, agent = ('claude', 'claude') if claude else (conv.get('platform') or 'custom', conv.get('source_agent') or 'user')
            title = conv.get('name') if claude else conv.get('title')
            items = conv['chat_messages' if claude else 'messages']
            if not isinstance(items, list):
                raise ValueError('Messages must be a list')
            messages = [m for item in items if (m := _message(item))]
        else:
            raise ValueError('Conversation has no recognized messages')
        platform = default_platform or platform
        title = title or 'Imported Conversation'
        summary = conv.get('summary') or ''
        created_at = conv.get('created_at', conv.get('create_time', ''))
        source_id = conv.get('id', conv.get('uuid'))
        if not all(isinstance(x, str) for x in (platform, agent, title, summary)) or not isinstance(created_at, (str, int, float)) or (source_id is not None and not isinstance(source_id, str)):
            raise ValueError('Invalid conversation metadata')
        if not messages:
            raise ValueError('Conversation has no text messages')
        canonical = {'platform': platform, 'source_agent': agent, 'title': title, 'summary': summary, 'created_at': str(created_at), 'messages': messages, 'source_id': source_id}
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        canonical['id'] = 'import_' + digest
        result.append(canonical)
    return result
