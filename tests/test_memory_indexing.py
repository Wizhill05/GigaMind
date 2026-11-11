import threading

import pytest
from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine, select
from gigamind.db.database import MemoryItem
from gigamind.db.memory_index import MemoryIndexState
from gigamind.services import memory


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(memory, "engine", engine)
    monkeypatch.setattr(memory, "is_postgres", False)
    monkeypatch.setattr(memory.embedding_config, "DEFAULT_DIM", 3)
    monkeypatch.setattr(memory, "generate_embedding", lambda text: [1.0, 0.0, 0.0])
    return engine


def test_failure_persists_and_clears_stale_chunks(db, monkeypatch):
    saved = memory.add_memory("old words " * 150)
    assert saved["index_status"] == "completed"
    monkeypatch.setattr(
        memory,
        "generate_embedding",
        lambda text: (_ for _ in ()).throw(RuntimeError("secret")),
    )
    updated = memory.update_memory(saved["id"], content="new words " * 150)
    assert (
        updated["index_status"] == "failed" and "secret" not in updated["index_error"]
    )
    with Session(db) as session:
        assert session.get(MemoryItem, saved["id"]).content == "new words " * 150
        assert not session.exec(
            select(MemoryItem).where(MemoryItem.parent_id == saved["id"])
        ).all()


def test_rebuild_metadata_and_conflict(db, monkeypatch):
    saved = memory.add_memory("first")
    calls = []
    monkeypatch.setattr(
        memory, "generate_embedding", lambda text: calls.append(text) or [1.0, 0.0, 0.0]
    )
    updated = memory.update_memory(
        saved["id"], content="later words " * 160, category="work", tags=["x"]
    )
    assert len(calls) == updated["total_chunks"] > 1
    assert "later words" in calls[-1]
    memory.update_memory(
        saved["id"],
        category="new",
        source_agent="agent",
        tags=["y"],
        attachments=[{"key": "a"}],
    )
    with Session(db) as session:
        children = session.exec(
            select(MemoryItem).where(MemoryItem.parent_id == saved["id"])
        ).all()
        assert all(
            c.category == "new"
            and c.source_agent == "agent"
            and "y" in c.tags_json
            and "a" in c.attachments_json
            for c in children
        )
    with pytest.raises(HTTPException) as error:
        memory.update_memory(saved["id"], content="conflict", expected_revision=1)
    assert error.value.status_code == 409


def test_overlapping_and_deleted_indexing(db, monkeypatch):
    saved = memory.add_memory("first")
    entered, release = threading.Event(), threading.Event()

    def embed(text):
        if text.startswith("slow"):
            entered.set()
            assert release.wait(10)
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(memory, "generate_embedding", embed)
    worker = threading.Thread(
        target=memory.update_memory,
        args=(saved["id"],),
        kwargs={"content": "slow " * 150},
    )
    worker.start()
    assert entered.wait(10)
    memory.update_memory(saved["id"], content="fast " * 150)
    release.set()
    worker.join(10)
    assert not worker.is_alive()
    with Session(db) as session:
        children = session.exec(
            select(MemoryItem).where(MemoryItem.parent_id == saved["id"])
        ).all()
        assert children and all("slow" not in child.content for child in children)
    entered.clear()
    release.clear()
    worker = threading.Thread(
        target=memory.update_memory,
        args=(saved["id"],),
        kwargs={"content": "slow " * 150},
    )
    worker.start()
    assert entered.wait(10)
    assert memory.delete_memory(saved["id"])
    release.set()
    worker.join(10)
    with Session(db) as session:
        assert session.get(MemoryIndexState, saved["id"]) is None
        assert not session.exec(select(MemoryItem)).all()


@pytest.mark.parametrize(
    "vector", [None, [], [1.0, 2.0], [float("nan"), 0.0, 0.0], [float("inf"), 0.0, 0.0]]
)
def test_invalid_provider_results_preserve_source(db, monkeypatch, vector):
    monkeypatch.setattr(memory, "generate_embedding", lambda text: vector)
    saved = memory.add_memory("source survives")
    assert saved["index_status"] == "failed"
    assert saved["indexed_revision"] is None
    with Session(db) as session:
        assert session.get(MemoryItem, saved["id"]).content == "source survives"
        assert session.get(MemoryIndexState, saved["id"]).index_status == "failed"


def test_metadata_revision_and_export(db):
    saved = memory.add_memory("source")
    changed = memory.update_memory(saved["id"], category="work", expected_revision=1)
    assert changed["revision"] == changed["indexed_revision"] == 2
    exported = next(
        item for item in memory.export_all_memories() if item["id"] == saved["id"]
    )
    assert exported["content"] == "source" and exported["embedding_dimension"] == 3
    with pytest.raises(HTTPException) as error:
        memory.update_memory(saved["id"], tags=["stale"], expected_revision=1)
    assert error.value.status_code == 409


def test_attachments_remain_registered_and_failed_retry_preserves_completion(
    db, monkeypatch
):
    from gigamind.db.database import StorageFileItem

    saved = memory.add_memory("shared source", attachments=[{"key": "shared.pdf"}])
    with Session(db) as session:
        stored = session.exec(
            select(StorageFileItem).where(StorageFileItem.key == "shared.pdf")
        ).one()
        assert stored.indexing_status == "pending"
    memory.add_memory("another source", attachments=[{"key": "shared.pdf"}])
    monkeypatch.setattr(
        memory,
        "generate_embedding",
        lambda text: (_ for _ in ()).throw(RuntimeError("provider failed")),
    )
    memory._index_memory(saved["id"], saved["revision"], saved["content"])
    with Session(db) as session:
        assert session.get(MemoryIndexState, saved["id"]).index_status == "completed"
        assert (
            len(
                session.exec(
                    select(StorageFileItem).where(StorageFileItem.key == "shared.pdf")
                ).all()
            )
            == 1
        )
    memory.delete_memory(saved["id"])
    with Session(db) as session:
        assert session.exec(
            select(StorageFileItem).where(StorageFileItem.key == "shared.pdf")
        ).one()


def test_legacy_state_initialization_and_revision_api(db, monkeypatch):
    from fastapi.testclient import TestClient
    from gigamind import main

    with Session(db) as session:
        session.add(MemoryItem(id='legacy', content='retained', created_at='now', last_accessed='now'))
        session.commit()
    initialized = memory.update_memory('legacy', category='updated')
    assert initialized['revision'] == 1
    assert initialized['index_status'] == 'completed'
    monkeypatch.setenv('GIGAMIND_API_KEY', 'indexing-api-test-admin')
    client = TestClient(main.app)
    headers = {'Authorization': 'Bearer indexing-api-test-admin'}
    response = client.put('/api/v1/memories/legacy', headers=headers, json={'content': 'current', 'expected_revision': 1})
    assert response.status_code == 200, response.text
    assert response.json()['memory']['revision'] == 2
    stale = client.put('/api/v1/memories/legacy', headers=headers, json={'content': 'stale', 'expected_revision': 1})
    assert stale.status_code == 409
    assert memory.get_memories()['memories'][0]['content'] == 'current'


def test_deleted_initial_write_is_not_reported_as_saved(db, monkeypatch):
    def embed(source):
        with Session(db) as session:
            record = session.exec(select(MemoryItem).where(MemoryItem.content == source)).one()
            memory_id = record.id
        assert memory.delete_memory(memory_id)
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(memory, 'generate_embedding', embed)
    with pytest.raises(HTTPException) as deleted:
        memory.add_memory('deleted during initial indexing')
    assert deleted.value.status_code == 409
    assert memory.get_memories()['total'] == 0
