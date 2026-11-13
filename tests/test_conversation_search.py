import json

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session

from gigamind.db.database import ConversationItem
from gigamind.db.migrations import migrate
from gigamind.services import memory, conversation_index, embedding, jobs


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'search.sqlite'}")
    migrate(engine)
    monkeypatch.setattr(memory, "engine", engine)
    monkeypatch.setattr(memory, "is_postgres", False)
    monkeypatch.setattr(
        memory,
        "generate_embedding",
        lambda *args: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    yield engine
    engine.dispose()


def add(engine, ident, messages, platform="ChatGPT", source="GPT", vector=None):
    with Session(engine) as session:
        session.add(
            ConversationItem(
                id=ident,
                platform=platform,
                source_agent=source,
                title="ordinary",
                summary="ordinary",
                created_at="2024",
                messages_json=json.dumps(messages),
                embedding_json=json.dumps(vector or []),
            )
        )
        session.commit()


def test_complete_transcripts_and_filters(database):
    for i in range(65):
        add(database, f"{i:03}", [{"role": "user", "content": "ordinary"}])
    messages = [{"role": "user", "content": "ordinary"} for _ in range(100)]
    messages.append(
        {
            "role": "assistant",
            "content": "x" * 500 + " cafézebra",
            "id": "node-100",
            "created_at": "yesterday",
        }
    )
    add(database, "zzz", messages)
    add(database, "other", messages, platform="Claude", source="other")
    result = memory.search_conversations(
        "cafézebra", platform="chatgpt", source_agent="gpt"
    )
    assert [x["id"] for x in result] == ["zzz"]
    assert result[0]["retrieval_method"] == "lexical"
    assert result[0]["evidence"][0] == {
        "role": "assistant",
        "index": 100,
        "text": "x" * 99 + " cafézebra",
        "id": "node-100",
        "created_at": "yesterday",
    }
    assert memory.search_conversations("absent") == []
    assert memory.search_conversations("  ") == []
    assert (
        memory.search_conversations("cafézebra", platform="claude", source_agent="gpt")
        == []
    )


def test_order_limit_and_vectors(database, monkeypatch):
    monkeypatch.setattr(memory.embedding_config, "DEFAULT_DIM", 2)
    monkeypatch.setattr(memory, "generate_embedding", lambda *args: [1.0, 0.0])
    add(database, "b", [{"role": "user", "content": "needle"}])
    add(database, "a", [{"role": "user", "content": "needle"}])
    add(database, "semantic", [], vector=[1.0, 0.0])
    add(database, "invalid", [], vector=[True, 0])
    # Unidentified old preview vectors are not a complete transcript index.
    assert memory.search_conversations("unrelated", limit=1000) == []
    monkeypatch.setattr(embedding, "generate_embedding", lambda **kwargs: [1.0, 0.0])
    conversation_index.enqueue_conversation("semantic", engine=database)
    assert jobs.run_once(engine=database).state == "completed"
    rows = memory.search_conversations("needle", limit=2)
    assert [row["id"] for row in rows] == ["a", "b"]
    rows = memory.search_conversations("unrelated", limit=1000)
    assert [row["id"] for row in rows] == ["semantic"]
    assert rows[0]["retrieval_method"] == "vector"
    assert rows[0]["evidence"][0]["role"] == "indexed_segment"
    assert rows[0]["evidence"][0]["embedding_model"] == embedding.MODEL_NAME
    monkeypatch.setattr(memory, "generate_embedding", lambda *args: [float("nan"), 0])
    assert memory.search_conversations("unrelated") == []


def test_direct_text_precedes_vector_only_and_unicode_excerpt_is_exact(
    database, monkeypatch
):
    monkeypatch.setattr(memory.embedding_config, "DEFAULT_DIM", 2)
    monkeypatch.setattr(memory, "generate_embedding", lambda *args: [1.0, 0.0])
    add(database, "a-vector", [], vector=[1.0, 0.0])
    original = "x" * 500 + " Straße is the name in this source."
    add(database, "z-direct", [{"role": "assistant", "content": original}])
    query = "strasse " + " ".join(f"absent{i}" for i in range(10))
    result = memory.search_conversations(query, limit=1)
    assert [row["id"] for row in result] == ["z-direct"]
    assert "Straße" in result[0]["evidence"][0]["text"]
    assert result[0]["evidence"][0]["text"] in original
    assert 0 < result[0]["score"] <= 1
    assert memory.search_conversations("what is the") == []


def test_query_bounds_invalid_vectors_and_database_failures(database, monkeypatch):
    from fastapi import HTTPException
    from sqlalchemy.exc import OperationalError

    monkeypatch.setattr(memory.embedding_config, "DEFAULT_DIM", 2)
    add(database, "invalid-big", [], vector=[10**1000, 1])
    monkeypatch.setattr(memory, "generate_embedding", lambda *args: [1.0, 0.0])
    assert memory.search_conversations("no_match") == []
    for query in ("x" * 2049, ["wrong-type"]):
        with pytest.raises(HTTPException) as error:
            memory.search_conversations(query)
        assert error.value.status_code == 422
    ConversationItem.__table__.drop(database)
    with pytest.raises(OperationalError):
        memory.search_conversations("text")


def test_semantic_match_uses_late_segments_with_identified_model(database, monkeypatch):
    monkeypatch.setattr(embedding, "DEFAULT_DIM", 2)
    monkeypatch.setattr(memory, "generate_embedding", lambda *args: [1.0, 0.0])
    calls = []

    def provider(**kwargs):
        content = kwargs["text"]
        calls.append(content)
        return [1.0, 0.0] if "astronomy-marker" in content else [0.0, 1.0]

    monkeypatch.setattr(embedding, "generate_embedding", provider)
    add(database, "a-legacy", [], vector=[1.0, 0.0])
    messages = [{"role": "user", "content": "一" * 9000}]
    messages.append({"role": "assistant", "content": "astronomy-marker is in the last turn"})
    add(database, "z-complete", messages)
    conversation_index.enqueue_conversation("z-complete", engine=database)
    assert jobs.run_once(engine=database).state == "completed"
    assert len(calls) > 1 and "astronomy-marker" not in calls[0]
    result = memory.search_conversations("orbitalsynonym")
    assert [row["id"] for row in result] == ["z-complete"]
    assert result[0]["retrieval_method"] == "vector"
    assert result[0]["evidence"][0]["index"] > 0
    assert result[0]["evidence"][0]["embedding_model"] == embedding.MODEL_NAME
    assert result[0]["evidence"][0]["embedding_dimension"] == 2
    monkeypatch.setattr(embedding, "MODEL_NAME", "different-model")
    assert memory.search_conversations("orbitalsynonym") == []
