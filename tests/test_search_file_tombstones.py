import os
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from gigamind.db.database import StorageFileItem
from gigamind.db.jobs import ResourceJobState
from gigamind.main import app
from gigamind.security import Actor
from gigamind.services import file_lifecycle, memory


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'search.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(memory, "engine", engine)
    monkeypatch.setattr(memory, "is_postgres", False)
    monkeypatch.setattr(memory, "generate_embedding", lambda **kwargs: [1.0])
    monkeypatch.setattr(
        memory, "rerank_candidates", lambda query, candidates, top_n: candidates[:top_n]
    )
    monkeypatch.setattr(memory.storage_service, "is_enabled", lambda: True)
    urls = []
    monkeypatch.setattr(
        memory.storage_service,
        "get_presigned_download_url",
        lambda key, **kwargs: urls.append(key) or f"url:{key}",
    )
    yield engine, urls
    engine.dispose()


def add_file(session, key):
    session.add(
        StorageFileItem(
            id=key,
            key=key,
            filename="needle.txt",
            document_summary="needle",
            created_at="now",
            updated_at="now",
        )
    )


def test_search_filters_before_limit_and_delete_admission(setup, monkeypatch):
    engine, urls = setup
    actor = Actor(id="admin", scopes=set(), project_ids=None, is_admin=True)
    with Session(engine) as session:
        for i in range(45):
            key = f"deleted-{i}"
            add_file(session, key)
            session.add(
                ResourceJobState(
                    key=key, deleted=True, created_at="now", updated_at="now"
                )
            )
        add_file(session, "legacy")
        add_file(session, "race")
        session.commit()
    original = file_lifecycle.active_access

    def racing_access(key, engine=None):
        if key == "race":
            file_lifecycle.request_delete(actor, key, engine)
        return original(key, engine)

    monkeypatch.setattr(file_lifecycle, "active_access", racing_access)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {os.environ['GIGAMIND_API_KEY']}"}
    for path in ("search_memory", "search_multimodal", "search_files"):
        response = client.post(
            f"/api/v1/{path}",
            headers=headers,
            json={"query": "needle", "scope": "files", "limit": 10},
        )
        assert response.status_code == 200, response.text
        assert [item["file_key"] for item in response.json()["results"]] == ["legacy"]
    assert urls == ["legacy"] * 3
    with Session(engine) as session:
        assert session.get(ResourceJobState, "race").deleted


def test_native_candidate_limits(postgres_engine, monkeypatch):
    from sqlalchemy import text
    from gigamind.db import migrations
    from gigamind.db.database import StorageChunkItem

    migrations.migrate(postgres_engine)
    monkeypatch.setattr(memory, "engine", postgres_engine)
    monkeypatch.setattr(memory, "is_postgres", True)
    monkeypatch.setattr(
        memory, "generate_embedding", lambda **kwargs: [1.0] + [0.0] * 767
    )
    monkeypatch.setattr(
        memory, "rerank_candidates", lambda query, candidates, top_n: candidates[:top_n]
    )
    monkeypatch.setattr(memory.storage_service, "is_enabled", lambda: False)
    with Session(postgres_engine) as session:
        for i in range(65):
            key = f"dead-{i}"
            add_file(session, key)
            session.add(
                ResourceJobState(
                    key=key, deleted=True, created_at="now", updated_at="now"
                )
            )
            session.add(
                StorageChunkItem(
                    id=key,
                    file_id=key,
                    file_key=key,
                    filename="needle.txt",
                    content="needle",
                    created_at="now",
                )
            )
        add_file(session, "live-doc")
        session.add(
            StorageChunkItem(
                id="live-chunk",
                file_id="live-chunk",
                file_key="live-chunk",
                filename="needle.txt",
                content="needle",
                created_at="now",
            )
        )
        session.commit()
        vector = "[" + ",".join(["1"] + ["0"] * 767) + "]"
        session.execute(
            text("UPDATE storage_files SET embedding_vector = CAST(:v AS vector)"),
            {"v": vector},
        )
        session.execute(
            text("UPDATE storage_chunks SET embedding_vector = CAST(:v AS vector)"),
            {"v": vector},
        )
        session.commit()
    results = memory.search_memory("needle", scope="files", limit=10)
    assert {item["file_key"] for item in results} == {"live-doc", "live-chunk"}
    assert all(
        item["retrieval_method"] == "lexical+vector" and item["vector_score"] > 0.99
        for item in results
    )


from tests.test_postgres_migrations import postgres_engine  # noqa: F401, fixture


def test_deletion_commits_in_another_thread_before_url_admission(setup, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    engine, urls = setup
    actor = Actor(id="admin", scopes=set(), project_ids=None, is_admin=True)
    with Session(engine) as session:
        add_file(session, "raced")
        session.commit()
    collected = Event()
    resume = Event()
    original = file_lifecycle.active_access

    def paused_access(key, engine=None):
        collected.set()
        if not resume.wait(5):
            raise RuntimeError("search was never resumed")
        return original(key, engine)

    monkeypatch.setattr(file_lifecycle, "active_access", paused_access)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(memory.search_memory, "needle", scope="files")
        try:
            assert collected.wait(5), "candidate collection did not complete"
            job = file_lifecycle.request_delete(actor, "raced", engine)
            assert job.state == "queued"
        finally:
            resume.set()
        assert future.result(timeout=5) == []
    assert urls == []


def test_missing_tombstone_schema_never_mints_a_url(setup):
    from sqlalchemy.exc import OperationalError

    engine, urls = setup
    with Session(engine) as session:
        add_file(session, "legacy")
        session.commit()
    ResourceJobState.__table__.drop(engine)
    with pytest.raises(OperationalError):
        memory.search_memory("needle", scope="files")
    assert urls == []
