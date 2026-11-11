from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine

from gigamind.db.database import StorageFileItem
from gigamind.security import Actor
from gigamind.services import file_lifecycle, jobs, memory
from gigamind.services.storage import storage_service


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path / "test.db"}', connect_args={'timeout': 10, 'check_same_thread': False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(memory, 'engine', engine)
    monkeypatch.setattr(memory, '_index_memory', lambda *args: None)
    monkeypatch.setattr(storage_service, 'is_enabled', lambda: True)
    yield engine
    engine.dispose()


admin = Actor('admin', set(), None, True)


def test_shared_references_and_worker(setup, monkeypatch):
    engine = setup
    deleted = []
    monkeypatch.setattr(storage_service, 'delete_file', lambda key: deleted.append(key) or True)
    a = memory.add_memory('first', file_keys=['file'])
    b = memory.add_memory('second', file_keys=['file'])
    for actor in (None, {'is_admin': True}, Actor('user', set(), None)):
        with pytest.raises(HTTPException) as err:
            file_lifecycle.request_delete(actor, 'file', engine)
        assert err.value.status_code == 403
    with pytest.raises(HTTPException) as err:
        file_lifecycle.request_delete(admin, 'file', engine)
    assert err.value.status_code == 409
    with Session(engine) as session:
        assert session.exec(__import__('sqlmodel').select(StorageFileItem)).first()
    memory.delete_memory(a['id'])
    with pytest.raises(HTTPException):
        file_lifecycle.request_delete(admin, 'file', engine)
    memory.delete_memory(b['id'])
    job = file_lifecycle.request_delete(admin, 'file', engine)
    assert deleted == []
    assert file_lifecycle.request_delete(admin, 'file', engine).id == job.id
    assert jobs.run_once(engine=engine).state == 'completed'
    assert deleted == ['file']
    with pytest.raises(HTTPException):
        memory.add_memory('later', file_keys=['file'])
    assert file_lifecycle.request_delete(admin, 'file', engine).id == job.id


def test_failed_cleanup_can_retry(setup, monkeypatch):
    engine = setup
    monkeypatch.setattr(storage_service, 'delete_file', lambda key: False)
    job = file_lifecycle.request_delete(admin, 'file', engine)
    with Session(engine) as session:
        row = session.get(jobs.Job, job.id)
        row.max_attempts = 1
        session.add(row)
        session.commit()
    assert jobs.run_once(engine=engine).state == 'failed'
    new = file_lifecycle.request_delete(admin, 'file', engine)
    assert new.id != job.id
    monkeypatch.setattr(storage_service, 'delete_file', lambda key: True)
    assert jobs.run_once(engine=engine).state == 'completed'


def test_attachment_waiting_for_cleanup_cannot_commit(setup, monkeypatch):
    engine = setup
    entered, release = Event(), Event()
    original = file_lifecycle.referenced
    def paused(session, key):
        entered.set()
        assert release.wait(5)
        return original(session, key)
    monkeypatch.setattr(file_lifecycle, 'referenced', paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        cleanup = pool.submit(file_lifecycle.request_delete, admin, 'file', engine)
        assert entered.wait(5)
        attachment = pool.submit(memory.add_memory, 'racing', file_keys=['file'])
        release.set()
        assert cleanup.result(timeout=10).state == 'queued'
        with pytest.raises(HTTPException) as err:
            attachment.result(timeout=10)
        assert err.value.status_code == 409


def test_update_rollback_and_orphan_reference(setup):
    from gigamind.db.database import MemoryItem
    engine = setup
    item = memory.add_memory('original', file_keys=['old'])
    file_lifecycle.request_delete(admin, 'forgotten', engine)
    with pytest.raises(HTTPException) as err:
        memory.update_memory(item['id'], content='changed', attachments=[{'key': 'forgotten'}])
    assert err.value.status_code == 409
    with Session(engine) as session:
        saved = session.get(MemoryItem, item['id'])
        assert saved.content == 'original'
        assert 'old' in saved.attachments_json
        session.add(MemoryItem(id='orphan', content='chunk', parent_id='missing', attachments_json='[{"key":"orphan-file"}]', created_at='now', last_accessed='now'))
        session.commit()
    with pytest.raises(HTTPException) as err:
        file_lifecycle.request_delete(admin, 'orphan-file', engine)
    assert err.value.status_code == 409


def test_worker_refuses_new_reference(setup, monkeypatch):
    from gigamind.db.database import MemoryItem
    engine = setup
    deleted = []
    monkeypatch.setattr(storage_service, 'delete_file', lambda key: deleted.append(key) or True)
    file_lifecycle.request_delete(admin, 'file', engine)
    with Session(engine) as session:
        session.add(MemoryItem(id='legacy', content='legacy', media_url='file', created_at='now', last_accessed='now'))
        session.commit()
    assert jobs.run_once(engine=engine).state == 'failed'
    assert not deleted
