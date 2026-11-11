"""Real job handler and indexing transactions with provider/storage boundaries stubbed."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from gigamind.db.database import StorageChunkItem, StorageFileItem
from gigamind.services import indexing, jobs


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pipeline.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(indexing, "engine", engine)
    monkeypatch.setattr(indexing, "is_postgres", False)
    monkeypatch.setattr(indexing.embedding, "DEFAULT_DIM", 3)
    monkeypatch.setattr(indexing, "generate_embedding", lambda **kw: [1.0, 2.0, 3.0])
    monkeypatch.setattr(indexing.storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        indexing.storage_service, "download_file", lambda key: b"new source"
    )
    yield engine
    engine.dispose()


def test_actual_handler_persists_completed_index(pipeline):
    job = jobs.enqueue("index_file", {"key": "files/source.txt"}, engine=pipeline)
    result = jobs.run_once(engine=pipeline)
    assert result.id == job.id and result.state == "completed"
    with Session(pipeline) as session:
        file = session.exec(select(StorageFileItem)).one()
        chunk = session.exec(select(StorageChunkItem)).one()
        assert file.indexing_status == "completed" and file.total_chunks == 1
        assert chunk.file_id == file.id and chunk.content == "new source"


def test_cancel_then_delete_cannot_be_resurrected(pipeline, monkeypatch):
    key = "files/source.txt"
    indexing.index_file_content(key, "source.txt", b"old source")
    entered, release = Event(), Event()

    def embedding(**kwargs):
        entered.set()
        assert release.wait(5), "test did not release embedding"
        return [1.0, 2.0, 3.0]

    monkeypatch.setattr(indexing, "generate_embedding", embedding)
    job = jobs.enqueue("index_file", {"key": key}, engine=pipeline)
    with ThreadPoolExecutor(1) as executor:
        future = executor.submit(jobs.run_once, engine=pipeline)
        try:
            assert entered.wait(5), "handler did not reach provider"
            assert jobs.cancel_resource(key, engine=pipeline) == 1
            assert indexing.delete_storage_file_index(key)
        finally:
            release.set()
        assert future.result(timeout=5).state == "cancelled"
    assert jobs.status(job.id, engine=pipeline).state == "cancelled"
    with Session(pipeline) as session:
        assert session.exec(select(StorageFileItem)).all() == []
        assert session.exec(select(StorageChunkItem)).all() == []


def test_reclaimed_lease_cannot_publish_or_complete_new_owner(pipeline, monkeypatch):
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    clock = lambda: now[0]
    entered, release = Event(), Event()

    def embedding(**kwargs):
        entered.set()
        assert release.wait(5), "test did not release embedding"
        return [1.0, 2.0, 3.0]

    monkeypatch.setattr(indexing, "generate_embedding", embedding)
    job = jobs.enqueue(
        "index_file", {"key": "files/source.txt"}, engine=pipeline, clock=clock
    )
    with ThreadPoolExecutor(1) as executor:
        future = executor.submit(
            jobs.run_once, engine=pipeline, clock=clock, lease_seconds=10
        )
        try:
            assert entered.wait(5), "handler did not reach provider"
            now[0] += timedelta(seconds=11)
            replacement = jobs.claim(engine=pipeline, clock=clock)
            assert replacement and replacement.attempts == 2
        finally:
            release.set()
        old_result = future.result(timeout=5)
    assert (
        old_result.state == "running"
        and old_result.lease_token == replacement.lease_token
    )
    with Session(pipeline) as session:
        assert session.exec(select(StorageFileItem)).all() == []
        assert session.exec(select(StorageChunkItem)).all() == []
    lease = jobs.JobLease(job.id, replacement.lease_token, clock)
    assert jobs.index_file({"key": "files/source.txt"}, lease)["status"] == "completed"
    assert jobs.guarded(
        job.id,
        replacement.lease_token,
        {"state": "completed"},
        engine=pipeline,
        clock=clock,
    )
