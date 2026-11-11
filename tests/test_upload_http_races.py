"""Actual upload/cancel/cleanup routes with object SDK and embedding boundaries stubbed."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from gigamind.db.jobs import UploadManifest
from gigamind.main import app
from gigamind.routers import jobs as job_router
from gigamind.services import indexing, jobs
from gigamind.services.storage import storage_service

ADMIN = {"Authorization": "Bearer offline-test-master-key"}


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'http-races.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(
        jobs, "resolve_engine", lambda candidate=None: candidate or engine
    )
    monkeypatch.setattr(job_router, "engine", engine)
    monkeypatch.setattr(indexing, "engine", engine)
    monkeypatch.setattr(indexing, "is_postgres", False)
    monkeypatch.setattr(indexing.embedding, "DEFAULT_DIM", 3)
    monkeypatch.setattr(indexing, "generate_embedding", lambda **kw: [1.0, 2.0, 3.0])

    class Store:
        def __init__(self):
            self.objects = {}
            self.puts = []
            self.reads = []
            self.hook = None

        def put_object(self, **request):
            assert request["IfNoneMatch"] == "*"
            key = request["Key"]
            self.puts.append(key)
            if self.hook:
                self.hook(request)
            if key in self.objects:
                raise ClientError(
                    {
                        "Error": {
                            "Code": "PreconditionFailed",
                            "Message": "private storage detail",
                        },
                        "ResponseMetadata": {"HTTPStatusCode": 412},
                    },
                    "PutObject",
                )
            self.objects[key] = request["Body"]
            return {}

        def get_object(self, **request):
            key = request["Key"]
            self.reads.append(key)
            value = self.objects[key]
            return {"Body": BytesIO(value), "ContentLength": len(value)}

        def delete_object(self, **request):
            self.objects.pop(request["Key"], None)
            return {}

    store = Store()
    monkeypatch.setattr(storage_service, "s3_client", store)
    monkeypatch.setattr(storage_service, "bucket_name", "isolated-bucket")
    monkeypatch.setattr(storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        storage_service, "download_file", lambda key: store.objects.get(key)
    )
    with TestClient(app) as client:
        yield engine, store, client
    engine.dispose()


def test_scoped_clients_cannot_upload_or_recover(pipeline):
    engine, store, client = pipeline
    issued = client.post(
        "/api/v1/admin/clients",
        headers=ADMIN,
        json={
            "name": "upload-denied",
            "scopes": [
                "memory:read",
                "memory:propose",
                "memory:write",
                "memory:delete",
            ],
            "project_ids": ["p"],
        },
    ).json()
    restricted = {"Authorization": "Bearer " + issued["token"]}
    assert (
        client.post(
            "/api/v1/files/upload",
            headers=restricted,
            files={"file": ("a.txt", b"abc", "text/plain")},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/files/upload_base64",
            headers=restricted,
            json={"filename": "a.txt", "content_base64": "YWJj"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/files/upload/recover",
            headers=restricted,
            json={"key": "a", "job_id": "b"},
        ).status_code
        == 403
    )
    assert not store.puts and not store.reads
    with Session(engine) as session:
        assert session.exec(select(UploadManifest)).all() == []


def test_collision_cannot_overwrite_existing_object(pipeline, monkeypatch):
    _, store, client = pipeline
    key = "files/collision.txt"
    store.objects[key] = b"original bytes"
    monkeypatch.setattr(storage_service, "generate_storage_key", lambda *a: key)
    response = client.post(
        "/api/v1/files/upload_base64",
        headers=ADMIN,
        json={"filename": "new.txt", "content_base64": "bmV3"},
    )
    assert response.status_code == 503
    assert "private storage detail" not in response.text
    ref = response.json()["detail"]
    assert store.objects[key] == b"original bytes" and store.puts == [key]
    assert (
        client.post(
            "/api/v1/files/upload/recover",
            headers=ADMIN,
            json={"key": key, "job_id": ref["job_id"]},
        ).status_code
        == 409
    )
    assert jobs.claim() is None
    assert (
        client.post(
            "/api/v1/files/delete", headers=ADMIN, json={"key": key}
        ).status_code
        == 409
    )
    assert store.puts == [key]


def test_real_twenty_megabyte_boundary(pipeline):
    _, store, client = pipeline
    accepted = client.post(
        "/api/v1/files/upload",
        headers=ADMIN,
        files={"file": ("at-limit.txt", b"x" * 20_000_000, "text/plain")},
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["file"]["size_bytes"] == 20_000_000
    rejected = client.post(
        "/api/v1/files/upload",
        headers=ADMIN,
        files={"file": ("too-large.txt", b"x" * 20_000_001, "text/plain")},
    )
    assert rejected.status_code == 413
    assert len(store.puts) == 1


def test_slow_put_allows_heartbeat_but_cancel_does_not_allow_deletion(
    pipeline, monkeypatch
):
    engine, store, client = pipeline
    entered_provider, entered_put, renewed, release_put, release_provider = (
        Event() for _ in range(5)
    )
    store.objects["heartbeat.txt"] = b"worker source"
    other = jobs.enqueue("index_file", {"key": "heartbeat.txt"})
    original_heartbeat = jobs.heartbeat

    def observe_heartbeat(*args, **kwargs):
        result = original_heartbeat(*args, **kwargs)
        if result and entered_put.is_set():
            renewed.set()
        return result

    def embedding(**kwargs):
        entered_provider.set()
        assert release_provider.wait(10), "test did not release worker provider"
        return [1.0, 2.0, 3.0]

    def slow_put(request):
        entered_put.set()
        assert release_put.wait(10), "test did not release remote PUT"

    monkeypatch.setattr(jobs, "heartbeat", observe_heartbeat)
    monkeypatch.setattr(indexing, "generate_embedding", embedding)
    store.hook = slow_put
    with ThreadPoolExecutor(2) as pool:
        worker = pool.submit(jobs.run_once, lease_seconds=3)
        assert entered_provider.wait(5)
        uploading = pool.submit(
            client.post,
            "/api/v1/files/upload_base64",
            headers=ADMIN,
            json={"filename": "new.txt", "content_base64": "bmV3"},
        )
        try:
            assert entered_put.wait(5)
            with Session(engine) as session:
                manifest = session.exec(select(UploadManifest)).one()
                key, job_id = manifest.key, manifest.job_id
            assert (
                client.post(
                    "/api/v1/jobs/" + job_id + "/cancel", headers=ADMIN
                ).status_code
                == 200
            )
            assert (
                client.post(
                    "/api/v1/files/delete", headers=ADMIN, json={"key": key}
                ).status_code
                == 409
            )
            assert renewed.wait(5), "upload IO prevented a real worker heartbeat"
            assert jobs.status(other.id).state == "running"
        finally:
            release_put.set()
            release_provider.set()
        uploaded = uploading.result(timeout=10)
        assert uploaded.status_code == 409, uploaded.text
        assert uploaded.json()["detail"]["verified"] is True
        assert worker.result(timeout=10).state == "completed"
    assert jobs.status(job_id).state == "cancelled"
    cleanup = client.post("/api/v1/files/delete", headers=ADMIN, json={"key": key})
    assert cleanup.status_code == 202
    assert jobs.run_once().state == "completed"
    assert key not in store.objects
    reads = list(store.reads)
    assert (
        client.post(
            "/api/v1/files/upload/recover",
            headers=ADMIN,
            json={"key": key, "job_id": job_id},
        ).status_code
        == 409
    )
    assert store.reads == reads and store.puts == [key]
