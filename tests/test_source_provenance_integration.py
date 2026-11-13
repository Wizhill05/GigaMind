"""Authoritative legacy source writes and attribution commit together."""

import pytest
from sqlalchemy import create_engine
from gigamind import security
from gigamind.db import migrations
from gigamind.services import memory, source_provenance
from gigamind.security import Actor


@pytest.fixture
def provenance_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'provenance.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    migrations.migrate(engine)
    monkeypatch.setattr(memory, "engine", engine)
    monkeypatch.setattr(memory, "is_postgres", False)
    monkeypatch.setattr(security, "engine", engine)
    monkeypatch.setattr(memory.embedding_config, "DEFAULT_DIM", 3)
    monkeypatch.setattr(memory, "generate_embedding", lambda *a, **kw: [1.0, 0.0, 0.0])
    yield engine
    engine.dispose()


def test_create_edit_delete_preserve_authenticated_creator(provenance_db):
    creator = Actor("real-creator", {"admin"}, None, True)
    editor = Actor("real-editor", {"admin"}, None, True)
    row = memory.add_memory(
        "private source", source_agent="claimed-agent", actor=creator
    )
    assert row["index_status"] == "completed"
    memory.update_memory(
        row["id"], content="replacement source", actor=editor, expected_revision=1
    )
    result = source_provenance.read_provenance(provenance_db, "memory", row["id"])
    assert result["head"]["creator_id"] == creator.id
    assert result["receipts"][0]["writer_id"] == editor.id
    assert [receipt["source_revision"] for receipt in result["receipts"]] == ["2", "1"]
    assert "private source" not in str(result) and "claimed-agent" not in str(result)
    assert memory.delete_memory(row["id"], actor=editor)
    assert not source_provenance.read_provenance(provenance_db, "memory", row["id"])[
        "head"
    ]["active"]


def test_profile_keys_and_existing_ids_remain_distinct(provenance_db):
    from sqlmodel import Session
    from gigamind.db.database import ProfileItem

    creator = Actor("profile-creator", {"admin"}, None, True)
    editor = Actor("profile-editor", {"admin"}, None, True)
    first = memory.set_profile_rule("a b", "original", actor=creator)
    second = memory.set_profile_rule("a_b", "different", actor=editor)
    assert first["id"] != second["id"]
    updated = memory.set_profile_rule(
        "a b", "edited", source_agent="faked-writer", actor=editor
    )
    assert updated["id"] == first["id"]
    history = memory.get_source_provenance("profile", first["id"])
    assert history["head"]["creator_id"] == creator.id
    assert history["receipts"][0]["writer_id"] == editor.id
    with Session(provenance_db) as session:
        session.add(
            ProfileItem(
                id="imported-custom-id", key="imported", value="old", updated_at="old"
            )
        )
        session.commit()
    assert (
        memory.set_profile_rule("imported", "new", actor=editor)["id"]
        == "imported-custom-id"
    )
    history = memory.get_source_provenance("profile", "imported-custom-id")
    assert history["head"]["creator_id"] is None
    assert history["head"]["creator_provenance"] == "legacy_unknown"
    assert memory.delete_profile_rule(first["id"], actor=editor)
    assert not memory.get_source_provenance("profile", first["id"])["head"]["active"]
    recreated = memory.set_profile_rule("a b", "new record", actor=editor)
    assert recreated["id"] != first["id"]
    assert (
        memory.get_source_provenance("profile", recreated["id"])["head"]["creator_id"]
        == editor.id
    )


def test_service_and_failed_indexing_attribution_are_truthful(
    provenance_db, monkeypatch
):
    monkeypatch.setattr(
        memory,
        "generate_embedding",
        lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("private provider failure")
        ),
    )
    row = memory.add_memory(
        "source retained without provider", source_agent="not-authentication"
    )
    assert row["index_status"] == "failed"
    provenance_db.dispose()
    result = memory.get_source_provenance("memory", row["id"])
    assert result["head"]["creator_id"] is None
    assert result["head"]["creator_provenance"] == "unattributed"
    assert (
        result["total"] == 1
        and result["receipts"][0]["writer_provenance"] == "unattributed"
    )
    assert "source retained without provider" not in str(result)


