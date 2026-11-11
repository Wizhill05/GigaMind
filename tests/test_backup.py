import os
import sqlite3
import subprocess
import sys

import pytest
from sqlalchemy import create_engine
from gigamind.db import database, migrations  # register models
from gigamind.db import memory_index
from gigamind import security
from gigamind.db.jobs import Job, UploadManifest
from gigamind.services.backup import backup, restore


def fixture_db(path):
    engine = create_engine(f'sqlite:///{path}')
    migrations.migrate(engine)
    from sqlmodel import Session
    with Session(engine) as session:
        session.add(database.MemoryItem(id='m', content='hello', created_at='now', last_accessed='now'))
        session.add(security.ClientCredential(id='c', name='client', token_hash='hash', scopes_json='["memory:read"]', project_ids_json='["p"]', revoked=True, revision=4))
        session.add(Job(id='j', kind='index', resource_key='m', payload_json='{}', state='queued', available_at='now', created_at='now', updated_at='now'))
        session.add(UploadManifest(key='k', job_id='j', sha256='abc', size_bytes=1))
        session.add(memory_index.MemoryIndexState(memory_id='m', revision=3, created_at='now', updated_at='now'))
        session.commit()
    engine.dispose()


def test_roundtrip_and_exclusive_targets(tmp_path):
    source, snapshot, restored = (tmp_path / n for n in ('source', 'snapshot', 'restored'))
    fixture_db(source)
    before = source.read_bytes()
    assert len(backup(source, snapshot)) == 64
    assert snapshot.stat().st_mode & 0o777 == 0o600
    restore(snapshot, restored)
    with sqlite3.connect(restored) as conn:
        assert conn.execute('select content from memories').fetchone() == ('hello',)
        assert conn.execute('select revoked, revision, scopes_json from client_credentials').fetchone() == (1, 4, '["memory:read"]')
        assert conn.execute('select state from jobs').fetchone() == ('queued',)
        assert conn.execute('select job_id from upload_manifests').fetchone() == ('j',)
        assert conn.execute('select revision from memory_index_state').fetchone() == (3,)
    assert source.read_bytes() == before
    with pytest.raises(FileExistsError):
        backup(source, snapshot)
    link = tmp_path / 'link'
    link.symlink_to(snapshot)
    with pytest.raises((FileExistsError, ValueError)):
        backup(source, link)
    assert link.is_symlink()


def test_failure_cleans_output(tmp_path, monkeypatch):
    source, target = tmp_path / 'source', tmp_path / 'target'
    fixture_db(source)
    def fail(engine):
        raise RuntimeError('migration failed')
    monkeypatch.setattr(migrations, 'migrate', fail)
    with pytest.raises(RuntimeError, match='migration failed'):
        restore(source, target)
    assert not target.exists()
    source.write_bytes(b'corrupt')
    with pytest.raises(sqlite3.DatabaseError):
        restore(source, target)
    assert not target.exists()


def test_future_version_rejected(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'target'
    fixture_db(source)
    with sqlite3.connect(source) as conn:
        conn.execute('insert into schema_migrations values (?)', (migrations.VERSION + 1,))
    with pytest.raises(ValueError, match='Unsupported schema'):
        restore(source, target)
    assert not target.exists()


def test_cli_ignores_hostile_environment(tmp_path):
    source, target, sentinel = (tmp_path / n for n in ('source', 'target', 'sentinel'))
    fixture_db(source)
    sentinel.write_bytes(b'do not touch')
    env = dict(os.environ, DATABASE_URL='postgresql://invalid/remote', DB_PATH=str(sentinel), ENVIRONMENT='production', RENDER='1')
    result = subprocess.run([sys.executable, '-m', 'gigamind.cli.backup', 'restore', '--db', str(source), '--output', str(target)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert sentinel.read_bytes() == b'do not touch'
