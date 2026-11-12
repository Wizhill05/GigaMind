"""Published file text stays searchable beyond vector and summary candidate caps."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy import text

from gigamind.db.database import StorageFileItem, StorageChunkItem
from gigamind.db.jobs import ResourceJobState
from gigamind.main import app, API_KEY
from gigamind.security import Actor
from gigamind.services import memory, file_lifecycle


def seed(engine):
    with Session(engine) as session:
        for index in range(80):
            session.add(
                StorageFileItem(
                    id=f"early-{index}",
                    key=f"early/{index}",
                    filename="noise.txt",
                    source_agent="other",
                    document_summary="needle",
                    created_at="now",
                    updated_at="now",
                )
            )
        session.add(
            StorageFileItem(
                id="late",
                key="late",
                filename="report.pdf",
                source_agent="wanted",
                multimodal_type="pdf",
                document_summary="Introduction",
                created_at="now",
                updated_at="now",
            )
        )
        session.add(
            StorageFileItem(
                id="summary",
                key="summary",
                filename="summary.txt",
                source_agent="wanted",
                document_summary="needle summary",
                created_at="now",
                updated_at="now",
            )
        )
        for index in range(74):
            content = "needle 稀有 evidence" if index >= 72 else "Ordinary page"
            session.add(
                StorageChunkItem(
                    id=f"page-{index:03}",
                    file_id="late",
                    file_key="late",
                    filename="report.pdf",
                    chunk_index=index,
                    total_chunks=74,
                    page_number=index + 1,
                    content=content,
                    created_at="now",
                )
            )
        session.commit()


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'corpus.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(memory, "engine", engine)
    monkeypatch.setattr(memory, "is_postgres", False)
    monkeypatch.setattr(memory, "generate_embedding", lambda **kwargs: [])
    monkeypatch.setattr(memory.storage_service, "is_enabled", lambda: False)
    seed(engine)
    yield engine
    engine.dispose()


def test_published_late_pages_and_summary_survive_filters_and_parent_dedup(corpus):
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {API_KEY}"}
    response = client.post(
        "/api/v1/search_memory",
        headers=headers,
        json={
            "query": "needle 稀有",
            "source_agent": "wanted",
            "category": "file",
            "scope": "files",
            "limit": 2,
        },
    )
    assert response.status_code == 200, response.text
    found = response.json()["results"]
    assert [item["file_key"] for item in found] == ["late", "summary"]
    page = found[0]
    assert page["file_id"] == "late" and page["chunk_index"] == 72
    assert page["page_number"] == 73 and page["total_chunks"] == 74
    assert page["matching_pages"] == [73, 74]
    assert "稀有 evidence" in page["content"] and "73, 74" in page["citation"]
    assert page["source_agent"] == "wanted" and page["retrieval_method"] == "lexical"
    assert "vector_score" not in page
    assert memory.search_memory("稀有", scope="files", category="coding") == []
    assert memory.search_memory("needle", scope="files", source_agent="missing") == []
    assert memory.search_memory("absent", scope="files") == []
    assert (
        memory.search_memory(
            "needle 稀有", scope="files", source_agent="wanted", limit=1
        )
        == found[:1]
    )


def test_tombstones_are_excluded_before_pool_limits_and_urls_are_bounded(
    corpus, monkeypatch
):
    with Session(corpus) as session:
        for index in range(80):
            key = f"early/{index}"
            session.add(
                ResourceJobState(
                    key=key, deleted=True, created_at="now", updated_at="now"
                )
            )
        session.commit()
    calls = []
    monkeypatch.setattr(memory.storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        memory.storage_service,
        "get_presigned_download_url",
        lambda key, **kwargs: calls.append(key) or f"url:{key}",
    )
    results = memory.search_memory("needle", scope="files", limit=2)
    assert {item["file_key"] for item in results} == {"late", "summary"}
    assert set(calls) == {"late", "summary"} and len(calls) == 2


def test_chunk_match_is_fenced_by_deletion_in_another_transaction(corpus, monkeypatch):
    collected, resume = Event(), Event()
    calls = []
    original = file_lifecycle.active_access

    def paused(key, engine=None):
        collected.set()
        if not resume.wait(5):
            raise RuntimeError("admission was not resumed")
        return original(key, engine)

    monkeypatch.setattr(file_lifecycle, "active_access", paused)
    monkeypatch.setattr(memory.storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        memory.storage_service,
        "get_presigned_download_url",
        lambda key, **kwargs: calls.append(key) or "url",
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(memory.search_memory, "稀有", scope="files")
        try:
            assert collected.wait(5), "late-page candidate was not collected"
            file_lifecycle.request_delete(
                Actor("admin", set(), None, True), "late", corpus
            )
        finally:
            resume.set()
        assert future.result(timeout=5) == []
    assert calls == []


def test_table_local_ids_do_not_merge_unrelated_evidence(corpus):
    with Session(corpus) as session:
        session.add(
            StorageFileItem(
                id="page-072",
                key="collision",
                filename="same-id.txt",
                document_summary="稀有",
                created_at="now",
                updated_at="now",
            )
        )
        session.commit()
    results = memory.search_memory("稀有", scope="files", limit=5)
    assert {item["file_key"] for item in results} == {"late", "collision"}


def test_scanned_files_do_not_all_generate_urls(corpus, monkeypatch):
    calls = []
    monkeypatch.setattr(memory.storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        memory.storage_service,
        "get_presigned_download_url",
        lambda key, **kwargs: calls.append(key) or "url",
    )
    assert len(memory.search_memory("needle", scope="files", limit=1)) == 1
    assert len(calls) <= 25


@pytest.fixture
def native_corpus(postgres_engine, monkeypatch):
    from gigamind.db import migrations

    migrations.migrate(postgres_engine)
    seed(postgres_engine)
    monkeypatch.setattr(memory, "engine", postgres_engine)
    monkeypatch.setattr(memory, "is_postgres", True)
    monkeypatch.setattr(
        memory, "generate_embedding", lambda **kwargs: [1.0] + [0.0] * 767
    )
    monkeypatch.setattr(memory.storage_service, "is_enabled", lambda: False)
    with postgres_engine.begin() as connection:
        vector = "[" + ",".join(["1"] + ["0"] * 767) + "]"
        connection.execute(
            text(
                "UPDATE storage_files SET embedding_vector = CAST(:v AS vector) WHERE source_agent = 'other'"
            ),
            {"v": vector},
        )
        connection.execute(
            text("UPDATE storage_chunks SET embedding_vector = CAST(:v AS vector)"),
            {"v": vector},
        )
        connection.execute(
            text(
                "UPDATE storage_files SET embedding_vector = CAST(:v AS vector) WHERE id = 'summary'"
            ),
            {"v": vector},
        )
    return postgres_engine


def test_native_lexical_hits_survive_a_full_vector_pool(native_corpus):
    result = memory.search_memory("稀有", scope="files", limit=1)
    assert result[0]["file_key"] == "late" and "稀有" in result[0]["content"]
    assert result[0]["page_number"] == 73
    # The lexical evidence is outside the nearest 60 chunk vectors.
    assert result[0]["retrieval_method"] == "lexical"
    assert "vector_score" not in result[0]


def test_native_filters_apply_to_parent_owned_chunks_before_limits(native_corpus):
    result = memory.search_memory(
        "absent", source_agent="wanted", scope="files", limit=5
    )
    assert {item["file_key"] for item in result} == {"summary", "late"}
    assert all(
        item["source_agent"] == "wanted" and item["vector_score"] > 0.99
        for item in result
    )
    with Session(native_corpus) as session:
        owner = session.get(ResourceJobState, "late")
        owner.deleted = True
        session.add(owner)
        session.commit()
    assert {
        item["file_key"]
        for item in memory.search_memory("absent", source_agent="wanted", scope="files")
    } == {"summary"}


from tests.test_postgres_migrations import postgres_engine  # noqa: F401, fixture
