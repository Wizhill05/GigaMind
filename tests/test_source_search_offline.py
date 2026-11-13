import os
import base64

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from gigamind.db.database import MemoryItem, ProfileItem
from gigamind.main import app
from gigamind.services import memory


@pytest.fixture
def source_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'source.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(memory, "engine", engine)
    monkeypatch.setattr(memory, "is_postgres", False)
    with Session(engine) as session:
        for i in range(75):
            session.add(
                MemoryItem(
                    id=str(i),
                    content="ordinary filler",
                    category="other",
                    source_agent="a",
                    created_at="now",
                    last_accessed="now",
                )
            )
        session.add(
            MemoryItem(
                id="late",
                content="filler " * 2000 + "稀有 xy",
                category="wanted",
                source_agent="b",
                created_at="now",
                last_accessed="now",
                attachments_json='[{"key":"example","filename":"e"}]',
            )
        )
        session.add(
            ProfileItem(
                id="profile",
                key="稀有",
                value="xy",
                category="wanted",
                source_agent="b",
                updated_at="now",
            )
        )
        session.commit()
    yield engine
    engine.dispose()


def test_authenticated_complete_filtered_lexical_search(source_db):
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {os.environ['GIGAMIND_API_KEY']}"}

    def search(query, **kwargs):
        response = client.post(
            "/api/v1/search_memory",
            headers=headers,
            json={"query": query, "scope": "memories", **kwargs},
        )
        assert response.status_code == 200, response.text
        return response.json()["results"]

    results = search("稀有", category="wanted", source_agent="b", limit=2)
    assert {r["id"] for r in results} == {"late", "profile"}
    assert all(
        r["retrieval_method"] == "lexical" and "vector_score" not in r for r in results
    )
    assert (
        next(r for r in results if r["id"] == "late")["attachments"][0]["key"]
        == "example"
    )
    assert search("xy", category="wanted", source_agent="b")
    assert search("稀有", category="other") == []
    assert search("termabsent") == []


def test_provider_failure_and_invalid_vector(source_db, monkeypatch):
    def fail(**kwargs):
        raise memory.embedding_config.EmbeddingUnavailable("provider unavailable")

    monkeypatch.setattr(memory, "generate_embedding", fail)
    assert memory.search_memory("稀有", scope="memories")
    monkeypatch.setattr(memory, "generate_embedding", lambda **kwargs: [float("nan")])
    assert memory.search_memory("稀有", scope="memories")
    assert memory.search_memory("absent", scope="memories") == []


def test_image_validation_and_unavailable(source_db):
    jpeg = base64.b64encode(b"\xff\xd8\xff" + b"fake").decode()
    with pytest.raises(HTTPException) as unavailable:
        memory.search_memory(query_image_base64=jpeg)
    assert unavailable.value.status_code == 503
    with pytest.raises(HTTPException) as invalid:
        memory.search_memory(query_image_base64="not base64!")
    assert invalid.value.status_code == 422


def test_image_http_errors_are_distinct_from_text_fallback(source_db):
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {os.environ['GIGAMIND_API_KEY']}"}
    for image in (
        base64.b64encode(b"\xff\xd8\xffJFIF").decode(),
        base64.b64encode(b"\x89PNG\r\n\x1a\n").decode(),
    ):
        response = client.post(
            "/api/v1/search_memory",
            headers=headers,
            json={"query": "稀有", "image_base64": image},
        )
        assert response.status_code == 503
        assert "GEMINI_API_KEY" not in response.text
    invalid = client.post(
        "/api/v1/search_memory", headers=headers, json={"image_base64": "not base64!"}
    )
    assert invalid.status_code == 422
    assert (
        client.post("/api/v1/search_memory", headers=headers, json={}).status_code
        == 422
    )


def test_short_terms_do_not_match_substrings_and_results_are_deterministic(source_db):
    with Session(source_db) as session:
        for identifier, content in (
            ("go", "Use Go for services"),
            ("django", "Django governance"),
            ("c", "C language"),
        ):
            session.add(
                MemoryItem(
                    id=identifier,
                    content=content,
                    category="short",
                    source_agent="tester",
                    created_at="now",
                    last_accessed="now",
                )
            )
        session.commit()
    assert [item["id"] for item in memory.search_memory("go", scope="memories")] == [
        "go"
    ]
    assert [item["id"] for item in memory.search_memory("C", scope="memories")] == ["c"]
    first = memory.search_memory("稀有", scope="memories", limit=1)
    assert len(first) == 1
    assert memory.search_memory("稀有", scope="memories", limit=1) == first


