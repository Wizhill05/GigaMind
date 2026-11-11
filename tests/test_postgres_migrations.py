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


def test_native_file_publication_rolls_back_and_clears_vectors(
    postgres_engine, monkeypatch
):
    from sqlalchemy.exc import DBAPIError
    from gigamind.services import indexing

    monkeypatch.setenv("EMBEDDING_DIM", "3")
    monkeypatch.setattr(indexing, "engine", postgres_engine)
    monkeypatch.setattr(indexing, "is_postgres", True)
    monkeypatch.setattr(indexing.embedding, "DEFAULT_DIM", 3)
    monkeypatch.setattr(indexing, "generate_embedding", lambda **kw: [1.0, 2.0, 3.0])
    migrations.migrate(postgres_engine)
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE publication_probe (id INTEGER PRIMARY KEY, publications INTEGER NOT NULL)"
            )
        )
        connection.execute(text("INSERT INTO publication_probe VALUES (1, 0)"))

    def guard(session):
        session.execute(
            text("UPDATE publication_probe SET publications=publications+1 WHERE id=1")
        )

    original = indexing.index_file_content(
        "native/key",
        "source.txt",
        b"original paragraph " * 300,
        mime_type="text/plain",
        publication_guard=guard,
    )
    assert original["status"] == "completed" and original["chunks_created"] > 1

    def snapshot():
        with postgres_engine.connect() as connection:
            file = tuple(
                connection.execute(
                    text(
                        "SELECT id, document_summary, total_chunks, indexing_status, embedding_vector::text FROM storage_files"
                    )
                ).one()
            )
            chunks = [
                tuple(row)
                for row in connection.execute(
                    text(
                        "SELECT id, file_id, content, embedding_vector::text FROM storage_chunks ORDER BY chunk_index"
                    )
                )
            ]
            count = connection.execute(
                text("SELECT publications FROM publication_probe")
            ).scalar_one()
            return file, chunks, count

    before = snapshot()
    assert before[2] == 1 and len(before[1]) == original["chunks_created"]
    assert all(
        row[1] == original["file_id"] and row[-1] == "[1,2,3]" for row in before[1]
    )
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""CREATE FUNCTION deny_vector_publication() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'injected native vector failure'; RETURN NEW; END; $$""")
        )
        connection.execute(
            text(
                "CREATE TRIGGER publication_failure BEFORE UPDATE OF embedding_vector ON storage_chunks FOR EACH ROW EXECUTE FUNCTION deny_vector_publication()"
            )
        )
    monkeypatch.setattr(indexing, "generate_embedding", lambda **kw: [3.0, 2.0, 1.0])
    with pytest.raises(DBAPIError, match="injected native vector failure"):
        indexing.index_file_content(
            "native/key",
            "source.txt",
            b"replacement",
            mime_type="text/plain",
            publication_guard=guard,
        )
    assert snapshot() == before
    with postgres_engine.begin() as connection:
        connection.execute(text("DROP TRIGGER publication_failure ON storage_chunks"))
    replaced = indexing.index_file_content(
        "native/key",
        "source.txt",
        b"replacement",
        mime_type="text/plain",
        publication_guard=guard,
    )
    assert replaced["file_id"] == original["file_id"]
    after = snapshot()
    assert after[0][-1] == "[3,2,1]" and len(after[1]) == 1 and after[2] == 2
    assert after[1][0][-1] == "[3,2,1]"
    empty = indexing.index_file_content(
        "native/key", "source.txt", b"", mime_type="text/plain", publication_guard=guard
    )
    assert empty["file_id"] == original["file_id"] and empty["status"] == "empty"
    cleared = snapshot()
    assert cleared[0][2:] == (0, "empty", None) and cleared[1] == [] and cleared[2] == 3


def test_native_queue_claims_and_lease_fencing(postgres_engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlmodel import Session
    from gigamind.services import jobs

    migrations.migrate(postgres_engine)
    barrier = Barrier(2)

    def enqueue(_):
        barrier.wait(timeout=5)
        return jobs.enqueue(
            "index_file",
            {"key": "native/source.txt"},
            "same-request",
            engine=postgres_engine,
        ).id

    with ThreadPoolExecutor(2) as executor:
        ids = list(executor.map(enqueue, range(2)))
    assert ids[0] == ids[1]
    barrier = Barrier(2)

    def claim(_):
        barrier.wait(timeout=5)
        return jobs.claim(engine=postgres_engine)

    with ThreadPoolExecutor(2) as executor:
        claimed = list(executor.map(claim, range(2)))
    assert sum(item is not None for item in claimed) == 1
    owner = next(item for item in claimed if item is not None)
    with Session(postgres_engine) as session:
        jobs.JobLease(owner.id, owner.lease_token).publication_guard(session)
        session.commit()
    assert jobs.cancel_resource("native/source.txt", engine=postgres_engine) == 1
    with Session(postgres_engine) as session, pytest.raises(jobs.PermanentFailure):
        jobs.JobLease(owner.id, owner.lease_token).publication_guard(session)
    assert not jobs.guarded(
        owner.id, owner.lease_token, {"state": "completed"}, engine=postgres_engine
    )


def test_native_conversation_import_is_idempotent_and_unindexed(
    postgres_engine, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from gigamind.services import memory

    migrations.migrate(postgres_engine)
    monkeypatch.setattr(memory, "engine", postgres_engine)
    monkeypatch.setattr(
        memory,
        "generate_embedding",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("provider called")),
    )
    data = {
        "id": "full-native-source-identifier",
        "create_time": 1700000000,
        "messages": [{"role": "user", "content": "preserve this source"}],
    }
    barrier = Barrier(2)

    def run(_):
        barrier.wait(timeout=5)
        return memory.import_conversations_data(data)

    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(run, range(2)))
    assert sum(r["ingested"] for r in results) == 1
    assert sum(r["skipped"] for r in results) == 1
    with postgres_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT embedding_json, embedding_vector, created_at FROM conversations"
            )
        ).one()
    assert tuple(row) == ("[]", None, "2023-11-14T22:13:20+00:00")


def test_native_transcript_search_filters_before_candidates_and_unions_text(
    postgres_engine, monkeypatch
):
    import json
    from sqlalchemy.exc import DBAPIError
    from sqlmodel import Session
    from gigamind.db.database import ConversationItem
    from gigamind.services import memory

    monkeypatch.setenv("EMBEDDING_DIM", "2")
    monkeypatch.setattr(memory, "engine", postgres_engine)
    monkeypatch.setattr(memory, "is_postgres", True)
    monkeypatch.setattr(memory.embedding_config, "DEFAULT_DIM", 2)
    monkeypatch.setattr(memory, "generate_embedding", lambda *args: [1.0, 0.0])
    migrations.migrate(postgres_engine)
    with Session(postgres_engine) as session:
        for i in range(65):
            session.add(
                ConversationItem(
                    id=f"hidden-{i}",
                    platform="Other" if i % 2 else "Claude",
                    source_agent="GPT" if i % 2 else "other",
                    title="ordinary",
                    summary="",
                    created_at="2024-01-01T00:00:00+00:00",
                    messages_json="[]",
                )
            )
        session.add(
            ConversationItem(
                id="semantic-visible",
                platform="Claude",
                source_agent="GPT",
                title="ordinary",
                summary="",
                created_at="2024-01-01T00:00:00+00:00",
                messages_json="[]",
            )
        )
        session.add(
            ConversationItem(
                id="text-visible",
                platform="Claude",
                source_agent="GPT",
                title="ordinary",
                summary="",
                created_at="2024-01-01T00:00:00+00:00",
                messages_json=json.dumps(
                    [
                        {
                            "role": "assistant",
                            "content": "x" * 500 + " needle",
                            "id": "last-source-node",
                        }
                    ]
                ),
            )
        )
        session.flush()
        session.execute(
            text(
                "UPDATE conversations SET embedding_vector='[1,0]'::vector WHERE id LIKE 'hidden-%'"
            )
        )
        session.execute(
            text(
                "UPDATE conversations SET embedding_vector='[0.9,0.1]'::vector WHERE id='semantic-visible'"
            )
        )
        session.commit()
    found = memory.search_conversations(
        "synonym", platform="claude", source_agent="gpt"
    )
    assert [item["id"] for item in found] == ["semantic-visible"]
    assert found[0]["retrieval_method"] == "vector"
    combined = memory.search_conversations(
        "needle", platform="claude", source_agent="gpt", limit=1
    )
    assert [item["id"] for item in combined] == ["text-visible"]
    assert combined[0]["evidence"][0]["id"] == "last-source-node"
    assert "needle" in combined[0]["evidence"][0]["text"]
    with postgres_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE conversations DROP COLUMN embedding_vector CASCADE")
        )
    with pytest.raises(DBAPIError, match="embedding_vector"):
        memory.search_conversations("needle")


def test_native_worker_bootstrap_registers_all_models(postgres_engine, monkeypatch):
    import subprocess
    import sys
    from gigamind.db import jobs, memory_index
    from gigamind import security

    monkeypatch.setenv("EMBEDDING_DIM", "2")
    with postgres_engine.connect() as connection:
        namespace = connection.execute(text("SELECT current_schema()")).scalar_one()
    url = make_url(os.environ["GIGAMIND_TEST_POSTGRES_URL"]).set(
        drivername="postgresql"
    )
    url = url.update_query_dict({"options": f"-csearch_path={namespace},public"})
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.getcwd(),
        "PYTHON_DOTENV_DISABLED": "1",
        "DATABASE_URL": url.render_as_string(hide_password=False),
        "ENVIRONMENT": "production",
        "EMBEDDING_DIM": "2",
    }
    run = subprocess.run(
        [sys.executable, "-m", "gigamind.cli.worker", "--once"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "Worker ready" in run.stdout and migrations.schema_ready(postgres_engine)


def test_native_latest_resource_owner_and_conflict_rollback(postgres_engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlmodel import Session
    from gigamind.services import jobs

    migrations.migrate(postgres_engine)
    barrier = Barrier(2)

    def enqueue(key):
        barrier.wait(timeout=5)
        return jobs.enqueue(
            "index_file", {"key": "native/source.txt"}, key, engine=postgres_engine
        )

    with ThreadPoolExecutor(2) as executor:
        requests = list(executor.map(enqueue, ("one", "two")))
    current = next(
        job
        for job in requests
        if jobs.status(job.id, engine=postgres_engine).state == "queued"
    )
    old = next(job for job in requests if job.id != current.id)
    assert jobs.status(old.id, engine=postgres_engine).state == "cancelled"
    assert (
        jobs.enqueue(
            "index_file",
            {"key": "native/source.txt"},
            old.idempotency_key,
            engine=postgres_engine,
        ).id
        == old.id
    )
    with pytest.raises(jobs.Conflict):
        jobs.enqueue(
            "index_file",
            {"key": "other.txt"},
            current.idempotency_key,
            engine=postgres_engine,
        )
    with Session(postgres_engine) as session:
        assert (
            session.get(jobs.ResourceJobState, "native/source.txt").current_job_id
            == current.id
        )
        assert session.get(jobs.ResourceJobState, "other.txt") is None
    assert jobs.status(current.id, engine=postgres_engine).state == "queued"


def test_native_stale_resource_publisher_cannot_resurrect_after_forgetting(
    postgres_engine, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from sqlmodel import Session, select
    from gigamind.db.database import StorageChunkItem, StorageFileItem
    from gigamind.services import jobs, indexing

    monkeypatch.setenv("EMBEDDING_DIM", "3")
    monkeypatch.setattr(indexing, "engine", postgres_engine)
    monkeypatch.setattr(indexing, "is_postgres", True)
    monkeypatch.setattr(indexing.embedding, "DEFAULT_DIM", 3)
    monkeypatch.setattr(indexing.storage_service, "is_enabled", lambda: True)
    contents = [b"old source"]
    monkeypatch.setattr(
        indexing.storage_service, "download_file", lambda key: contents[0]
    )
    entered, release = Event(), Event()

    def embedding(**kwargs):
        if not entered.is_set():
            entered.set()
            assert release.wait(10)
        return [1.0, 2.0, 3.0]

    monkeypatch.setattr(indexing, "generate_embedding", embedding)
    migrations.migrate(postgres_engine)
    key = "native/source.txt"
    old = jobs.enqueue("index_file", {"key": key}, engine=postgres_engine)
    with ThreadPoolExecutor(1) as executor:
        future = executor.submit(jobs.run_once, engine=postgres_engine)
        try:
            assert entered.wait(10)
            contents[0] = b"new source"
            current = jobs.enqueue("index_file", {"key": key}, engine=postgres_engine)
            assert jobs.run_once(engine=postgres_engine).state == "completed"
        finally:
            release.set()
        assert future.result(timeout=10).state == "cancelled"
    with Session(postgres_engine) as session:
        assert session.exec(select(StorageChunkItem)).one().content == "new source"
        assert session.get(jobs.ResourceJobState, key).current_job_id == current.id
    with postgres_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT embedding_vector::text FROM storage_files")
            ).scalar_one()
            == "[1,2,3]"
        )
    assert jobs.status(old.id, engine=postgres_engine).state == "cancelled"
    jobs.forget_resource(key, engine=postgres_engine)
    indexing.delete_storage_file_index(key)
    postgres_engine.dispose()
    with pytest.raises(jobs.Conflict):
        jobs.enqueue("index_file", {"key": key}, engine=postgres_engine)
    with Session(postgres_engine) as session:
        assert session.exec(select(StorageFileItem)).all() == []
        assert session.exec(select(StorageChunkItem)).all() == []
        assert session.get(jobs.ResourceJobState, key).deleted


def test_native_credential_upgrade_also_creates_late_tables(
    postgres_engine, monkeypatch
):
    import hashlib
    import json
    from gigamind import security
    from gigamind.db.jobs import ResourceJobState

    monkeypatch.setenv("EMBEDDING_DIM", "3")
    migrations.migrate(postgres_engine)
    token = "gm_native-legacy-test-key"
    digest = hashlib.sha256(token.encode()).hexdigest()
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO client_credentials (id,name,token_hash,scopes_json,project_ids_json,revoked,revision) VALUES (:id,:name,:hash,:scopes,:projects,false,0)"
            ),
            {
                "id": "legacy-client",
                "name": "legacy",
                "hash": digest,
                "scopes": json.dumps(["memory:read"]),
                "projects": json.dumps(["p"]),
            },
        )
        for column in ("created_at", "expires_at", "last_used_at", "revision"):
            connection.execute(
                text(f"ALTER TABLE client_credentials DROP COLUMN {column}")
            )
        connection.execute(text("DROP TABLE resource_job_state"))
        connection.execute(text("DELETE FROM schema_migrations"))
        connection.execute(text("INSERT INTO schema_migrations VALUES (1)"))
    migrations.migrate(postgres_engine)
    assert migrations.schema_ready(postgres_engine)
    with postgres_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT token_hash, created_at, expires_at, last_used_at, revision FROM client_credentials"
            )
        ).one()
        assert tuple(row) == (digest, None, None, None, 0)
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM resource_job_state")
            ).scalar_one()
            == 0
        )
    monkeypatch.setattr(security, "engine", postgres_engine)
    assert security.get_actor("Bearer " + token).project_ids == {"p"}


def test_native_rotation_and_revocation_race(postgres_engine, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    from gigamind import main, security

    monkeypatch.setenv("EMBEDDING_DIM", "3")
    migrations.migrate(postgres_engine)
    monkeypatch.setattr(main, "engine", postgres_engine)
    monkeypatch.setattr(security, "engine", postgres_engine)
    monkeypatch.setenv("GIGAMIND_API_KEY", "native-client-admin")
    admin = {"Authorization": "Bearer native-client-admin"}
    with TestClient(main.app) as http:
        body = {"name": "native", "scopes": ["memory:read"], "project_ids": ["p"]}
        client = http.post("/api/v1/admin/clients", headers=admin, json=body).json()
        path = "/api/v1/admin/clients/" + client["client"]["id"]
        barrier = Barrier(2)

        def rotate(_):
            barrier.wait(timeout=5)
            return http.post(
                path + "/rotate", headers=admin, json={"expected_revision": 0}
            )

        with ThreadPoolExecutor(2) as executor:
            responses = list(executor.map(rotate, range(2)))
        assert sorted(item.status_code for item in responses) == [200, 409]
        winner = next(item.json() for item in responses if item.status_code == 200)
        assert winner["client"]["revision"] == 1
        assert (
            security.get_actor("Bearer " + winner["token"]).id == client["client"]["id"]
        )
        with pytest.raises(HTTPException) as rejected:
            security.get_actor("Bearer " + client["token"])
        assert rejected.value.status_code == 401
        barrier = Barrier(2)

        def change(action):
            barrier.wait(timeout=5)
            return http.post(
                path + "/" + action,
                headers=admin,
                json={"expected_revision": 1} if action == "rotate" else None,
            )

        with ThreadPoolExecutor(2) as executor:
            rotation, revocation = list(executor.map(change, ("rotate", "revoke")))
        assert rotation.status_code in (200, 409) and revocation.status_code == 200
        tokens = [winner["token"]]
        if rotation.status_code == 200:
            tokens.append(rotation.json()["token"])
        for token in tokens:
            with pytest.raises(HTTPException) as denied:
                security.get_actor("Bearer " + token)
            assert denied.value.status_code == 401


def test_native_activity_total_excludes_other_projects(postgres_engine, monkeypatch):
    from sqlmodel import Session
    from gigamind.security import Actor
    from gigamind.db.trust_models import ActivityEvent
    from gigamind.services import trust

    migrations.migrate(postgres_engine)
    monkeypatch.setattr(trust, "engine", postgres_engine)
    with Session(postgres_engine) as session:
        for ident, project in (
            ("a", "p"),
            ("b", "p"),
            ("hidden", "other"),
            ("global", None),
        ):
            session.add(
                ActivityEvent(
                    id=ident,
                    project_id=project,
                    writer_id="test",
                    action="propose",
                    target_id="target",
                    created_at="2026-01-01T00:00:00Z",
                    updated_at="2026-01-01T00:00:00Z",
                )
            )
        session.commit()
    reader = Actor("reader", {"memory:read"}, {"p"})
    first = trust.list_activity(reader, limit=1)
    second = trust.list_activity(reader, limit=1, offset=1)
    assert first["total"] == second["total"] == 2
    assert [first["events"][0]["id"], second["events"][0]["id"]] == ["b", "a"]


def test_native_cleanup_and_attachment_races(postgres_engine, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from fastapi import HTTPException
    from sqlmodel import Session, select
    from gigamind.db.database import MemoryItem
    from gigamind.security import Actor
    from gigamind.services import memory, file_lifecycle, jobs
    from gigamind.services.storage import storage_service

    monkeypatch.setenv("EMBEDDING_DIM", "3")
    monkeypatch.setattr(memory, "engine", postgres_engine)
    monkeypatch.setattr(memory, "is_postgres", True)
    monkeypatch.setattr(memory.embedding_config, "DEFAULT_DIM", 3)
    monkeypatch.setattr(memory, "generate_embedding", lambda *args: [1.0, 2.0, 3.0])
    monkeypatch.setattr(storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        storage_service, "get_presigned_download_url", lambda *a, **k: None
    )
    migrations.migrate(postgres_engine)
    actor = Actor("native-cleanup-admin", set(), None, True)
    objects = {"shared": b"bytes"}
    renewed = Event()
    heartbeat = jobs.heartbeat

    def observe_renewal(*args, **kwargs):
        result = heartbeat(*args, **kwargs)
        if result:
            renewed.set()
        return result

    monkeypatch.setattr(jobs, "heartbeat", observe_renewal)

    def remove(key):
        assert renewed.wait(5), "cleanup I/O blocked renewal"
        objects.pop(key, None)
        return True

    monkeypatch.setattr(storage_service, "delete_file", remove)
    first = memory.add_memory("first source", file_keys=["shared"])
    second = memory.add_memory("second source", file_keys=["shared"])
    with pytest.raises(HTTPException) as blocked:
        file_lifecycle.request_delete(actor, "shared", postgres_engine)
    assert blocked.value.status_code == 409 and objects["shared"] == b"bytes"
    memory.delete_memory(first["id"])
    with pytest.raises(HTTPException):
        file_lifecycle.request_delete(actor, "shared", postgres_engine)
    memory.delete_memory(second["id"])
    cleanup = file_lifecycle.request_delete(actor, "shared", postgres_engine)
    assert objects["shared"] == b"bytes"
    assert jobs.run_once(engine=postgres_engine, lease_seconds=1).state == "completed"
    assert (
        not objects
        and file_lifecycle.request_delete(actor, "shared", postgres_engine).id
        == cleanup.id
    )

    registered, release, delete_attempted = Event(), Event(), Event()
    register = memory._register_attachment_metadata
    lock = jobs.lock_resource

    def hold_registration(*args, **kwargs):
        register(*args, **kwargs)
        registered.set()
        assert release.wait(5)

    def observe_lock(*args, **kwargs):
        if registered.is_set() and not release.is_set():
            delete_attempted.set()
        return lock(*args, **kwargs)

    monkeypatch.setattr(memory, "_register_attachment_metadata", hold_registration)
    monkeypatch.setattr(jobs, "lock_resource", observe_lock)
    with ThreadPoolExecutor(2) as executor:
        attached = executor.submit(
            memory.add_memory, "attachment wins", file_keys=["attachment-first"]
        )
        assert registered.wait(5)
        deleting = executor.submit(
            file_lifecycle.request_delete, actor, "attachment-first", postgres_engine
        )
        try:
            assert delete_attempted.wait(5)
        finally:
            release.set()
        assert attached.result(timeout=10)["index_status"] == "completed"
        with pytest.raises(HTTPException) as rejected:
            deleting.result(timeout=10)
        assert rejected.value.status_code == 409
    monkeypatch.setattr(memory, "_register_attachment_metadata", register)
    monkeypatch.setattr(jobs, "lock_resource", lock)

    locked, release_cleanup, attachment_attempted = Event(), Event(), Event()
    references = file_lifecycle.referenced

    def hold_cleanup(session, key):
        if key == "cleanup-first":
            locked.set()
            assert release_cleanup.wait(5)
        return references(session, key)

    def observe_registration(*args, **kwargs):
        attachment_attempted.set()
        return register(*args, **kwargs)

    monkeypatch.setattr(file_lifecycle, "referenced", hold_cleanup)
    monkeypatch.setattr(memory, "_register_attachment_metadata", observe_registration)
    with ThreadPoolExecutor(2) as executor:
        deleting = executor.submit(
            file_lifecycle.request_delete, actor, "cleanup-first", postgres_engine
        )
        assert locked.wait(5)
        attached = executor.submit(
            memory.add_memory, "must roll back", file_keys=["cleanup-first"]
        )
        try:
            assert attachment_attempted.wait(5)
        finally:
            release_cleanup.set()
        assert deleting.result(timeout=10).state == "queued"
        with pytest.raises(HTTPException) as rejected:
            attached.result(timeout=10)
        assert rejected.value.status_code == 409
    with Session(postgres_engine) as session:
        rows = session.exec(
            select(MemoryItem).where(MemoryItem.parent_id.is_(None))
        ).all()
        assert [row.content for row in rows] == ["attachment wins"]


def test_native_download_admission_is_ordered_against_forgetting(
    postgres_engine, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from fastapi import HTTPException
    from gigamind.security import Actor
    from gigamind.services import file_lifecycle, jobs
    from gigamind.services.storage import storage_service

    monkeypatch.setenv("EMBEDDING_DIM", "3")
    migrations.migrate(postgres_engine)
    actor = Actor("download-admin", set(), None, True)
    admitted, release, delete_attempted = Event(), Event(), Event()
    calls = []
    original_lock = jobs.lock_resource

    def sign(key, **options):
        calls.append(key)
        admitted.set()
        assert release.wait(5), "download test did not release signer"
        return "https://example.test/" + key

    def observe_lock(session, key, now):
        if admitted.is_set() and not release.is_set():
            delete_attempted.set()
        return original_lock(session, key, now)

    monkeypatch.setattr(storage_service, "get_presigned_download_url", sign)
    monkeypatch.setattr(jobs, "lock_resource", observe_lock)
    with ThreadPoolExecutor(2) as pool:
        download = pool.submit(
            file_lifecycle.download_url, "url-first", engine=postgres_engine
        )
        assert admitted.wait(5)
        deletion = pool.submit(
            file_lifecycle.request_delete, actor, "url-first", postgres_engine
        )
        try:
            assert delete_attempted.wait(5)
        finally:
            release.set()
        assert download.result(timeout=10) == "https://example.test/url-first"
        assert deletion.result(timeout=10).state == "queued"
    with pytest.raises(HTTPException) as denied:
        file_lifecycle.download_url("url-first", engine=postgres_engine)
    assert denied.value.status_code == 409 and calls == ["url-first"]

    deletion_locked, release_delete, download_attempted = Event(), Event(), Event()
    original_referenced = file_lifecycle.referenced

    def hold_reference_check(session, key):
        if key == "delete-first":
            deletion_locked.set()
            assert release_delete.wait(5), "download test did not release deletion"
        return original_referenced(session, key)

    def observe_download(session, key, now):
        if key == "delete-first" and deletion_locked.is_set():
            download_attempted.set()
        return original_lock(session, key, now)

    monkeypatch.setattr(file_lifecycle, "referenced", hold_reference_check)
    monkeypatch.setattr(jobs, "lock_resource", observe_download)
    with ThreadPoolExecutor(2) as pool:
        deletion = pool.submit(
            file_lifecycle.request_delete, actor, "delete-first", postgres_engine
        )
        assert deletion_locked.wait(5)
        download = pool.submit(
            file_lifecycle.download_url, "delete-first", engine=postgres_engine
        )
        try:
            assert download_attempted.wait(5)
        finally:
            release_delete.set()
        assert deletion.result(timeout=10).state == "queued"
        with pytest.raises(HTTPException) as denied:
            download.result(timeout=10)
        assert denied.value.status_code == 409
    assert calls == ["url-first"]


def test_native_upload_preparation_is_atomic_and_repeatable(
    postgres_engine, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi import HTTPException
    from sqlmodel import Session, select
    from gigamind.db.database import StorageFileItem
    from gigamind.db.jobs import Job, ResourceJobState
    from gigamind.services import file_uploads, jobs

    monkeypatch.setenv("EMBEDDING_DIM", "3")
    migrations.migrate(postgres_engine)

    def prepare():
        return file_uploads.prepare_upload(
            "files/native.txt",
            "native.txt",
            "text/plain",
            "text",
            3,
            "test-admin",
            "native-upload",
            engine=postgres_engine,
        )

    with ThreadPoolExecutor(2) as pool:
        first, second = list(pool.map(lambda _: prepare(), range(2)))
    assert first == second
    with Session(postgres_engine) as session:
        assert len(session.exec(select(Job)).all()) == 1
        assert session.exec(select(StorageFileItem)).one().indexing_status == "pending"
        assert (
            session.get(ResourceJobState, "files/native.txt").current_job_id
            == first[1]["id"]
        )
    assert jobs.claim(engine=postgres_engine) is None
    acknowledged = file_uploads.acknowledge_upload(
        "files/native.txt", first[1]["id"], engine=postgres_engine
    )
    assert (
        file_uploads.acknowledge_upload(
            "files/native.txt", first[1]["id"], engine=postgres_engine
        )
        == acknowledged
    )
    claimed = jobs.claim(engine=postgres_engine)
    assert claimed.id == first[1]["id"]
    file_uploads.acknowledge_upload(
        "files/native.txt", claimed.id, engine=postgres_engine
    )
    assert (
        jobs.status(claimed.id, engine=postgres_engine).lease_token
        == claimed.lease_token
    )
    jobs.forget_resource("files/native.txt", engine=postgres_engine)
    with pytest.raises(HTTPException) as denied:
        file_uploads.acknowledge_upload(
            "files/native.txt", claimed.id, engine=postgres_engine
        )
    assert denied.value.status_code == 409
    assert jobs.status(claimed.id, engine=postgres_engine).state == "cancelled"


def test_native_v2_upload_manifest_upgrade_and_single_admission(
    postgres_engine, monkeypatch
):
    import hashlib
    from concurrent.futures import ThreadPoolExecutor
    from sqlmodel import Session
    from gigamind.db.database import StorageFileItem
    from gigamind.db.jobs import UploadManifest
    from gigamind.services import file_uploads, jobs
    from sqlalchemy import inspect

    monkeypatch.setenv("EMBEDDING_DIM", "3")
    migrations.migrate(postgres_engine)
    with Session(postgres_engine) as session:
        session.add(
            StorageFileItem(
                id="legacy-file",
                key="legacy.txt",
                filename="legacy.txt",
                created_at="old",
                updated_at="old",
                document_summary="preserve this",
            )
        )
        session.commit()
    with postgres_engine.begin() as connection:
        UploadManifest.__table__.drop(connection)
        connection.execute(text("DELETE FROM schema_migrations"))
        connection.execute(text("INSERT INTO schema_migrations (version) VALUES (2)"))
    migrations.migrate(postgres_engine)
    assert "upload_manifests" in inspect(postgres_engine).get_table_names()
    assert migrations.schema_version(postgres_engine) == 3
    with Session(postgres_engine) as session:
        assert (
            session.get(StorageFileItem, "legacy-file").document_summary
            == "preserve this"
        )
    _, job = file_uploads.prepare_upload(
        "manifest.txt",
        "manifest.txt",
        "text/plain",
        "text",
        3,
        "admin",
        "manifest-upgrade",
        sha256=hashlib.sha256(b"abc").hexdigest(),
        engine=postgres_engine,
    )
    with ThreadPoolExecutor(2) as pool:
        admitted = list(
            pool.map(
                lambda _: file_uploads.begin_upload(
                    "manifest.txt", job["id"], engine=postgres_engine
                ),
                range(2),
            )
        )
    assert sorted(admitted) == [False, True]
    assert jobs.claim(engine=postgres_engine) is None
    assert not file_uploads.verify_upload(
        "manifest.txt", job["id"], b"xyz", engine=postgres_engine
    )
    assert file_uploads.verify_upload(
        "manifest.txt", job["id"], b"abc", engine=postgres_engine
    )
    file_uploads.acknowledge_upload("manifest.txt", job["id"], engine=postgres_engine)
    claimed = jobs.claim(engine=postgres_engine)
    assert claimed.id == job["id"]
    with Session(postgres_engine) as session:
        jobs.JobLease(claimed.id, claimed.lease_token).publication_guard(session)
    assert not file_uploads.verify_upload(
        "manifest.txt", job["id"], None, engine=postgres_engine
    )
    with Session(postgres_engine) as session:
        with pytest.raises(jobs.PermanentFailure, match="not been verified"):
            jobs.JobLease(claimed.id, claimed.lease_token).publication_guard(session)
