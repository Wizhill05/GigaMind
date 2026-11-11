from datetime import datetime
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlmodel import Session, create_engine, select

from gigamind.db.database import StorageFileItem
from gigamind.db.jobs import Job, ResourceJobState, UploadManifest
from gigamind.services import file_uploads, jobs


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'uploads.db'}")
    for model in (StorageFileItem, Job, ResourceJobState, UploadManifest):
        model.__table__.create(engine)
    yield engine
    engine.dispose()


def prepare(engine, **overrides):
    args = dict(
        key="file/a",
        filename="a.txt",
        mime_type="text/plain",
        multimodal_type="text",
        size_bytes=3,
        source_agent="user",
        idempotency_key="upload-1",
    )
    args.update(overrides)
    return file_uploads.prepare_upload(**args, engine=engine)


def test_persistence_repeat_and_acknowledgement(engine):
    file, job = prepare(engine)
    engine.dispose()
    with Session(engine) as session:
        assert session.get(StorageFileItem, file["id"]).indexing_status == "pending"
        assert session.get(ResourceJobState, "file/a").current_job_id == job["id"]
    assert jobs.claim(engine=engine) is None
    assert prepare(engine) == (file, job)
    with pytest.raises(jobs.Conflict):
        prepare(engine, filename="different")
    with pytest.raises(jobs.Conflict):
        prepare(engine, idempotency_key="different")
    file_uploads.acknowledge_upload("file/a", job["id"], engine=engine)
    assert jobs.claim(engine=engine).id == job["id"]


def test_rollback_restores_owner_and_cancellation(engine, monkeypatch):
    old = jobs.enqueue("index_file", {"key": "file/a"}, engine=engine)
    original = jobs.enqueue_in_session

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected")

    monkeypatch.setattr(jobs, "enqueue_in_session", fail)
    with pytest.raises(RuntimeError):
        prepare(engine)
    engine.dispose()
    with Session(engine) as session:
        assert session.get(Job, old.id).state == "queued"
        assert session.get(ResourceJobState, "file/a").current_job_id == old.id
        assert session.exec(select(StorageFileItem)).first() is None
        assert len(session.exec(select(Job)).all()) == 1


def test_tombstone(engine):
    jobs.forget_resource("file/a", engine=engine)
    with pytest.raises(HTTPException) as exc:
        prepare(engine)
    assert exc.value.status_code == 409


def test_failure_after_metadata_is_added_rolls_back(engine, monkeypatch):
    old = jobs.enqueue("index_file", {"key": "file/a"}, engine=engine)
    original = Session.commit

    def fail_commit(session):
        if any(isinstance(item, StorageFileItem) for item in session.new):
            session.flush()
            raise RuntimeError("injected after metadata flush")
        return original(session)

    monkeypatch.setattr(Session, "commit", fail_commit)
    with pytest.raises(RuntimeError):
        prepare(engine, sha256=hashlib.sha256(b"abc").hexdigest())
    engine.dispose()
    with Session(engine) as session:
        assert session.get(Job, old.id).state == "queued"
        assert session.get(ResourceJobState, "file/a").current_job_id == old.id
        assert session.exec(select(StorageFileItem)).first() is None
        assert session.exec(select(UploadManifest)).first() is None
        assert len(session.exec(select(Job)).all()) == 1


def test_existing_index_is_not_replaced(engine):
    file, job = prepare(engine)
    with Session(engine) as session:
        record = session.get(StorageFileItem, file["id"])
        record.indexing_status = "completed"
        record.document_summary = "accepted content"
        record.total_chunks = 7
        session.commit()
    with pytest.raises(jobs.Conflict):
        prepare(engine, filename="replacement.txt")
    with Session(engine) as session:
        record = session.get(StorageFileItem, file["id"])
        assert (record.filename, record.document_summary, record.total_chunks) == (
            "a.txt",
            "accepted content",
            7,
        )
        assert session.get(ResourceJobState, "file/a").current_job_id == job["id"]


def test_acknowledgement_is_idempotent_without_resetting_a_lease(engine):
    file, job = prepare(engine)
    first = file_uploads.acknowledge_upload("file/a", job["id"], engine=engine)
    assert file_uploads.acknowledge_upload("file/a", job["id"], engine=engine) == first
    claimed = jobs.claim(engine=engine)
    running = file_uploads.acknowledge_upload("file/a", job["id"], engine=engine)
    assert running["state"] == "running" and "lease_token" not in running
    assert jobs.status(job["id"], engine=engine).lease_token == claimed.lease_token
    assert jobs.guarded(
        job["id"], claimed.lease_token, {"state": "completed"}, engine=engine
    )
    assert (
        file_uploads.acknowledge_upload("file/a", job["id"], engine=engine)["state"]
        == "completed"
    )


@pytest.mark.parametrize("action", ["cancel", "supersede", "forget"])
def test_acknowledgement_cannot_revive_old_or_forgotten_work(engine, action):
    file, job = prepare(engine)
    if action == "cancel":
        jobs.cancel(job["id"], engine=engine)
    elif action == "supersede":
        jobs.enqueue("index_file", {"key": "file/a"}, engine=engine)
    else:
        jobs.forget_resource("file/a", engine=engine)
    with pytest.raises((jobs.Conflict, HTTPException)):
        file_uploads.acknowledge_upload("file/a", job["id"], engine=engine)
    assert jobs.status(job["id"], engine=engine).state == "cancelled"


@pytest.mark.parametrize("value", ["tomorrow", 1, datetime(2026, 1, 1)])
def test_invalid_schedule_rolls_back_before_queue_mutation(engine, value):
    with Session(engine) as session:
        with pytest.raises(ValueError, match="timezone-aware"):
            jobs.enqueue_in_session(
                session, "index_file", {"key": "file/a"}, not_before=value
            )
    with Session(engine) as session:
        assert session.exec(select(Job)).all() == []
        assert session.exec(select(ResourceJobState)).all() == []


def test_manifest_admission_and_recovery(engine):
    digest = hashlib.sha256(b"abc").hexdigest()
    _, job = prepare(engine, sha256=digest)
    engine.dispose()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: file_uploads.begin_upload("file/a", job["id"], engine=engine), range(2)))
    assert sorted(results) == [False, True]
    file_uploads.record_unknown("file/a", job["id"], engine=engine)
    for data in (None, b"ab", b"xyz"):
        assert not file_uploads.verify_upload("file/a", job["id"], data, engine=engine)
        with pytest.raises(jobs.Conflict):
            file_uploads.acknowledge_upload("file/a", job["id"], engine=engine)
    assert file_uploads.verify_upload("file/a", job["id"], b"abc", engine=engine)
    file_uploads.acknowledge_upload("file/a", job["id"], engine=engine)
    claimed = jobs.claim(engine=engine)
    file_uploads.acknowledge_upload("file/a", job["id"], engine=engine)
    assert jobs.status(job["id"], engine=engine).lease_token == claimed.lease_token


def test_cancelled_manifest_cannot_restart(engine):
    _, job = prepare(engine, sha256=hashlib.sha256(b"abc").hexdigest())
    assert file_uploads.begin_upload("file/a", job["id"], engine=engine)
    jobs.cancel(job["id"], engine=engine)
    assert file_uploads.verify_upload("file/a", job["id"], b"abc", engine=engine)
    with pytest.raises(jobs.Conflict):
        file_uploads.acknowledge_upload("file/a", job["id"], engine=engine)
    assert not file_uploads.begin_upload("file/a", job["id"], engine=engine)
