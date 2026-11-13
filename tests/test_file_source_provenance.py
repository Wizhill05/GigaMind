import hashlib

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from gigamind.db.database import StorageFileItem
from gigamind.db.jobs import Job, ResourceJobState, UploadManifest
from gigamind.db.source_provenance import SourceHead, SourceReceipt
from gigamind.security import Actor
from gigamind.services import file_lifecycle, file_uploads, jobs, source_provenance

CREATOR = Actor("creator", set(), None, True)
RECOVERER = Actor("recoverer", set(), None, True)


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'files.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def prepare(engine, actor=CREATOR):
    return file_uploads.prepare_upload(
        "files/a",
        "a.txt",
        "text/plain",
        "text",
        3,
        "claimed-agent",
        "idem",
        sha256=hashlib.sha256(b"abc").hexdigest(),
        actor=actor,
        engine=engine,
    )


def receipts(engine, source_id):
    with Session(engine) as session:
        return list(
            session.exec(
                select(SourceReceipt)
                .where(
                    SourceReceipt.kind == "file", SourceReceipt.source_id == source_id
                )
                .order_by(SourceReceipt.revision)
            ).all()
        )


def test_registration_recovery_and_delete_are_attributed_and_idempotent(engine):
    file, job = prepare(engine)
    assert prepare(engine, RECOVERER) == (file, job)
    assert file_uploads.begin_upload(file["key"], job["id"], engine=engine)
    assert not file_uploads.verify_upload(
        file["key"], job["id"], b"bad", actor=RECOVERER, engine=engine
    )
    assert [r.operation for r in receipts(engine, file["id"])] == ["created"]
    assert file_uploads.verify_upload(
        file["key"], job["id"], b"abc", actor=RECOVERER, engine=engine
    )
    assert file_uploads.verify_upload(
        file["key"], job["id"], b"abc", actor=CREATOR, engine=engine
    )
    delete_job = file_lifecycle.request_delete(RECOVERER, file["key"], engine)
    assert (
        file_lifecycle.request_delete(CREATOR, file["key"], engine).id == delete_job.id
    )
    rows = receipts(engine, file["id"])
    assert [(r.operation, r.writer_id) for r in rows] == [
        ("created", "creator"),
        ("verified", "recoverer"),
        ("deleted", "recoverer"),
    ]
    assert all(r.source_revision is None and r.payload_hash for r in rows)
    with Session(engine) as session:
        head = session.get(SourceHead, ("file", file["id"]))
        assert (head.creator_id, head.creator_provenance, head.active) == (
            "creator",
            "authenticated",
            False,
        )
        assert session.get(StorageFileItem, file["id"]) is None


def test_receipt_failure_rolls_back_registration_and_delete(engine, monkeypatch):
    original = source_provenance.record_write

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("receipt failure")

    monkeypatch.setattr(source_provenance, "record_write", fail)
    with pytest.raises(RuntimeError):
        prepare(engine)
    engine.dispose()
    with Session(engine) as session:
        assert session.exec(select(StorageFileItem)).all() == []
        assert session.exec(select(Job)).all() == []
        assert session.exec(select(SourceReceipt)).all() == []
        assert session.get(ResourceJobState, "files/a") is None
    monkeypatch.setattr(source_provenance, "record_write", original)
    file, _ = prepare(engine)
    monkeypatch.setattr(source_provenance, "record_write", fail)
    with pytest.raises(RuntimeError):
        file_lifecycle.request_delete(CREATOR, file["key"], engine)
    engine.dispose()
    with Session(engine) as session:
        assert session.get(StorageFileItem, file["id"]) is not None
        assert not session.get(ResourceJobState, file["key"]).deleted
        assert len(session.exec(select(SourceReceipt)).all()) == 1


def test_legacy_deletion_has_unknown_creator_and_gc_adds_no_receipt(
    engine, monkeypatch
):
    from gigamind.services.storage import storage_service

    with Session(engine) as session:
        session.add(
            StorageFileItem(
                id="legacy-id",
                key="legacy",
                filename="old",
                mime_type="text/plain",
                multimodal_type="text",
                size_bytes=3,
                source_agent="claimed",
                indexing_status="pending",
                created_at="now",
                updated_at="now",
            )
        )
        session.commit()
    file_lifecycle.request_delete(RECOVERER, "legacy", engine)
    with Session(engine) as session:
        head = session.get(SourceHead, ("file", "legacy-id"))
        assert (head.creator_id, head.creator_provenance) == (None, "legacy_unknown")
    monkeypatch.setattr(storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_service, "delete_file", lambda key: True)
    assert jobs.run_once(engine=engine).state == "completed"
    assert [(r.operation, r.writer_id) for r in receipts(engine, "legacy-id")] == [
        ("deleted", "recoverer")
    ]