def test_request_auth_and_programming_database_errors_never_fall_back(
    source_db, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    calls = []

    def unexpected(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("programming failure")

    monkeypatch.setattr(memory, "generate_embedding", unexpected)
    client = TestClient(app)
    assert (
        client.post("/api/v1/search_memory", json={"query": "稀有"}).status_code == 401
    )
    assert calls == []
    with pytest.raises(RuntimeError, match="programming failure"):
        memory.search_memory("稀有", scope="memories")
    monkeypatch.setattr(memory, "generate_embedding", lambda **kwargs: [])
    MemoryItem.__table__.drop(source_db)
    with pytest.raises(OperationalError):
        memory.search_memory("稀有", scope="memories")


def test_rejected_provider_credentials_still_allow_text_but_not_image_search(
    source_db, monkeypatch
):
    import io
    import urllib.error

    monkeypatch.setenv("GEMINI_API_KEY", "fake-provider-credential")

    def reject(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://provider.invalid", 403, "forbidden", {}, io.BytesIO(b"forbidden")
        )

    monkeypatch.setattr(memory.embedding_config.urllib.request, "urlopen", reject)
    results = memory.search_memory("稀有", scope="memories")
    assert results and all(item["retrieval_method"] == "lexical" for item in results)
    with pytest.raises(HTTPException) as unavailable:
        memory.search_memory(
            query_image_base64=base64.b64encode(b"\xff\xd8\xffJFIF").decode()
        )
    assert unavailable.value.status_code == 503


def test_jpeg_request_uses_detected_mime_and_valid_vectors(source_db, monkeypatch):
    import io
    import json

    monkeypatch.setenv("GEMINI_API_KEY", "fake-provider-credential")
    requests = []
    vector = [1.0] + [0.0] * (memory.embedding_config.DEFAULT_DIM - 1)

    def provider(request, **kwargs):
        requests.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"embedding": {"values": vector}}).encode())

    monkeypatch.setattr(memory.embedding_config.urllib.request, "urlopen", provider)
    memory.search_memory(
        query_image_base64=base64.b64encode(b"\xff\xd8\xffJFIF").decode(),
        scope="memories",
    )
    assert (
        requests[0]["content"]["parts"][0]["inline_data"]["mime_type"] == "image/jpeg"
    )


def test_huge_invalid_vector_is_a_provider_failure(source_db, monkeypatch):
    vector = [10**1000] * memory.embedding_config.DEFAULT_DIM
    monkeypatch.setattr(memory, "generate_embedding", lambda **kwargs: vector)
    results = memory.search_memory("稀有", scope="memories")
    assert results and all("vector_score" not in item for item in results)


def test_native_offline_lexical_search_uses_filters(postgres_engine, monkeypatch):
    from gigamind.db import migrations

    migrations.migrate(postgres_engine)
    monkeypatch.setattr(memory, "engine", postgres_engine)
    monkeypatch.setattr(memory, "is_postgres", True)

    def unavailable(**kwargs):
        raise memory.embedding_config.EmbeddingUnavailable("no provider")

    monkeypatch.setattr(memory, "generate_embedding", unavailable)
    with Session(postgres_engine) as session:
        for index in range(80):
            session.add(
                MemoryItem(
                    id=str(index),
                    content="稀有 source",
                    category="other",
                    source_agent="a",
                    created_at="now",
                    last_accessed="now",
                )
            )
        session.add(
            MemoryItem(
                id="native-late",
                content="long source " * 1000 + "稀有 Go",
                category="wanted",
                source_agent="b",
                created_at="now",
                last_accessed="now",
            )
        )
        session.add(
            ProfileItem(
                id="native-profile",
                key="language",
                value="Go",
                category="wanted",
                source_agent="b",
                updated_at="now",
            )
        )
        session.commit()
    results = memory.search_memory(
        "Go", category="wanted", source_agent="b", scope="memories", limit=2
    )
    assert {item["id"] for item in results} == {"native-late", "native-profile"}
    assert all(
        item["retrieval_method"] == "lexical" and "vector_score" not in item
        for item in results
    )
    assert memory.search_memory("missing", scope="memories") == []


from tests.test_postgres_migrations import postgres_engine  # noqa: F401, fixture
