from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine, select

from gigamind.db.database import StorageFileItem
from gigamind.security import Actor
from gigamind.services import file_lifecycle, jobs, memory
from gigamind.services.storage import storage_service


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"timeout": 10, "check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(memory, "engine", engine)
    monkeypatch.setattr(memory, "is_postgres", False)
    monkeypatch.setattr(memory.embedding_config, "DEFAULT_DIM", 3)
    monkeypatch.setattr(
        memory, "generate_embedding", lambda *args, **kwargs: [1.0, 2.0, 3.0]
    )
    monkeypatch.setattr(storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        storage_service, "get_presigned_download_url", lambda *args, **kwargs: None
    )
    yield engine
    engine.dispose()


admin = Actor("admin", set(), None, True)


def test_shared_references_and_worker(setup, monkeypatch):
    engine = setup
    deleted = []
    monkeypatch.setattr(
        storage_service, "delete_file", lambda key: deleted.append(key) or True
    )
    a = memory.add_memory("first", file_keys=["file"])
    b = memory.add_memory("second", file_keys=["file"])
    for actor in (None, {"is_admin": True}, Actor("user", set(), None)):
        with pytest.raises(HTTPException) as err:
            file_lifecycle.request_delete(actor, "file", engine)
        assert err.value.status_code == 403
    with pytest.raises(HTTPException) as err:
        file_lifecycle.request_delete(admin, "file", engine)
    assert err.value.status_code == 409
    with Session(engine) as session:
        assert session.exec(select(StorageFileItem)).first()
    memory.delete_memory(a["id"])
    with pytest.raises(HTTPException):
        file_lifecycle.request_delete(admin, "file", engine)
    memory.delete_memory(b["id"])
    job = file_lifecycle.request_delete(admin, "file", engine)
    assert deleted == []
    assert file_lifecycle.request_delete(admin, "file", engine).id == job.id
    assert jobs.run_once(engine=engine).state == "completed"
    assert deleted == ["file"]
    with pytest.raises(HTTPException):
        memory.add_memory("later", file_keys=["file"])
    assert file_lifecycle.request_delete(admin, "file", engine).id == job.id


def test_failed_cleanup_can_retry(setup, monkeypatch):
    engine = setup
    monkeypatch.setattr(storage_service, "delete_file", lambda key: False)
    job = file_lifecycle.request_delete(admin, "file", engine)
    with Session(engine) as session:
        row = session.get(jobs.Job, job.id)
        row.max_attempts = 1
        session.add(row)
        session.commit()
    assert jobs.run_once(engine=engine).state == "failed"
    new = file_lifecycle.request_delete(admin, "file", engine)
    assert new.id != job.id
    monkeypatch.setattr(storage_service, "delete_file", lambda key: True)
    assert jobs.run_once(engine=engine).state == "completed"


