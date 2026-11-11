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


def test_http_validation_and_registration_failures(tmp_path, monkeypatch):
    from gigamind.services import file_uploads

    engine = create_engine(f"sqlite:///{tmp_path / 'validation.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(jobs, "resolve_engine", lambda candidate=None: candidate or engine)
    monkeypatch.setattr(storage_service, "is_enabled", lambda: True)
    calls = []
    monkeypatch.setattr(storage_service, "create_immutable_object", lambda *args: calls.append(args))
    headers = {"Authorization": "Bearer offline-test-master-key"}
    with TestClient(app) as client:
        endpoint = "/api/v1/files/upload_base64"
        for body, suffix, expected in [
            ({"filename": "a.txt", "content_base64": "eA==!"}, "", 400),
            ({"filename": "", "content_base64": "eA=="}, "", 422),
            ({"filename": "a.txt", "content_base64": "eA==", "mime_type": "bad mime"}, "", 422),
            ({"filename": "a.txt", "content_base64": "eA=="}, "?prefix=bad%20prefix", 422),
        ]:
            assert client.post(endpoint + suffix, headers=headers, json=body).status_code == expected
        assert client.post('/api/v1/files/upload/recover', json={"key": "x", "job_id": "x"}).status_code == 401
        def fail(*args, **kwargs):
            raise RuntimeError("sensitive database detail")
        monkeypatch.setattr(file_uploads, "prepare_upload", fail)
        response = client.post(endpoint, headers=headers, json={"filename": "a.txt", "content_base64": "eA=="})
        assert response.status_code == 503
        assert "sensitive" not in response.text
        assert not calls
    engine.dispose()


def test_admission_failure_preserves_reference_without_put(tmp_path, monkeypatch):
    from gigamind.services import file_uploads
    from gigamind.db.jobs import UploadManifest
    from sqlmodel import Session

    engine = create_engine(f"sqlite:///{tmp_path / 'admission.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(jobs, "resolve_engine", lambda candidate=None: candidate or engine)
    monkeypatch.setattr(storage_service, "is_enabled", lambda: True)
    puts = []
    monkeypatch.setattr(storage_service, "create_immutable_object", lambda *args: puts.append(args))
    def fail(*args):
        raise RuntimeError("private detail")
    monkeypatch.setattr(file_uploads, "begin_upload", fail)
    with TestClient(app) as client:
        response = client.post('/api/v1/files/upload_base64', headers={"Authorization": "Bearer offline-test-master-key"}, json={"filename": "a.txt", "content_base64": "eA=="})
        assert response.status_code == 503
        assert 'private detail' not in response.text
        ref = response.json()['detail']
        with Session(engine) as session:
            assert session.get(UploadManifest, ref['key']).job_id == ref['job_id']
        assert not puts
    engine.dispose()


def test_http_recovery_mismatch_and_cancelled(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'recover.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(jobs, "resolve_engine", lambda candidate=None: candidate or engine)
    monkeypatch.setattr(storage_service, "is_enabled", lambda: True)
    puts = []
    def lost(key, data, mime):
        puts.append((key, data))
        raise TimeoutError()
    monkeypatch.setattr(storage_service, "create_immutable_object", lost)
    headers = {"Authorization": "Bearer offline-test-master-key"}
    with TestClient(app) as client:
        response = client.post('/api/v1/files/upload_base64', headers=headers, json={"filename": "a.txt", "content_base64": "eA=="})
        assert response.status_code == 503
        ref = response.json()['detail']
        request = {"key": ref['key'], "job_id": ref['job_id']}
        monkeypatch.setattr(storage_service, "get_bounded_object", lambda key: b"wrong")
        assert client.post('/api/v1/files/upload/recover', headers=headers, json=request).status_code == 409
        monkeypatch.setattr(storage_service, "get_bounded_object", lambda key: None)
        assert client.post('/api/v1/files/upload/recover', headers=headers, json=request).status_code == 409
        jobs.cancel(ref['job_id'])
        monkeypatch.setattr(storage_service, "get_bounded_object", lambda key: b"x")
        response = client.post('/api/v1/files/upload/recover', headers=headers, json=request)
        assert response.status_code == 200, response.text
        assert response.json()['state'] == 'cancelled'
        assert len(puts) == 1
    engine.dispose()


def test_multipart_limit_reads_bounded_and_closes(tmp_path, monkeypatch):
    from starlette.datastructures import UploadFile
    from gigamind.services import upload_http

    engine = create_engine(f"sqlite:///{tmp_path / 'limit.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(jobs, "resolve_engine", lambda candidate=None: candidate or engine)
    monkeypatch.setattr(storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(upload_http, "LIMIT", 20)
    reads, closes, objects = [], [], {}
    original_read, original_close = UploadFile.read, UploadFile.close

    async def read(file, size=-1):
        reads.append(size)
        return await original_read(file, size)

    async def close(file):
        closes.append(file.filename)
        return await original_close(file)

    monkeypatch.setattr(UploadFile, "read", read)
    monkeypatch.setattr(UploadFile, "close", close)
    monkeypatch.setattr(storage_service, "create_immutable_object", lambda key, data, mime: objects.update({key: data}))
    monkeypatch.setattr(storage_service, "get_bounded_object", lambda key: objects[key])
    headers = {"Authorization": "Bearer offline-test-master-key"}
    with TestClient(app) as client:
        assert client.post('/api/v1/files/upload', headers=headers, files={'file': ('ok.txt', b'x' * 20, 'text/plain')}).status_code == 202
        assert client.post('/api/v1/files/upload', headers=headers, files={'file': ('large.txt', b'x' * 21, 'text/plain')}).status_code == 413
    assert reads == [21, 21]
    assert set(closes) == {'ok.txt', 'large.txt'}
    assert len(objects) == 1
    engine.dispose()


def test_stale_recovery_does_not_read_storage(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'stale.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(jobs, "resolve_engine", lambda candidate=None: candidate or engine)
    monkeypatch.setattr(storage_service, "is_enabled", lambda: True)
    def lost(*args):
        raise TimeoutError()
    monkeypatch.setattr(storage_service, "create_immutable_object", lost)
    reads = []
    monkeypatch.setattr(storage_service, "get_bounded_object", lambda key: reads.append(key))
    headers = {"Authorization": "Bearer offline-test-master-key"}
    with TestClient(app) as client:
        response = client.post('/api/v1/files/upload_base64', headers=headers, json={"filename": "a.txt", "content_base64": "eA=="})
        ref = response.json()['detail']
        jobs.enqueue('index_file', {'key': ref['key']})
        response = client.post('/api/v1/files/upload/recover', headers=headers, json={'key': ref['key'], 'job_id': ref['job_id']})
        assert response.status_code == 409
        assert reads == []
    engine.dispose()