def test_invalid_actor_cannot_mutate(engine):
    with pytest.raises(PermissionError):
        prepare(engine, Actor("no", set(), None, False))
    with Session(engine) as session:
        assert session.exec(select(Job)).all() == []


def test_http_upload_recovery_and_delete_use_authenticated_actor(engine, monkeypatch):
    from gigamind.main import app
    from gigamind.services.storage import storage_service

    monkeypatch.setattr(
        jobs, "resolve_engine", lambda candidate=None: candidate or engine
    )
    monkeypatch.setattr(storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        storage_service, "generate_storage_key", lambda *args: "files/http"
    )
    monkeypatch.setattr(storage_service, "create_immutable_object", lambda *args: None)
    monkeypatch.setattr(storage_service, "get_bounded_object", lambda key: b"abc")
    admin = {"Authorization": "Bearer offline-test-master-key"}
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/files/upload_base64",
                json={"filename": "a.txt", "content_base64": "YWJj"},
            ).status_code
            == 401
        )
        response = client.post(
            "/api/v1/files/upload_base64",
            headers=admin,
            json={"filename": "a.txt", "content_base64": "YWJj"},
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert (
            client.post(
                "/api/v1/files/upload/recover",
                headers=admin,
                json={"key": "files/http", "job_id": body["job_id"]},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/files/delete", headers=admin, json={"key": "files/http"}
            ).status_code
            == 202
        )
        assert (
            client.delete("/api/v1/files/files/http", headers=admin).status_code == 202
        )
    assert [
        (r.operation, r.writer_id) for r in receipts(engine, body["file"]["id"])
    ] == [("created", "master"), ("verified", "master"), ("deleted", "master")]


def test_http_recovery_attributes_verification_to_recoverer(engine, monkeypatch):
    from gigamind.main import app
    from gigamind.services.storage import storage_service

    file, job = prepare(engine)
    assert file_uploads.begin_upload(file["key"], job["id"], engine=engine)
    file_uploads.record_unknown(file["key"], job["id"], engine=engine)
    monkeypatch.setattr(
        jobs, "resolve_engine", lambda candidate=None: candidate or engine
    )
    monkeypatch.setattr(storage_service, "get_bounded_object", lambda key: b"abc")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/files/upload/recover",
            headers={"Authorization": "Bearer offline-test-master-key"},
            json={"key": file["key"], "job_id": job["id"]},
        )
        assert response.status_code == 200, response.text
    assert [(r.operation, r.writer_id) for r in receipts(engine, file["id"])] == [
        ("created", "creator"),
        ("verified", "master"),
    ]


def test_failed_verification_receipt_rolls_back_manifest(engine, monkeypatch):
    file, job = prepare(engine)
    assert file_uploads.begin_upload(file["key"], job["id"], engine=engine)
    original = source_provenance.record_write

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("receipt failure")

    monkeypatch.setattr(source_provenance, "record_write", fail)
    with pytest.raises(RuntimeError):
        file_uploads.verify_upload(
            file["key"], job["id"], b"abc", actor=RECOVERER, engine=engine
        )
    engine.dispose()
    with Session(engine) as session:
        assert session.get(UploadManifest, file["key"]).state == "inflight"
    assert [r.operation for r in receipts(engine, file["id"])] == ["created"]


def test_legacy_recovery_does_not_invent_creator(engine):
    file, job = prepare(engine)
    assert file_uploads.begin_upload(file["key"], job["id"], engine=engine)
    with Session(engine) as session:
        session.delete(session.get(SourceReceipt, ("file", file["id"], 1)))
        session.delete(session.get(SourceHead, ("file", file["id"])))
        session.commit()
    assert file_uploads.verify_upload(
        file["key"], job["id"], b"abc", actor=RECOVERER, engine=engine
    )
    with Session(engine) as session:
        head = session.get(SourceHead, ("file", file["id"]))
        assert (head.creator_id, head.creator_provenance) == (None, "legacy_unknown")
    assert [(r.operation, r.writer_id) for r in receipts(engine, file["id"])] == [
        ("verified", "recoverer")
    ]


