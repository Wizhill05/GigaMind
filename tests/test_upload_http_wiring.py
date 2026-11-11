import base64

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

from gigamind.main import app
from gigamind.services import jobs, indexing
from gigamind.services.storage import storage_service


def test_upload_and_recovery(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'uploads.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(
        jobs, "resolve_engine", lambda engine=None: engine or globals_engine
    )
    globals_engine = engine
    monkeypatch.setattr(indexing, "engine", engine)
    objects = {}
    monkeypatch.setattr(storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_service, "get_bounded_object", lambda key: objects[key])
    monkeypatch.setattr(storage_service, "download_file", lambda key: objects.get(key))
    monkeypatch.setattr(
        indexing,
        "generate_embedding",
        lambda **kw: [1.0] * indexing.embedding.DEFAULT_DIM,
    )

    def put(key, data, mime):
        objects[key] = data

    monkeypatch.setattr(storage_service, "create_immutable_object", put)
    headers = {"Authorization": "Bearer offline-test-master-key"}
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/files/upload_base64",
                json={"filename": "a.txt", "content_base64": "eA=="},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/files/upload_base64",
                headers=headers,
                json={"filename": "a.txt", "content_base64": "eA==!"},
            ).status_code
            == 400
        )
        response = client.post(
            "/api/v1/files/upload",
            headers=headers,
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 202, response.text
        engine.dispose()
        assert jobs.run_once().state == "completed"

        def lost(key, data, mime):
            objects[key] = data
            raise TimeoutError()

        monkeypatch.setattr(storage_service, "create_immutable_object", lost)
        response = client.post(
            "/api/v1/files/upload_base64",
            headers=headers,
            json={
                "filename": "b.txt",
                "content_base64": base64.b64encode(b"world").decode(),
            },
        )
        assert response.status_code == 503
        ref = response.json()["detail"]
        response = client.post(
            "/api/v1/files/upload/recover",
            headers=headers,
            json={"key": ref["key"], "job_id": ref["job_id"]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["verified"] is True
        assert jobs.run_once().state == "completed"
    engine.dispose()


def test_failed_recovery_cannot_downgrade_a_new_owner(tmp_path, monkeypatch):
    import hashlib
    from sqlmodel import Session
    from gigamind.db.jobs import UploadManifest
    from gigamind.services import file_uploads

    engine = create_engine(
        f"sqlite:///{tmp_path / 'recovery-race.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(
        jobs, "resolve_engine", lambda candidate=None: candidate or engine
    )
    _, original = file_uploads.prepare_upload(
        "race.txt",
        "race.txt",
        "text/plain",
        "text",
        3,
        "admin",
        "race",
        sha256=hashlib.sha256(b"abc").hexdigest(),
    )
    assert file_uploads.begin_upload("race.txt", original["id"])
    assert file_uploads.verify_upload("race.txt", original["id"], b"abc")
    file_uploads.acknowledge_upload("race.txt", original["id"])

    def supersede_then_fail(key):
        jobs.enqueue("index_file", {"key": key})
        raise TimeoutError("remote read acknowledgement lost")

    monkeypatch.setattr(storage_service, "get_bounded_object", supersede_then_fail)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/files/upload/recover",
            headers={"Authorization": "Bearer offline-test-master-key"},
            json={"key": "race.txt", "job_id": original["id"]},
        )
        assert response.status_code == 409, response.text
    with Session(engine) as session:
        assert session.get(UploadManifest, "race.txt").state == "verified"
    assert jobs.status(original["id"]).state == "cancelled"
    engine.dispose()
