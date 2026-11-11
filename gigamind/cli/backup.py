"""Create or restore an explicit local SQLite snapshot."""
import argparse
import os

os.environ['PYTHON_DOTENV_DISABLED'] = '1'

from gigamind.services.backup import backup, restore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('backup', 'restore'))
    parser.add_argument('--db', required=True, help='source SQLite file')
    parser.add_argument('--output', required=True, help='new output file')
    args = parser.parse_args()
    digest = (backup if args.action == 'backup' else restore)(args.db, args.output)
    print(f'SHA-256 {digest}  {args.output}')


if __name__ == '__main__':
    main()
