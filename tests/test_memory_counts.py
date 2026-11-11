from sqlmodel import SQLModel, create_engine
from gigamind.services import memory


def test_counts_and_lists_use_logical_memories(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/memories.db")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(memory, "engine", engine)
    monkeypatch.setattr(memory, "is_postgres", False)
    monkeypatch.setattr(memory.embedding_config, "DEFAULT_DIM", 3)
    monkeypatch.setattr(
        memory, "generate_embedding", lambda *args, **kwargs: [1.0, 0.0, 0.0]
    )
    saved = memory.add_memory("long source record " * 100, source_agent="gpt")
    assert saved["chunks_created"] > 1
    listed = memory.get_memories()
    assert listed["total"] == 1
    assert [item["id"] for item in listed["memories"]] == [saved["id"]]
    stats = memory.get_stats()
    assert stats["total_memories"] == 1
    assert stats["source_distribution"] == {"gpt": 1}
    assert memory.get_memories(page=0, limit=0)["page"] == 1
    assert len(memory.get_memories(page=0, limit=0)["memories"]) == 1