def test_http_actor_cannot_be_spoofed_and_metadata_is_admin_only(provenance_db):
    from fastapi.testclient import TestClient
    from gigamind.main import app

    _, token = security.create_client("scoped", ["memory:read", "memory:write"], ["p"])
    headers = {"Authorization": "Bearer offline-test-master-key"}
    scoped_headers = {"Authorization": "Bearer " + token}
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/add_memory",
            headers=headers,
            json={
                "content": "private HTTP source",
                "source_agent": "forged-writer",
                "writer_id": "forged-writer",
            },
        )
        assert response.status_code == 200, response.text
        row = response.json()["memory"]
        url = f"/api/v1/sources/memory/{row['id']}/provenance"
        assert client.get(url).status_code == 401
        assert client.get(url, headers=scoped_headers).status_code == 403
        assert (
            client.put(
                f"/api/v1/memories/{row['id']}",
                headers=scoped_headers,
                json={"content": "denied"},
            ).status_code
            == 403
        )
        result = client.get(url, headers=headers).json()
        assert (
            result["head"]["creator_id"]
            == result["receipts"][0]["writer_id"]
            == "master"
        )
        assert "private HTTP source" not in str(result) and "forged-writer" not in str(
            result
        )
        response = client.put(
            f"/api/v1/memories/{row['id']}",
            headers=headers,
            json={"content": "HTTP update", "expected_revision": 1},
        )
        assert response.status_code == 200
        stale = client.put(
            f"/api/v1/memories/{row['id']}",
            headers=headers,
            json={"content": "stale update", "expected_revision": 1},
        )
        assert stale.status_code == 409
        result = client.get(url + "?limit=1&offset=1", headers=headers).json()
        assert result["total"] == 2 and result["receipts"][0]["revision"] == 1
        assert client.get(url + "?limit=101", headers=headers).status_code == 422
        assert client.get(url + "?offset=-1", headers=headers).status_code == 422
        assert (
            client.get(
                "/api/v1/sources/unknown/id/provenance", headers=headers
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v1/sources/memory/absent/provenance", headers=headers
            ).status_code
            == 404
        )
        response = client.post(
            "/api/v1/set_profile_rule",
            headers=headers,
            json={
                "key": "HTTP profile",
                "value": "private rule",
                "source_agent": "fake",
            },
        )
        assert response.status_code == 200
        profile = response.json()["rule"]
        purl = f"/api/v1/sources/profile/{profile['id']}/provenance"
        assert (
            client.get(purl, headers=headers).json()["head"]["creator_id"] == "master"
        )
        assert (
            client.delete(
                f"/api/v1/profile/{profile['id']}", headers=headers
            ).status_code
            == 200
        )
        assert not client.get(purl, headers=headers).json()["head"]["active"]
        assert (
            client.post(
                "/api/v1/delete_memory",
                headers=headers,
                json={"memory_id": row["id"], "user_confirmed": True},
            ).status_code
            == 200
        )
        assert not client.get(url, headers=headers).json()["head"]["active"]


@pytest.mark.parametrize(
    "operation", ["create", "update", "delete", "reset", "profile"]
)
def test_source_and_receipt_rollback_as_one_transaction(provenance_db, operation):
    from sqlalchemy import event, text

    if operation in ("update", "delete", "reset"):
        row = memory.add_memory("rollback source")
    with provenance_db.connect() as connection:
        before = {
            name: connection.execute(text(f'SELECT * FROM "{name}" ORDER BY 1')).all()
            for name in (
                "memories",
                "memory_index_state",
                "profile",
                "source_provenance_heads",
                "source_provenance_receipts",
                "storage_files",
                "resource_job_state",
            )
        }

    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO source_provenance_receipts"):
            raise RuntimeError("injected receipt failure")

    event.listen(provenance_db, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="injected receipt failure"):
            if operation == "create":
                memory.add_memory(
                    "must roll back", file_keys=["unwritten-attachment.txt"]
                )
            elif operation == "update":
                memory.update_memory(
                    row["id"], content="must roll back", expected_revision=1
                )
            elif operation == "delete":
                memory.delete_memory(row["id"])
            elif operation == "reset":
                memory.reset_all_memories()
            else:
                memory.set_profile_rule("must-roll-back", "private value")
    finally:
        event.remove(provenance_db, "before_cursor_execute", fail)
    with provenance_db.connect() as connection:
        for name, expected in before.items():
            assert (
                connection.execute(text(f'SELECT * FROM "{name}" ORDER BY 1')).all()
                == expected
            )


