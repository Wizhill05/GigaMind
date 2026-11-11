"""Local SQLite snapshots. Callers must supply both paths explicitly."""
import hashlib
import hmac
import os
import re
from contextlib import closing
from pathlib import Path
import sqlite3
from urllib.parse import quote


def _path(value):
    value = os.fspath(value)
    if '://' in value or value.startswith('file:') or value == ':memory:':
        raise ValueError('Expected a local filesystem path, not a database URL')
    return Path(value).absolute()


def _copy(source, target, validate=None):
    source, target = _path(source), _path(target)
    if source.is_symlink() or not source.is_file():
        raise ValueError('Source must be an existing regular file, not a symlink')
    if source.resolve() == target.resolve():
        raise ValueError('Source and target must differ')
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    identity = os.fstat(fd)
    os.close(fd)
    try:
        uri = 'file:' + quote(str(source), safe='/') + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True)) as src, closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('SQLite integrity check failed')
        if validate:
            validate(target)
        with open(target, 'rb') as artifact:
            digest = hashlib.file_digest(artifact, 'sha256').hexdigest()
        return digest
    except BaseException:
        try:
            current = os.lstat(target)
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                os.unlink(target)
        except FileNotFoundError:
            pass
        raise


def backup(db, output):
    return _copy(db, output)


def restore(db, output, expected_sha256=None):
    if expected_sha256 is not None:
        if (not isinstance(expected_sha256, str)
                or not re.fullmatch(r'[0-9a-fA-F]{64}', expected_sha256)):
            raise ValueError('Expected SHA-256 must be 64 hexadecimal characters')
        source = _path(db)
        if source.is_symlink() or not source.is_file():
            raise ValueError('Source must be an existing regular file, not a symlink')
        with source.open('rb') as artifact:
            actual = hashlib.file_digest(artifact, 'sha256').hexdigest()
        if not hmac.compare_digest(actual, expected_sha256.lower()):
            raise ValueError('Input SHA-256 mismatch')

    def validate(path):
        # The database module registers models but initializes an engine at import.
        # Force that unused engine to be in-memory, regardless of inherited settings.
        saved = {k: os.environ.get(k) for k in ('DATABASE_URL', 'DB_PATH', 'ENVIRONMENT', 'RENDER', 'PYTHON_DOTENV_DISABLED')}
        try:
            os.environ.update(DATABASE_URL='', DB_PATH=':memory:', ENVIRONMENT='test', PYTHON_DOTENV_DISABLED='1')
            os.environ.pop('RENDER', None)
            from gigamind.db import database, migrations  # noqa: F401
            from gigamind.db import memory_index  # noqa: F401
            from gigamind import security  # noqa: F401
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        from sqlalchemy import create_engine
        from sqlalchemy.engine import URL
        engine = create_engine(URL.create('sqlite', database=str(path)))
        try:
            version = migrations.schema_version(engine)
            if not isinstance(version, int) or not 1 <= version <= migrations.VERSION:
                raise ValueError(f'Unsupported schema version: {version}')
            if version == migrations.VERSION and not migrations.schema_ready(engine):
                raise ValueError('Current-version schema is incomplete')
            migrations.migrate(engine)
            if not migrations.schema_ready(engine):
                raise ValueError('Restored schema is not ready')
            with engine.connect() as conn:
                if conn.exec_driver_sql('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise ValueError('Restored SQLite integrity check failed')
        finally:
            engine.dispose()
    return _copy(db, output, validate)
