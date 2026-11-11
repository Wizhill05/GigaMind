"""Pure normalization of conversation exports into immutable source versions."""

import hashlib
import json
import math
from datetime import datetime, timezone

MAX_BYTES = 20_000_000
MAX_CONVERSATIONS = 5000


def _text(value, depth=0):
    if depth > 32:
        raise ValueError("Message content exceeds nesting limit")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "parts" in value:
            return _text(value["parts"], depth + 1)
        return _text(value.get("text", ""), depth + 1)
    if isinstance(value, list):
        return "\n".join(t for item in value if (t := _text(item, depth + 1)))
    return ""


def _message(msg, node_id=None):
    if not isinstance(msg, dict):
        raise ValueError("Message must be an object")
    author = msg.get("author")
    role = (
        author.get("role")
        if isinstance(author, dict)
        else msg.get("role", msg.get("sender"))
    )
    if role is not None and not isinstance(role, str):
        raise ValueError("Invalid message role")
    role = "user" if role == "human" else role
    if not role:
        role = "unknown"
    if len(role) > 128:
        raise ValueError("Message role exceeds size limit")
    content = _text(msg.get("content")) or _text(msg.get("text"))
    if not content:
        return None
    result = {"role": role, "content": content}
    identifier = node_id if node_id is not None else msg.get("uuid", msg.get("id"))
    if identifier is not None:
        if not isinstance(identifier, str) or len(identifier) > 4096:
            raise ValueError("Invalid message identifier")
        result["id"] = identifier
    timestamp = msg.get("create_time", msg.get("created_at"))
    if timestamp is not None:
        try:
            valid_time = (
                not isinstance(timestamp, bool)
                and isinstance(timestamp, (str, int, float))
                and (isinstance(timestamp, str) or math.isfinite(timestamp))
            )
        except OverflowError:
            valid_time = False
        if not valid_time:
            raise ValueError("Invalid message timestamp")
        result["created_at"] = timestamp
    return result


def _branch(conv):
    mapping = conv["mapping"]
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("ChatGPT mapping must be a nonempty object")
    for key, node in mapping.items():
        if not isinstance(key, str) or not isinstance(node, dict):
            raise ValueError("Invalid ChatGPT node")
        if node.get("parent") is not None and not isinstance(node["parent"], str):
            raise ValueError("Invalid ChatGPT parent")
    current = conv.get("current_node")
    if current is None:
        parents = {
            n.get("parent") for n in mapping.values() if n.get("parent") is not None
        }
        leaves = set(mapping) - parents
        if len(leaves) != 1:
            raise ValueError("ChatGPT branch is ambiguous or cyclic")
        current = next(iter(leaves))
        # An unselected export must contain exactly one branch.
        require_all = True
    else:
        require_all = False
    seen, nodes = set(), []
    while current is not None:
        if not isinstance(current, str) or current not in mapping:
            raise ValueError("ChatGPT branch references a missing ancestor")
        if current in seen:
            raise ValueError("ChatGPT branch contains a cycle")
        seen.add(current)
        node = mapping[current]
        nodes.append((current, node))
        current = node.get("parent")
    if require_all and len(seen) != len(mapping):
        raise ValueError("ChatGPT branch is ambiguous or cyclic")
    messages = []
    for key, node in reversed(nodes):
        if node.get("message") is not None:
            msg = _message(node["message"], key)
            if msg:
                messages.append(msg)
    return messages


def _created_at(value):
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        raise ValueError("Invalid conversation timestamp")
    if isinstance(value, (int, float)):
        try:
            if not math.isfinite(value):
                raise ValueError
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            raise ValueError("Invalid conversation timestamp") from None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
            return parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            raise ValueError("Invalid conversation timestamp") from None
    raise ValueError("Invalid conversation timestamp")


def normalize_conversations(raw, default_platform=None):
    try:
        if isinstance(raw, (bytes, bytearray)):
            if len(raw) > MAX_BYTES:
                raise ValueError("Import exceeds size limit")
            raw = raw.decode("utf-8")
        if isinstance(raw, str):
            if len(raw.encode("utf-8")) > MAX_BYTES:
                raise ValueError("Import exceeds size limit")
            raw = json.loads(raw)
        else:
            encoded = json.dumps(raw, ensure_ascii=False, allow_nan=False).encode(
                "utf-8"
            )
            if len(encoded) > MAX_BYTES:
                raise ValueError("Import exceeds size limit")
    except (UnicodeError, TypeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Invalid JSON import") from exc
    conversations = [raw] if isinstance(raw, dict) else raw
    if not isinstance(conversations, list) or len(conversations) > MAX_CONVERSATIONS:
        raise ValueError("Import must be a bounded list or object")
    result = []
    for conv in conversations:
        if not isinstance(conv, dict):
            raise ValueError("Conversation must be an object")
        if "mapping" in conv:
            platform, agent, title = "chatgpt", "gpt", conv.get("title")
            messages = _branch(conv)
        elif "chat_messages" in conv or "messages" in conv:
            claude = "chat_messages" in conv
            platform, agent = (
                ("claude", "claude")
                if claude
                else (
                    conv.get("platform") or "custom",
                    conv.get("source_agent") or "user",
                )
            )
            title = conv.get("name") if claude else conv.get("title")
            items = conv["chat_messages" if claude else "messages"]
            if not isinstance(items, list):
                raise ValueError("Messages must be a list")
            messages = [m for item in items if (m := _message(item))]
        else:
            raise ValueError("Conversation has no recognized messages")
        platform = default_platform if default_platform is not None else platform
        title = title or "Imported Conversation"
        summary = conv.get("summary") or ""
        created_at = conv.get("created_at")
        created_at = _created_at(
            created_at if created_at is not None else conv.get("create_time")
        )
        source_id = conv.get("id") if conv.get("id") is not None else conv.get("uuid")
        if not all(isinstance(x, str) for x in (platform, agent, title, summary)) or (
            source_id is not None and not isinstance(source_id, str)
        ):
            raise ValueError("Invalid conversation metadata")
        if (
            not platform.strip()
            or not agent.strip()
            or len(platform.encode("utf-8")) > 512
            or len(agent.encode("utf-8")) > 512
        ):
            raise ValueError("Invalid indexed conversation metadata")
        if not messages:
            raise ValueError("Conversation has no text messages")
        canonical = {
            "platform": platform,
            "source_agent": agent,
            "title": title,
            "summary": summary,
            "created_at": created_at,
            "messages": messages,
            "source_id": source_id,
        }
        digest = hashlib.sha256(
            json.dumps(
                canonical,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        canonical["id"] = "import_" + digest
        result.append(canonical)
    return result