def test_parallel_profile_writes_and_memory_revision_conflict(provenance_db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException

    ready = Barrier(4)

    def write(i):
        actor = Actor(f"writer-{i}", {"admin"}, None, True)
        ready.wait(timeout=10)
        return memory.set_profile_rule("concurrent", f"value-{i}", actor=actor)

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(write, range(4)))
    assert len({row["id"] for row in results}) == 1
    result = memory.get_source_provenance("profile", results[0]["id"])
    assert result["head"]["revision"] == 4
    assert [row["revision"] for row in result["receipts"]] == [4, 3, 2, 1]
    assert result["head"]["creator_id"] == result["receipts"][-1]["writer_id"]
    value = memory.get_profile_rules()[0]["value"]
    assert result["receipts"][0]["writer_id"] == "writer-" + value.removeprefix(
        "value-"
    )
    row = memory.add_memory("before concurrent edit")
    ready = Barrier(2)

    def edit(i):
        ready.wait(timeout=10)
        try:
            return memory.update_memory(
                row["id"],
                content=f"edit-{i}",
                expected_revision=1,
                actor=Actor(f"editor-{i}", {"admin"}, None, True),
            )
        except HTTPException as error:
            assert error.status_code == 409
            return None

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(edit, range(2)))
    winner = next(result for result in results if result is not None)
    assert sum(result is None for result in results) == 1
    history = memory.get_source_provenance("memory", row["id"])
    assert history["total"] == 2
    assert history["receipts"][0]["writer_id"] == "editor-" + winner[
        "content"
    ].removeprefix("edit-")


def test_reset_records_only_parent_sources(provenance_db):
    from sqlmodel import Session, select
    from gigamind.db.database import MemoryItem
    from gigamind.db.memory_index import MemoryIndexState
    from gigamind.db.source_provenance import SourceHead

    actor = Actor("resetter", {"admin"}, None, True)
    rows = [
        memory.add_memory("many source words " * 250),
        memory.add_memory("short source"),
    ]
    with Session(provenance_db) as session:
        child = session.exec(
            select(MemoryItem).where(MemoryItem.parent_id.is_not(None))
        ).first()
        assert child is not None
        assert not memory.delete_memory(child.id, actor=actor)
        assert memory.get_source_provenance("memory", child.id) is None
    assert memory.reset_all_memories(actor=actor) == 2
    assert memory.reset_all_memories(actor=actor) == 0
    with Session(provenance_db) as session:
        assert session.exec(select(MemoryItem)).all() == []
        assert session.exec(select(MemoryIndexState)).all() == []
        assert len(session.exec(select(SourceHead)).all()) == 2
    for row in rows:
        history = memory.get_source_provenance("memory", row["id"])
        assert not history["head"]["active"]
        assert history["receipts"][0]["operation"] == "reset"
        assert history["receipts"][0]["writer_id"] == "resetter"