def test_http_history_requires_admin_and_survives_delete(engine, monkeypatch):
    from gigamind import security
    from gigamind.main import app
    from gigamind.services import memory

    monkeypatch.setattr(security, "engine", engine)
    monkeypatch.setattr(memory, "engine", engine)
    _, reader_token = security.create_client("reader", ["memory:read"], ["project"])
    file, job = prepare(engine)
    assert file_uploads.begin_upload(file["key"], job["id"], engine=engine)
    assert file_uploads.verify_upload(
        file["key"], job["id"], b"abc", actor=RECOVERER, engine=engine
    )
    file_lifecycle.request_delete(RECOVERER, file["key"], engine)
    with Session(engine) as session:
        session.add(
            StorageFileItem(
                id="legacy-http",
                key="legacy-http-key",
                filename="legacy.txt",
                mime_type="text/plain",
                multimodal_type="text",
                size_bytes=3,
                source_agent="claimed-agent",
                indexing_status="pending",
                created_at="now",
                updated_at="now",
            )
        )
        session.commit()
    path = f"/api/v1/sources/file/{file['id']}/provenance"
    admin = {"Authorization": "Bearer offline-test-master-key"}
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        assert (
            client.get(
                path, headers={"Authorization": f"Bearer {reader_token}"}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/v1/sources/file/missing/provenance", headers=admin
            ).status_code
            == 404
        )
        legacy = client.get(
            "/api/v1/sources/file/legacy-http/provenance", headers=admin
        )
        assert legacy.status_code == 200
        assert legacy.json()["head"]["creator_provenance"] == "legacy_unknown"
        assert legacy.json()["receipts"] == []
        response = client.get(path, headers=admin)
        assert response.status_code == 200, response.text
        history = response.json()
        assert history["head"]["creator_id"] == "creator"
        assert history["head"]["creator_provenance"] == "authenticated"
        assert history["head"]["active"] is False
        assert [
            (r["operation"], r["writer_id"], r["writer_provenance"])
            for r in history["receipts"]
        ] == [
            ("deleted", "recoverer", "authenticated"),
            ("verified", "recoverer", "authenticated"),
            ("created", "creator", "authenticated"),
        ]
        assert "claimed-agent" not in response.text
        assert '"abc"' not in response.text
    with Session(engine) as session:
        assert session.get(SourceHead, ("file", "legacy-http")) is None


def test_concurrent_verifications_append_one_receipt(engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    file, job = prepare(engine)
    assert file_uploads.begin_upload(file["key"], job["id"], engine=engine)
    start = Barrier(2)

    def verify(actor):
        start.wait(timeout=5)
        return file_uploads.verify_upload(
            file["key"], job["id"], b"abc", actor=actor, engine=engine
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(verify, actor) for actor in (CREATOR, RECOVERER)]
        assert all(result.result(timeout=10) for result in results)
    rows = receipts(engine, file["id"])
    assert [row.operation for row in rows] == ["created", "verified"]
    assert rows[-1].writer_id in {"creator", "recoverer"}


@pytest.mark.parametrize("first", ["registration", "deletion"])
def test_registration_and_deletion_order_is_atomic(engine, monkeypatch, first):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread

    locked, release, attempted = Event(), Event(), Event()
    original_lock = jobs.lock_resource
    original_source_lock = source_provenance.lock_sources

    def observe_source_lock(session):
        if current_thread().name == "contender":
            attempted.set()
        return original_source_lock(session)

    def pause_after_resource_lock(session, key, now):
        owner = original_lock(session, key, now)
        if current_thread().name == "first":
            locked.set()
            assert release.wait(10)
        return owner

    monkeypatch.setattr(source_provenance, "lock_sources", observe_source_lock)
    monkeypatch.setattr(jobs, "lock_resource", pause_after_resource_lock)

    def register(name):
        current_thread().name = name
        return prepare(engine)

    def delete(name):
        current_thread().name = name
        return file_lifecycle.request_delete(RECOVERER, "files/a", engine)

    with ThreadPoolExecutor(max_workers=2) as pool:
        initial = pool.submit(register if first == "registration" else delete, "first")
        assert locked.wait(5)
        contender = pool.submit(
            delete if first == "registration" else register, "contender"
        )
        try:
            assert attempted.wait(5)
            assert not contender.done()
        finally:
            release.set()
        first_result = initial.result(timeout=10)
        if first == "registration":
            contender.result(timeout=10)
            file, _ = first_result
            assert [r.operation for r in receipts(engine, file["id"])] == [
                "created",
                "deleted",
            ]
        else:
            with pytest.raises(HTTPException) as rejected:
                contender.result(timeout=10)
            assert rejected.value.status_code == 409
            with Session(engine) as session:
                assert session.exec(select(StorageFileItem)).all() == []
                assert session.exec(select(SourceReceipt)).all() == []
