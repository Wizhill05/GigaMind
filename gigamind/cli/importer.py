"""Import exported conversations as unindexed sources."""
import argparse
import sys
from pathlib import Path

from gigamind.db.database import init_db
from gigamind.services.conversation_import import MAX_BYTES
from gigamind.services.memory import import_conversations_data


def main():
    parser = argparse.ArgumentParser(description="Import conversation exports")
    parser.add_argument('--chatgpt')
    parser.add_argument('--claude')
    args = parser.parse_args()
    if not args.chatgpt and not args.claude:
        parser.error('provide --chatgpt or --claude')
    try:
        # Validate all inputs before initializing or writing the database.
        from gigamind.services.conversation_import import normalize_conversations
        inputs = []
        for platform in ('chatgpt', 'claude'):
            path = getattr(args, platform)
            if path:
                with Path(path).open('rb') as file:
                    data = file.read(MAX_BYTES + 1)
                normalize_conversations(data, platform)
                inputs.append((platform, data))
        init_db()
        for platform, data in inputs:
            result = import_conversations_data(data, platform)
            print(f"{platform}: {result['message']}")
    except (OSError, ValueError) as exc:
        print(f'Import failed: {str(exc)[:300]}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
