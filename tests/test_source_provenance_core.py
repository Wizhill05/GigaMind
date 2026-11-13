from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel
from gigamind.db.source_provenance import SourceHead, SourceReceipt
from gigamind.services.source_provenance import (
    lock_sources,
    read_provenance,
    record_write,
)


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sources.db'}", connect_args={"timeout": 10}
    )
    SQLModel.metadata.create_all(
        engine, tables=[SourceHead.__table__, SourceReceipt.__table__]
    )
    yield engine
    engine.dispose()


def test_transactions_creator_and_pagination(engine):
    admin = SimpleNamespace(id="real", is_admin=True)
    with Session(engine) as s:
        lock_sources(s)
        record_write(
            s,
            kind="memory",
            source_id="1",
            operation="created",
            actor=admin,
            payload={"source_agent": "claimed", "secret": "hello"},
        )
        s.rollback()
        assert read_provenance(engine, "memory", "1") is None
        with pytest.raises(RuntimeError):
            record_write(s, kind="memory", source_id="1", operation="created")
        lock_sources(s)
        record_write(s, kind="memory", source_id="1", operation="created", actor=admin)
        record_write(s, kind="memory", source_id="1", operation="deleted")
        record_write(
            s,
            kind="memory",
            source_id="1",
            operation="created",
            actor=SimpleNamespace(id="other", is_admin=True),
        )
        s.commit()
        with pytest.raises(RuntimeError):
            record_write(s, kind="memory", source_id="1", operation="updated")
    result = read_provenance(engine, "memory", "1", limit=1, offset=1)
    assert result["head"]["revision"] == 3
    assert result["head"]["creator_id"] == "real"
    assert result["head"]["active"] and result["receipts"][0]["operation"] == "deleted"
    with Session(engine) as s:
        lock_sources(s)
        with pytest.raises(PermissionError):
            record_write(
                s,
                kind="profile",
                source_id="x",
                operation="created",
                actor=SimpleNamespace(id="bad", is_admin=False),
            )
        record_write(
            s,
            kind="profile",
            source_id="x",
            operation="updated",
            actor=admin,
            payload={"source_agent": "claimed", "secret": "hello"},
        )
        record_write(s, kind="profile", source_id="x", operation="created", actor=admin)
        s.commit()
    result = read_provenance(engine, "profile", "x")
    assert result["head"]["creator_provenance"] == "legacy_unknown"
    assert result["head"]["creator_id"] is None
    assert result["receipts"][1]["writer_id"] == "real"
    assert "hello" not in str(result) and "claimed" not in str(result)


def test_concurrent_writes(engine):
    def write(_):
        with Session(engine) as s:
            lock_sources(s)
            record_write(s, kind="memory", source_id="x", operation="updated")
            s.commit()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(12)))
    result = read_provenance(engine, "memory", "x")
    assert result["head"]["revision"] == 12
    assert [r["revision"] for r in result["receipts"]] == list(range(12, 0, -1))


def test_schema6_backfill_preserves_ledger(tmp_path):
    from sqlalchemy import text
    from gigamind.db.database import MemoryItem, ProfileItem
    from gigamind.db.migrations import migrate

    engine = create_engine(f"sqlite:///{tmp_path / 'upgrade.db'}")
    migrate(engine)
    with Session(engine) as s:
        s.add(
            MemoryItem(
                id="parent", content="secret", created_at="old", last_accessed="old"
            )
        )
        s.add(
            MemoryItem(
                id="child",
                parent_id="parent",
                content="chunk",
                created_at="old",
                last_accessed="old",
            )
        )
        s.add(ProfileItem(id="profile", key="k", value="v", updated_at="old"))
        s.commit()
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO conversation_sources (key, platform, identity_kind, created_at, forgotten_at) VALUES ('tombstone', 'x', 'legacy_unknown', 'old', 'deleted')"
            )
        )
        c.execute(
            text(
                "INSERT INTO conversation_receipts (conversation_id, source_key, provenance, deleted_at) VALUES ('gone', 'tombstone', 'legacy_unknown', 'deleted')"
            )
        )
        c.execute(text("DELETE FROM schema_migrations WHERE version=7"))
        c.execute(text("INSERT INTO schema_migrations (version) VALUES (6)"))
    migrate(engine)
    assert (
        read_provenance(engine, "memory", "parent")["head"]["creator_provenance"]
        == "legacy_unknown"
    )
    assert read_provenance(engine, "memory", "child") is None
    assert read_provenance(engine, "profile", "profile")["head"]["revision"] == 0
    with engine.connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT deleted_at FROM conversation_receipts WHERE conversation_id='gone'"
                )
            ).scalar_one()
            == "deleted"
        )


@pytest.mark.parametrize(
    "limit, offset", [(True, 0), (1.5, 0), (20, False), (20, 1.5), (20, 1_000_001)]
)
def test_read_bounds_are_integers(engine, limit, offset):
    with pytest.raises(ValueError):
        read_provenance(engine, "memory", "id", limit=limit, offset=offset)


def test_actual_revision_rejects_unstructured_payloads(engine):
    with Session(engine) as session:
        lock_sources(session)
        for revision in ({"private": "must not be stored"}, True, "private text", -1):
            with pytest.raises(ValueError):
                record_write(
                    session,
                    kind="memory",
                    source_id="id",
                    operation="created",
                    source_revision=revision,
                )
        session.commit()
    assert read_provenance(engine, "memory", "id") is None


def test_read_binds_receipts_to_head_snapshot(engine):
    from sqlalchemy import event

    with Session(engine) as session:
        lock_sources(session)
        record_write(session, kind="memory", source_id="snapshot", operation="created")
        record_write(session, kind="memory", source_id="snapshot", operation="updated")
        session.commit()
    changed = False

    def append(connection, cursor, statement, parameters, context, executemany):
        nonlocal changed
        if (
            not changed
            and statement.startswith("SELECT")
            and "FROM source_provenance_receipts" in statement
        ):
            changed = True
            with Session(engine) as writer:
                lock_sources(writer)
                record_write(
                    writer, kind="memory", source_id="snapshot", operation="updated"
                )
                writer.commit()

    event.listen(engine, "before_cursor_execute", append)
    try:
        snapshot = read_provenance(engine, "memory", "snapshot")
    finally:
        event.remove(engine, "before_cursor_execute", append)
    assert changed and snapshot["head"]["revision"] == snapshot["total"] == 2
    assert [receipt["revision"] for receipt in snapshot["receipts"]] == [2, 1]
    assert read_provenance(engine, "memory", "snapshot")["total"] == 3
