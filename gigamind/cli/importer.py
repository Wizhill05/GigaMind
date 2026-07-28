import os
import sys
import json
import argparse
from gigamind.db.database import init_db
from gigamind.services.memory import add_conversation_log, add_memory

def extract_chatgpt_messages(mapping: dict) -> list:
    messages = []
    if not mapping:
        return messages

    for node in mapping.values():
        msg = node.get("message")
        if msg and msg.get("author") and msg.get("content") and msg["content"].get("parts"):
            role = "user" if msg["author"]["role"] == "user" else "assistant"
            parts = [p for p in msg["content"]["parts"] if isinstance(p, str) and p.strip()]
            if parts:
                messages.append({
                    "role": role,
                    "content": "\n".join(parts)
                })

    return messages

def import_chatgpt(file_path: str):
    print(f"📥 Importing ChatGPT conversations from: {file_path}...")
    with open(file_path, "r", encoding="utf-8") as f:
        conversations = json.load(f)

    count = 0
    facts_extracted = 0

    for conv in conversations:
        title = conv.get("title") or "Untitled ChatGPT Conversation"
        messages = extract_chatgpt_messages(conv.get("mapping", {}))
        if not messages:
            continue

        first_user = next((m["content"][:200] for m in messages if m["role"] == "user"), "")
        summary = f"Topic: {title}. User prompt preview: {first_user}"

        add_conversation_log("chatgpt", title, summary, messages)
        count += 1

        for m in messages:
            if m["role"] == "user" and any(k in m["content"].lower() for k in ["prefer", "project", "my name", "rule"]):
                add_memory(m["content"], category="chatgpt_import", tags=["chatgpt", "history"])
                facts_extracted += 1

    print(f"✅ Ingested {count} ChatGPT chats ({facts_extracted} key memory facts extracted).")

def import_claude(file_path: str):
    print(f"📥 Importing Claude conversations from: {file_path}...")
    with open(file_path, "r", encoding="utf-8") as f:
        conversations = json.load(f)

    count = 0
    facts_extracted = 0

    for conv in conversations:
        title = conv.get("name") or conv.get("summary") or "Untitled Claude Conversation"
        chat_messages = conv.get("chat_messages", [])

        messages = []
        for m in chat_messages:
            sender = "user" if m.get("sender") == "human" else "assistant"
            text = m.get("text") or ""
            if isinstance(m.get("content"), list):
                text = "\n".join(c.get("text", "") for c in m["content"] if isinstance(c, dict))
            if text.strip():
                messages.append({"role": sender, "content": text})

        if not messages:
            continue

        first_user = next((m["content"][:200] for m in messages if m["role"] == "user"), "")
        summary = f"Topic: {title}. User prompt preview: {first_user}"

        add_conversation_log("claude", title, summary, messages)
        count += 1

        for m in messages:
            if m["role"] == "user" and any(k in m["content"].lower() for k in ["prefer", "project", "my name", "rule"]):
                add_memory(m["content"], category="claude_import", tags=["claude", "history"])
                facts_extracted += 1

    print(f"✅ Ingested {count} Claude chats ({facts_extracted} key memory facts extracted).")

def main():
    parser = argparse.ArgumentParser(description="GigaMind Bulk Chat History Importer")
    parser.add_argument("--chatgpt", help="Path to ChatGPT conversations.json")
    parser.add_argument("--claude", help="Path to Claude conversations.json")

    args = parser.parse_args()

    if not args.chatgpt and not args.claude:
        parser.print_help()
        sys.exit(0)

    init_db()

    if args.chatgpt:
        if os.path.exists(args.chatgpt):
            import_chatgpt(args.chatgpt)
        else:
            print(f"❌ File not found: {args.chatgpt}")

    if args.claude:
        if os.path.exists(args.claude):
            import_claude(args.claude)
        else:
            print(f"❌ File not found: {args.claude}")

if __name__ == "__main__":
    main()