def test_attachment_waiting_for_cleanup_cannot_commit(setup, monkeypatch):
    engine = setup
    entered, release = Event(), Event()
    original = file_lifecycle.referenced

    def paused(session, key):
        entered.set()
        assert release.wait(5)
        return original(session, key)

    monkeypatch.setattr(file_lifecycle, "referenced", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        cleanup = pool.submit(file_lifecycle.request_delete, admin, "file", engine)
        assert entered.wait(5)
        attachment = pool.submit(memory.add_memory, "racing", file_keys=["file"])
        release.set()
        assert cleanup.result(timeout=10).state == "queued"
        with pytest.raises(HTTPException) as err:
            attachment.result(timeout=10)
        assert err.value.status_code == 409


def test_update_rollback_and_orphan_reference(setup):
    from gigamind.db.database import MemoryItem

    engine = setup
    item = memory.add_memory("original", file_keys=["old"])
    file_lifecycle.request_delete(admin, "forgotten", engine)
    with pytest.raises(HTTPException) as err:
        memory.update_memory(
            item["id"], content="changed", attachments=[{"key": "forgotten"}]
        )
    assert err.value.status_code == 409
    with Session(engine) as session:
        saved = session.get(MemoryItem, item["id"])
        assert saved.content == "original"
        assert "old" in saved.attachments_json
        session.add(
            MemoryItem(
                id="orphan",
                content="chunk",
                parent_id="missing",
                attachments_json='[{"key":"orphan-file"}]',
                created_at="now",
                last_accessed="now",
            )
        )
        session.commit()
    with pytest.raises(HTTPException) as err:
        file_lifecycle.request_delete(admin, "orphan-file", engine)
    assert err.value.status_code == 409


def test_worker_refuses_new_reference(setup, monkeypatch):
    from gigamind.db.database import MemoryItem

    engine = setup
    deleted = []
    monkeypatch.setattr(
        storage_service, "delete_file", lambda key: deleted.append(key) or True
    )
    file_lifecycle.request_delete(admin, "file", engine)
    with Session(engine) as session:
        session.add(
            MemoryItem(
                id="legacy",
                content="legacy",
                media_url="file",
                created_at="now",
                last_accessed="now",
            )
        )
        session.commit()
    assert jobs.run_once(engine=engine).state == "failed"
    assert not deleted


def test_storage_io_does_not_block_real_heartbeat(setup, monkeypatch):
    renewed = Event()
    original = jobs.heartbeat

    def heartbeat(*args, **kwargs):
        result = original(*args, **kwargs)
        if result:
            renewed.set()
        return result

    monkeypatch.setattr(jobs, "heartbeat", heartbeat)

    def remove(key):
        assert renewed.wait(5), "storage I/O blocked lease renewal"
        return True

    monkeypatch.setattr(storage_service, "delete_file", remove)
    file_lifecycle.request_delete(admin, "file", setup)
    assert jobs.run_once(engine=setup, lease_seconds=1).state == "completed"


def test_missing_object_reclaim_and_persistent_intent(setup, monkeypatch):
    from datetime import timedelta

    calls = []
    objects = {"file": b"bytes"}

    def remove(key):
        calls.append(key)
        objects.pop(key, None)
        return True

    monkeypatch.setattr(storage_service, "delete_file", remove)
    requested = file_lifecycle.request_delete(admin, "file", setup)
    now = [jobs.utcnow() + timedelta(seconds=1)]
    clock = lambda: now[0]
    first = jobs.claim(engine=setup, clock=clock, lease_seconds=1)
    first_lease = jobs.JobLease(first.id, first.lease_token, clock, setup)
    assert file_lifecycle.cleanup_file("file", first_lease) == {"deleted": True}
    # The first worker disappears after storage acknowledged deletion.
    now[0] += timedelta(seconds=2)
    second = jobs.claim(engine=setup, clock=clock, lease_seconds=1)
    with pytest.raises(jobs.PermanentFailure):
        file_lifecycle.cleanup_file("file", first_lease)
    assert calls == ["file"]
    second_lease = jobs.JobLease(second.id, second.lease_token, clock, setup)
    assert file_lifecycle.cleanup_file("file", second_lease) == {"deleted": True}
    assert calls == ["file", "file"] and not objects
    assert not jobs.guarded(
        first.id, first.lease_token, {"state": "completed"}, engine=setup, clock=clock
    )
    assert jobs.guarded(
        second.id, second.lease_token, {"state": "completed"}, engine=setup, clock=clock
    )
    setup.dispose()
    assert file_lifecycle.request_delete(admin, "file", setup).id == requested.id
    with pytest.raises(HTTPException) as denied:
        memory.add_memory("must not recreate reference", file_keys=["file"])
    assert denied.value.status_code == 409


def test_attachment_committing_first_blocks_cleanup(setup, monkeypatch):
    registered, release, delete_attempted = Event(), Event(), Event()
    register = memory._register_attachment_metadata
    lock_resource = jobs.lock_resource

    def register_and_pause(*args, **kwargs):
        register(*args, **kwargs)
        registered.set()
        assert release.wait(5)

    def observed_lock(*args, **kwargs):
        if registered.is_set() and not release.is_set():
            delete_attempted.set()
        return lock_resource(*args, **kwargs)

    monkeypatch.setattr(memory, "_register_attachment_metadata", register_and_pause)
    monkeypatch.setattr(jobs, "lock_resource", observed_lock)
    with ThreadPoolExecutor(2) as pool:
        attached = pool.submit(memory.add_memory, "source", file_keys=["file"])
        assert registered.wait(5)
        cleanup = pool.submit(file_lifecycle.request_delete, admin, "file", setup)
        try:
            assert delete_attempted.wait(5)
        finally:
            release.set()
        saved = attached.result(timeout=10)
        with pytest.raises(HTTPException) as rejected:
            cleanup.result(timeout=10)
        assert rejected.value.status_code == 409
    from gigamind.db.database import MemoryItem

    with Session(setup) as session:
        assert session.get(MemoryItem, saved["id"]) is not None
        assert not session.exec(select(jobs.Job)).all()
