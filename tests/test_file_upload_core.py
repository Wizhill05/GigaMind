import pytest
from fastapi import HTTPException
from sqlmodel import Session, create_engine, select

from gigamind.db.database import StorageFileItem
from gigamind.db.jobs import Job, ResourceJobState
from gigamind.services import file_uploads, jobs


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'uploads.db'}")
    for model in (StorageFileItem, Job, ResourceJobState):
        model.__table__.create(engine)
    return engine


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
        prepare(engine)
    engine.dispose()
    with Session(engine) as session:
        assert session.get(Job, old.id).state == "queued"
        assert session.get(ResourceJobState, "file/a").current_job_id == old.id
        assert session.exec(select(StorageFileItem)).first() is None
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
