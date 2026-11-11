"""Optional native integration checks against an isolated local PostgreSQL service."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from gigamind.db import database, migrations


@pytest.fixture
def postgres_engine():
    test_url = os.getenv("GIGAMIND_TEST_POSTGRES_URL")
    if not test_url:
        pytest.skip("Set GIGAMIND_TEST_POSTGRES_URL for native PostgreSQL integration")
    url = make_url(test_url)
    if url.host not in ("127.0.0.1", "localhost", "::1"):
        pytest.fail("PostgreSQL integration tests require an isolated local service")
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg2")
    namespace = "gigamind_test_" + uuid.uuid4().hex
    root = create_engine(url)
    with root.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text(f'CREATE SCHEMA "{namespace}"'))
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={namespace},public"}
    )
    try:
        yield engine
    finally:
        engine.dispose()
        with root.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))
        root.dispose()


def test_native_schema_readiness_and_index_repair(postgres_engine, monkeypatch):
    engine = postgres_engine
    monkeypatch.setenv("EMBEDDING_DIM", "768")
    migrations.migrate(engine)
    assert migrations.schema_ready(engine)
    assert migrations.schema_version(engine) == migrations.VERSION
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX memories_embedding_hnsw_idx"))
    assert not migrations.schema_ready(engine)
    migrations.migrate(engine)
    assert migrations.schema_ready(engine)
    monkeypatch.setenv("EMBEDDING_DIM", "1536")
    assert not migrations.schema_ready(engine)
    with pytest.raises(RuntimeError, match="incompatible"):
        migrations.migrate(engine)
    assert migrations.schema_version(engine) == migrations.VERSION
    monkeypatch.setenv("EMBEDDING_DIM", "768")
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE memories DROP COLUMN embedding_vector CASCADE")
        )
    assert not migrations.schema_ready(engine)
    with pytest.raises(RuntimeError, match="incompatible"):
        migrations.migrate(engine)


def test_native_legacy_upgrade_preserves_source_and_vectors(postgres_engine):
    engine = postgres_engine
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT, category TEXT, tags_json TEXT, embedding_json TEXT, created_at TEXT, last_accessed TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO memories VALUES ('legacy', 'kept source', 'general', '[]', '[]', 'now', 'now')"
            )
        )
    migrations.migrate(engine)
    migrations.migrate(engine)
    with engine.begin() as connection:
        row = connection.execute(text("SELECT content, media_type FROM memories")).one()
        assert tuple(row) == ("kept source", "text")
        vector = "[" + ",".join(["1"] + ["0"] * 767) + "]"
        connection.execute(
            text(
                "UPDATE memories SET embedding_vector = CAST(:vector AS vector) WHERE id = :id"
            ),
            {"vector": vector, "id": "legacy"},
        )
        assert (
            connection.execute(
                text("SELECT vector_dims(embedding_vector) FROM memories")
            ).scalar_one()
            == 768
        )
    assert migrations.schema_ready(engine)


def test_native_failed_migration_rolls_back_schema(postgres_engine, monkeypatch):
    engine = postgres_engine

    def fail(connection):
        connection.execute(text("CREATE TABLE uncommitted_migration (id INTEGER)"))
        raise RuntimeError("injected failure")

    monkeypatch.setattr(migrations, "_upgrade", fail)
    with pytest.raises(RuntimeError, match="injected failure"):
        migrations.migrate(engine)
    assert migrations.schema_version(engine) == 0
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT to_regclass('uncommitted_migration')")
            ).scalar_one()
            is None
        )


def test_full_application_boots_with_standard_postgresql_url(postgres_engine):
    import subprocess
    import sys

    with postgres_engine.connect() as connection:
        namespace = connection.execute(text("SELECT current_schema()")).scalar_one()
    url = make_url(os.environ["GIGAMIND_TEST_POSTGRES_URL"]).set(
        drivername="postgresql"
    )
    url = url.update_query_dict({"options": f"-csearch_path={namespace},public"})
    environment = {
        **os.environ,
        "PYTHON_DOTENV_DISABLED": "1",
        "DATABASE_URL": url.render_as_string(hide_password=False),
        "ENVIRONMENT": "production",
        "GIGAMIND_API_KEY": "local-application-boot-fixture",
        "EMBEDDING_DIM": "768",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from fastapi.testclient import TestClient\n"
            "from gigamind.main import app\n"
            "from gigamind.db.database import is_postgres\n"
            "assert is_postgres\n"
            "with TestClient(app) as client:\n"
            "    response = client.get('/health/ready')\n"
            "    assert response.status_code == 200, response.text\n",
        ],
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_approval_race_preserves_one_active_fact(postgres_engine, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    from sqlmodel import Session, select
    from gigamind.security import Actor
    from gigamind.services import trust
    from gigamind.db.trust_models import AcceptedKnowledge, MemoryProposal

    migrations.migrate(postgres_engine)
    monkeypatch.setattr(trust, "engine", postgres_engine)
    actor = Actor("native-reviewer", set(), None, True)
    proposals = [
        trust.create_proposal(
            actor,
            content=value,
            subject="native-stack",
            evidence=[],
            idempotency_key=value,
        )["proposal"]
        for value in ("python", "typescript")
    ]
    barrier = Barrier(2)
    original = trust.conflicts

    def synchronized(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(trust, "conflicts", synchronized)

    def approve(proposal):
        try:
            return trust.resolve_proposal(
                actor, proposal["id"], action="approve", expected_revision=1
            )
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(2) as executor:
        outcomes = list(executor.map(approve, proposals))
    assert sum(isinstance(result, dict) for result in outcomes) == 1
    assert 409 in outcomes
    with Session(postgres_engine) as session:
        assert (
            len(
                session.exec(
                    select(AcceptedKnowledge).where(
                        AcceptedKnowledge.status == "accepted"
                    )
                ).all()
            )
            == 1
        )
        assert sorted(
            proposal.status for proposal in session.exec(select(MemoryProposal)).all()
        ) == ["accepted", "proposed"]


def test_native_memory_indexing_is_revision_consistent(postgres_engine, monkeypatch):
    from fastapi import HTTPException
    from sqlmodel import Session, select
    from gigamind.services import memory
    from gigamind.db.database import MemoryItem
    from gigamind.db.memory_index import MemoryIndexState

    monkeypatch.setenv("EMBEDDING_DIM", "3")
    monkeypatch.setattr(memory, "engine", postgres_engine)
    monkeypatch.setattr(memory, "is_postgres", True)
    monkeypatch.setattr(memory.embedding_config, "DEFAULT_DIM", 3)
    calls = []
    monkeypatch.setattr(
        memory,
        "generate_embedding",
        lambda source: calls.append(source) or [1.0, 0.0, 0.0],
    )
    migrations.migrate(postgres_engine)
    saved = memory.add_memory(
        "original long source " * 100, attachments=[{"key": "native/shared.pdf"}]
    )
    assert saved["index_status"] == "completed", saved
    assert len(calls) == saved["total_chunks"] > 1
    with postgres_engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    "SELECT vector_dims(embedding_vector) FROM memories WHERE parent_id=:id"
                ),
                {"id": saved["id"]},
            )
            .scalars()
            .all()
        )
        assert rows and all(dimension == 3 for dimension in rows)
    updated = memory.update_memory(
        saved["id"], content="replacement", expected_revision=1
    )
    assert updated["index_status"] == "completed"
    assert updated["indexed_revision"] == updated["revision"] == 2
    with postgres_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM memories WHERE parent_id=:id"),
                {"id": saved["id"]},
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text("SELECT vector_dims(embedding_vector) FROM memories WHERE id=:id"),
                {"id": saved["id"]},
            ).scalar_one()
            == 3
        )
    with pytest.raises(HTTPException) as stale:
        memory.update_memory(saved["id"], content="stale", expected_revision=1)
    assert stale.value.status_code == 409
    monkeypatch.setattr(
        memory,
        "generate_embedding",
        lambda source: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )
    failed = memory.update_memory(
        saved["id"], content="new durable source", expected_revision=2
    )
    assert failed["index_status"] == "failed"
    with Session(postgres_engine) as session:
        assert session.get(MemoryItem, saved["id"]).content == "new durable source"
        assert session.get(MemoryIndexState, saved["id"]).indexed_revision is None
    with postgres_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT embedding_vector FROM memories WHERE id=:id"),
                {"id": saved["id"]},
            ).scalar_one()
            is None
        )
