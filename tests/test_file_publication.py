import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, select

from gigamind.db.database import StorageChunkItem, StorageFileItem
from gigamind.services import indexing


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'publication.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(indexing, "engine", engine)
    monkeypatch.setattr(indexing, "is_postgres", False)
    monkeypatch.setattr(indexing.embedding, "DEFAULT_DIM", 3)
    monkeypatch.setattr(
        indexing,
        "extract_text_from_file",
        lambda data, **kw: {
            "supported": data != b"unsupported",
            "format": "binary" if data == b"unsupported" else "text",
            "text": "" if data == b"unsupported" else data.decode(),
        },
    )
    monkeypatch.setattr(
        indexing,
        "chunk_text",
        lambda text, **kw: [{"content": part} for part in text.split("|")],
    )
    monkeypatch.setattr(indexing, "generate_embedding", lambda **kw: [1, 2, 3])
    yield engine
    engine.dispose()


def publish(data, guard=None):
    return indexing.index_file_content("key", "file.txt", data, publication_guard=guard)


def snapshot(engine):
    with Session(engine) as session:
        file = session.exec(select(StorageFileItem)).first()
        chunks = session.exec(
            select(StorageChunkItem).order_by(StorageChunkItem.chunk_index)
        ).all()
        return (
            (
                file.id,
                file.indexing_status,
                file.embedding_json,
                file.total_chunks,
                [c.content for c in chunks],
            )
            if file
            else None
        )


def test_replacement_and_failures(database, monkeypatch):
    result = publish(b"one|two|three")
    assert snapshot(database)[-1] == ["one", "two", "three"]
    assert publish(b"short")["file_id"] == result["file_id"]
    before = snapshot(database)
    assert before[-1] == ["short"]

    def failure(**kwargs):
        raise RuntimeError("provider failed")

    monkeypatch.setattr(indexing, "generate_embedding", failure)
    with pytest.raises(RuntimeError):
        publish(b"new")
    assert snapshot(database) == before
    for vector in (
        [0, 0, 0],
        [1, 2],
        [1, float("nan"), 3],
        [1, float("inf"), 3],
        [True, 2, 3],
        ["1", 2, 3],
        {1: 1, 2: 2, 3: 3},
    ):
        monkeypatch.setattr(indexing, "generate_embedding", lambda **kw: vector)
        with pytest.raises(ValueError):
            publish(b"new")
        assert snapshot(database) == before
    calls = iter([[1, 2, 3], [0, 0, 0]])
    monkeypatch.setattr(indexing, "generate_embedding", lambda **kw: next(calls))
    with pytest.raises(ValueError):
        publish(b"new|second")
    assert snapshot(database) == before


def test_guard_and_rollback(database, monkeypatch):
    def deny(session):
        raise PermissionError("denied")

    with pytest.raises(PermissionError):
        publish(b"new", deny)
    assert snapshot(database) is None
    publish(b"old")
    before = snapshot(database)
    with pytest.raises(PermissionError):
        publish(b"new", deny)
    assert snapshot(database) == before
    with pytest.raises(PermissionError):
        publish(b"unsupported", deny)
    assert snapshot(database) == before

    def guard(session):
        file = session.exec(select(StorageFileItem)).one()
        file.source_agent = "guard-write"

    monkeypatch.setattr(indexing, "is_postgres", True)
    with pytest.raises(OperationalError, match="embedding_vector"):
        publish(b"new", guard)
    assert snapshot(database) == before
    with Session(database) as session:
        assert session.exec(select(StorageFileItem)).one().source_agent == "user"


@pytest.mark.parametrize(
    "data,status", [(b"", "empty"), (b"unsupported", "unsupported")]
)
def test_empty_clears_existing(database, data, status):
    old = publish(b"one|two")
    result = publish(data)
    assert result["file_id"] == old["file_id"]
    assert result["status"] == status
    assert snapshot(database) == (old["file_id"], status, "[]", 0, [])


def test_reindex_forwards_guard(database, monkeypatch):
    monkeypatch.setattr(indexing.storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        indexing.storage_service, "download_file", lambda key: b"content"
    )

    def deny(session):
        raise PermissionError("denied")

    with pytest.raises(PermissionError):
        indexing.reindex_storage_file_by_key("key", publication_guard=deny)
    assert snapshot(database) is None
