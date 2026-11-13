"""Durable queue admission through real authenticated REST boundaries."""

import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session

from gigamind import main, security
from gigamind.db.database import ConversationItem
from gigamind.db.migrations import migrate
from gigamind.routers import jobs as jobs_router
from gigamind.services import conversation_index, embedding, jobs, memory


def test_http_indexing_is_durable_scoped_and_truthful(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'http.db'}", connect_args={"check_same_thread": False})
    migrate(engine)
    monkeypatch.setattr(memory, "engine", engine)
    monkeypatch.setattr(security, "engine", engine)
    monkeypatch.setattr(jobs_router, "engine", engine)
    with Session(engine) as session:
        for ident in ("a", "b", "c"):
            session.add(ConversationItem(
                id=ident, platform="test", title="Transcript", summary="",
                messages_json=json.dumps([{"role": "tool", "content": "late transcript evidence"}]),
                embedding_json="[]", created_at="now",
            ))
        session.commit()
    calls = []

    def provider(**kwargs):
        calls.append(kwargs["text"])
        return [1.0] + [0.0] * (embedding.DEFAULT_DIM - 1)

    monkeypatch.setattr(embedding, "generate_embedding", provider)
    _, token = security.create_client("reader", ["memory:read"], ["project-a"])
    admin = {"Authorization": "Bearer offline-test-master-key"}
    scoped = {"Authorization": f"Bearer {token}"}
    with TestClient(main.app) as client:
        assert client.post("/api/v1/conversations/a/vectorize").status_code == 401
        assert client.post("/api/v1/conversations/a/vectorize", headers=scoped).status_code == 403
        assert client.post("/api/v1/conversations/backfill_vectors", headers=scoped).status_code == 403
        assert client.post("/api/v1/conversations/missing/vectorize", headers=admin).status_code == 404
        queued = client.post("/api/v1/conversations/a/vectorize", headers=admin, json={"idempotency_key": "a-index"})
        assert queued.status_code == 202, queued.text
        job = queued.json()
        assert job["state"] == "queued" and job["job_id"]
        assert not calls
        replay = client.post("/api/v1/conversations/a/vectorize", headers=admin, json={"idempotency_key": "a-index"})
        assert replay.json()["job_id"] == job["job_id"]
        exact = client.get("/api/v1/conversations/a", headers=admin).json()["conversation"]
        assert exact["is_vectorized"] is False
        assert (exact["index_status"], exact["index_job_id"]) == ("queued", job["job_id"])
        listed = client.get("/api/v1/conversations", headers=admin).json()
        assert listed["total_vectorized"] == 0
        batch = client.post("/api/v1/conversations/backfill_vectors", headers=admin, json={"limit": 2})
        assert batch.status_code == 202, batch.text
        assert {key: batch.json()[key] for key in ("queued", "skipped", "next_cursor")} == {"queued": 1, "skipped": 1, "next_cursor": "b"}
        assert not calls
        engine.dispose()
        assert jobs.run_once(engine=engine).id == job["job_id"]
        assert calls and "late transcript evidence" in calls[0]
        exact = client.get("/api/v1/conversations/a", headers=admin).json()["conversation"]
        assert exact["is_vectorized"] is True and exact["index_status"] == "completed"
        assert client.get("/api/v1/conversations", headers=admin).json()["total_vectorized"] == 1
        retry = client.post("/api/v1/jobs", headers=admin, json={
            "kind": "index_conversation", "payload": {"conversation_id": "a"},
            "idempotency_key": "retry-a", "max_attempts": 5,
        })
        assert retry.status_code == 200, retry.text
        assert retry.json()["max_attempts"] == 5
        assert client.post("/api/v1/jobs", headers=admin, json={"kind": "index_conversation", "payload": {"key": "a"}}).status_code == 422
        assert client.post("/api/v1/conversations/backfill_vectors", headers=admin, json={"limit": True}).status_code == 422
        assert client.delete("/api/v1/conversations/a", headers=admin).status_code == 200
        assert client.get(f"/api/v1/jobs/{retry.json()['id']}", headers=admin).json()["state"] == "cancelled"
        assert client.post("/api/v1/conversations/a/vectorize", headers=admin, json={"idempotency_key": "a-index"}).status_code == 404
        assert conversation_index.segment_vectors("a", engine=engine) == []
    engine.dispose()