@pytest.mark.parametrize("operation", ["delete", "reset"])
def test_delete_waits_for_publisher_and_removes_new_chunks(provenance_db, operation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from sqlalchemy import event
    from sqlmodel import Session, select
    from gigamind.db.database import MemoryItem

    paused, release, attempted = Event(), Event(), Event()
    row = memory.add_memory("initial short source")

    def before(connection, cursor, statement, parameters, context, executemany):
        if paused.is_set() and (
            statement == "BEGIN IMMEDIATE"
            or statement.startswith("DELETE FROM memory_index_state")
        ):
            attempted.set()

    def after(connection, cursor, statement, parameters, context, executemany):
        if (
            statement.startswith("UPDATE memory_index_state SET updated_at=")
            and not paused.is_set()
        ):
            paused.set()
            assert release.wait(10)

    event.listen(provenance_db, "before_cursor_execute", before)
    event.listen(provenance_db, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(2) as pool:
            writer = pool.submit(
                memory.update_memory,
                row["id"],
                content="new long source words " * 250,
                expected_revision=1,
            )
            assert paused.wait(10)
            deleting = (
                pool.submit(memory.delete_memory, row["id"])
                if operation == "delete"
                else pool.submit(memory.reset_all_memories)
            )
            assert attempted.wait(10)
            assert not deleting.done()
            release.set()
            writer.result(10)
            assert deleting.result(10)
    finally:
        release.set()
        event.remove(provenance_db, "before_cursor_execute", before)
        event.remove(provenance_db, "after_cursor_execute", after)
    with Session(provenance_db) as session:
        assert session.exec(select(MemoryItem)).all() == []
    history = memory.get_source_provenance("memory", row["id"])
    assert not history["head"]["active"] and history["total"] == 3


@pytest.mark.parametrize("fail_upgrade", [False, True])
def test_v6_upgrade_preserves_sources_credentials_trust_jobs_and_forgetting(
    provenance_db, monkeypatch, fail_upgrade
):
    from sqlalchemy import inspect, text
    from gigamind.db.source_provenance import SourceHead, SourceReceipt
    from gigamind.services import jobs, trust

    monkeypatch.setattr(trust, "engine", provenance_db)
    actor = Actor("upgrade-admin", {"admin"}, None, True)
    client, token = security.create_client("survivor", ["memory:read"], ["p"])
    row = memory.add_memory("kept source and vector")
    profile = memory.set_profile_rule("kept profile", "kept value")
    proposal = trust.create_proposal(
        actor, content="kept reviewed fact", evidence=[], idempotency_key="upgrade-fact"
    )["proposal"]
    trust.resolve_proposal(actor, proposal["id"], action="approve", expected_revision=1)
    jobs.enqueue("index_file", {"key": "kept-file.txt"}, engine=provenance_db)
    conversation = memory.import_conversations_data(
        {
            "id": "forgotten-upstream",
            "messages": [{"role": "user", "content": "forgotten source"}],
        }
    )["records"][0]
    assert memory.delete_conversation(conversation["id"])
    with provenance_db.begin() as connection:
        before = {
            name: connection.execute(text(f'SELECT * FROM "{name}" ORDER BY 1')).all()
            for name in (
                "client_credentials",
                "trust_proposals",
                "trust_knowledge",
                "trust_revisions",
                "trust_activity",
                "jobs",
                "resource_job_state",
                "conversations",
                "conversation_sources",
                "conversation_receipts",
                "memories",
                "memory_index_state",
                "profile",
            )
        }
        SourceReceipt.__table__.drop(connection)
        SourceHead.__table__.drop(connection)
        connection.execute(text("DELETE FROM schema_migrations WHERE version >= 7"))
        connection.execute(
            text(
                "INSERT INTO schema_migrations (version) VALUES (6) ON CONFLICT (version) DO NOTHING"
            )
        )
    if fail_upgrade:
        original = migrations._upgrade_source_provenance

        def fail(connection):
            original(connection)
            raise RuntimeError("injected v7 upgrade failure")

        monkeypatch.setattr(migrations, "_upgrade_source_provenance", fail)
        with pytest.raises(RuntimeError, match="injected v7 upgrade"):
            migrations.migrate(provenance_db)
        assert migrations.schema_version(provenance_db) == 6
        with provenance_db.connect() as connection:
            assert not inspect(connection).has_table("source_provenance_heads")
            assert not inspect(connection).has_table("source_provenance_receipts")
        monkeypatch.setattr(migrations, "_upgrade_source_provenance", original)
    migrations.migrate(provenance_db)
    assert migrations.schema_ready(provenance_db)
    with provenance_db.connect() as connection:
        for name, expected in before.items():
            assert (
                connection.execute(text(f'SELECT * FROM "{name}" ORDER BY 1')).all()
                == expected
            )
    assert security.get_actor("Bearer " + token).id == client.id
    for kind, source in (("memory", row), ("profile", profile)):
        result = memory.get_source_provenance(kind, source["id"])
        assert result["head"]["creator_id"] is None
        assert result["head"]["creator_provenance"] == "legacy_unknown"
        assert result["total"] == 0 and result["receipts"] == []
    memory.update_memory(
        row["id"], content="new edit", actor=actor, expected_revision=1
    )
    result = memory.get_source_provenance("memory", row["id"])
    assert result["head"]["creator_id"] is None
    assert result["receipts"][0]["writer_id"] == actor.id
    assert result["receipts"][0]["source_revision"] == "2"
    assert (
        memory.import_conversations_data(
            {
                "id": "forgotten-upstream",
                "messages": [{"role": "user", "content": "changed export"}],
            }
        )["forgotten"]
        == 1
    )


def test_http_reset_uses_current_master_and_records_writer(provenance_db, monkeypatch):
    from fastapi.testclient import TestClient
    from gigamind.main import app

    monkeypatch.setenv("GIGAMIND_API_KEY", "changed-master-after-import")
    headers = {"Authorization": "Bearer changed-master-after-import"}
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/add_memory", headers=headers, json={"content": "reset source"}
        )
        assert response.status_code == 200
        source_id = response.json()["memory"]["id"]
        assert (
            client.post(
                "/api/v1/memories/reset", headers=headers, json={"password": "wrong"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/memories/reset",
                headers=headers,
                json={"password": "changed-master-after-import"},
            ).json()["count"]
            == 1
        )
        result = client.get(
            f"/api/v1/sources/memory/{source_id}/provenance", headers=headers
        ).json()
        assert result["receipts"][0]["writer_id"] == "master"
        assert result["receipts"][0]["operation"] == "reset"
        assert not result["head"]["active"]
