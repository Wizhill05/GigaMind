"""Create or restore an explicit local SQLite snapshot."""

import argparse
import os

os.environ["PYTHON_DOTENV_DISABLED"] = "1"

from gigamind.services.backup import backup, restore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "restore"))
    parser.add_argument("--db", required=True, help="source SQLite file")
    parser.add_argument("--output", required=True, help="new output file")
    parser.add_argument("--expected-sha256", help="expected SHA-256 of restore input")
    args = parser.parse_args()
    if args.action == "backup" and args.expected_sha256 is not None:
        parser.error("--expected-sha256 is only valid for restore")
    digest = (
        backup(args.db, args.output)
        if args.action == "backup"
        else restore(args.db, args.output, expected_sha256=args.expected_sha256)
    )
    print(f"SHA-256 {digest}  {args.output}")


if __name__ == "__main__":
    main()
