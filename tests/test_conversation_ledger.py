"""Import receipts and forgetting are observable across database sessions."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text, event
from sqlmodel import Session, select

from gigamind.db import migrations
from gigamind.db.database import ConversationItem
from gigamind.services import memory


def export(content="private transcript", source_id="upstream-one"):
    value = {"platform": "custom", "messages": [{"role": "user", "content": content}]}
    if source_id is not None:
        value["id"] = source_id
    return value


@pytest.fixture
def ledger_engine(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ledger.db'}", connect_args={"check_same_thread": False}
    )
    migrations.migrate(engine)
    monkeypatch.setattr(memory, "engine", engine)
    monkeypatch.setattr(
        memory,
        "generate_embedding",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("provider called")),
    )
    yield engine
    engine.dispose()


def test_delete_forgets_all_versions_and_blocks_changed_export_after_reopen(
    ledger_engine, monkeypatch
):
    assert memory.import_conversations_data(export())["ingested"] == 1
    assert (
        memory.import_conversations_data(export("changed private transcript"))[
            "ingested"
        ]
        == 1
    )
    with Session(ledger_engine) as session:
        ids = session.exec(select(ConversationItem.id)).all()
    assert len(ids) == 2
    assert memory.delete_conversation(ids[0])
    ledger_engine.dispose()
    assert memory.get_conversations()["total"] == 0
    result = memory.import_conversations_data(
        [export(), export("future changed transcript")]
    )
    assert result["ingested"] == 0
    assert result["forgotten"] == 2
    assert {row["status"] for row in result["records"]} == {"forgotten"}
    assert memory.get_conversation(ids[1]) is None


def test_receipts_separate_authenticated_writer_from_claimed_source(ledger_engine):
    from gigamind.security import Actor
    from gigamind.services.conversation_ledger import get_receipt

    actor = Actor("actual-admin", {"admin"}, None, True)
    data = dict(export(), source_agent="forged-writer")
    result = memory.import_conversations_data(data, actor=actor)
    cid = result["records"][0]["id"]
    original = get_receipt(cid, engine=ledger_engine)
    assert original["imported_by"] == "actual-admin"
    assert original["provenance"] == "authenticated"
    assert original["upstream_id"] == "upstream-one"
    assert original["content_digest"] == cid.removeprefix("import_")
    memory.import_conversations_data(data, provenance="local_cli")
    assert get_receipt(cid, engine=ledger_engine) == original
    memory.delete_conversation(cid, actor=actor)
    receipt = get_receipt(cid, engine=ledger_engine)
    assert receipt["deleted_by"] == "actual-admin"
    assert receipt["deleted_at"]
    with ledger_engine.connect() as connection:
        assert "private transcript" not in str(
            connection.execute(text("SELECT * FROM conversation_receipts")).all()
        )
        assert "private transcript" not in str(
            connection.execute(text("SELECT * FROM conversation_sources")).all()
        )


def test_missing_upstream_id_only_blocks_exact_fingerprint(ledger_engine):
    result = memory.import_conversations_data(
        export(source_id=None), provenance="local_cli"
    )
    cid = result["records"][0]["id"]
    assert memory.get_conversation(cid)["provenance"]["provenance"] == "local_cli"
    assert memory.delete_conversation(cid)
    assert memory.import_conversations_data(export(source_id=None))["forgotten"] == 1
    assert memory.import_conversations_data(export("different", None))["ingested"] == 1
    # Platform namespaces distinguish otherwise identical upstream IDs.
    assert (
        memory.import_conversations_data(dict(export(), platform="other"))["ingested"]
        == 1
    )


@pytest.mark.parametrize("operation", ["import", "delete"])
def test_ledger_and_source_rollback_together(ledger_engine, operation):
    if operation == "delete":
        cid = memory.import_conversations_data(export())["records"][0]["id"]

    def fail(connection, cursor, statement, parameters, context, executemany):
        if (
            operation == "import"
            and statement.startswith("INSERT INTO conversation_receipts")
        ) or (
            operation == "delete"
            and statement.startswith("UPDATE conversation_receipts")
        ):
            raise RuntimeError("injected transaction failure")

    event.listen(ledger_engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            if operation == "import":
                memory.import_conversations_data(export())
            else:
                memory.delete_conversation(cid)
    finally:
        event.remove(ledger_engine, "before_cursor_execute", fail)
    with ledger_engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM conversations")
        ).scalar_one() == (1 if operation == "delete" else 0)
        assert (
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM conversation_sources WHERE forgotten_at IS NOT NULL"
                )
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM conversation_receipts WHERE deleted_at IS NOT NULL"
                )
            ).scalar_one()
            == 0
        )
    assert memory.import_conversations_data(export())["ingested"] == (
        1 if operation == "import" else 0
    )


@pytest.mark.parametrize("first_operation", ["import", "delete"])
def test_import_delete_race_both_transaction_orderings(ledger_engine, first_operation):
    from threading import Event

    cid = memory.import_conversations_data(export())["records"][0]["id"]
    paused, release, second_started = Event(), Event(), Event()
    prefix = (
        "INSERT INTO conversations"
        if first_operation == "import"
        else "DELETE FROM conversations"
    )

    def pause(connection, cursor, statement, parameters, context, executemany):
        if paused.is_set() and (
            statement == "BEGIN IMMEDIATE" or "pg_advisory_xact_lock" in statement
        ):
            second_started.set()
        if statement.startswith(prefix) and not paused.is_set():
            paused.set()
            assert release.wait(10)

    def ingest():
        return memory.import_conversations_data(export("changed version"))

    def remove():
        return memory.delete_conversation(cid)

    first, second = (
        (ingest, remove) if first_operation == "import" else (remove, ingest)
    )

    event.listen(ledger_engine, "before_cursor_execute", pause)
    try:
        with ThreadPoolExecutor(2) as pool:
            initial = pool.submit(first)
            assert paused.wait(10)
            follower = pool.submit(second)
            assert second_started.wait(10)
            assert not follower.done()
            release.set()
            first_result, second_result = initial.result(10), follower.result(10)
    finally:
        release.set()
        event.remove(ledger_engine, "before_cursor_execute", pause)
    assert memory.get_conversations()["total"] == 0
    assert memory.import_conversations_data(export("another version"))["forgotten"] == 1
    if first_operation == "delete":
        assert second_result["forgotten"] == 1
    else:
        assert first_result["ingested"] == 1


def test_authenticated_http_import_forget_and_read_boundaries(
    ledger_engine, monkeypatch
):
    import json
    from fastapi.testclient import TestClient
    from gigamind.main import app
    from gigamind import security

    from gigamind.services import trust

    monkeypatch.setattr(security, "engine", ledger_engine)
    monkeypatch.setattr(trust, "engine", ledger_engine)
    headers = {"Authorization": "Bearer offline-test-master-key"}
    payload = {"file": ("source.json", json.dumps(export()), "application/json")}
    _, scoped_token = security.create_client("reader", ["memory:read"], ["project-a"])
    with TestClient(app) as client:
        assert (
            client.post("/api/v1/conversations/import_file", files=payload).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/conversations/import_file",
                files=payload,
                headers={"Authorization": "Bearer " + scoped_token},
            ).status_code
            == 403
        )
        response = client.post(
            "/api/v1/conversations/import_file", files=payload, headers=headers
        )
        assert response.status_code == 200, response.text
        cid = response.json()["records"][0]["id"]
        assert client.get("/api/v1/conversations", headers=headers).json()["total"] == 1
        detail = client.get("/api/v1/conversations/" + cid, headers=headers).json()[
            "conversation"
        ]
        assert detail["provenance"]["provenance"] == "authenticated"
        assert detail["provenance"]["imported_by"] == "master"
        proposal = trust.create_proposal(
            security.get_actor(headers["Authorization"]),
            content="unapproved claim",
            evidence=[
                {
                    "source_type": "conversation",
                    "source_id": cid,
                    "quote": "private transcript",
                    "source_role": "user",
                }
            ],
            idempotency_key="inspect-forgotten-source",
        )["proposal"]
        inspect_url = f"/api/v1/review/proposals/{proposal['id']}/inspect-evidence"
        assert (
            client.post(
                inspect_url, headers=headers, json={"expected_revision": 1}
            ).json()["evidence"][0]["status"]
            == "matched"
        )
        assert (
            client.delete("/api/v1/conversations/" + cid, headers=headers).status_code
            == 200
        )
        assert (
            client.get("/api/v1/conversations/" + cid, headers=headers).status_code
            == 404
        )
        assert client.get("/api/v1/conversations", headers=headers).json()["total"] == 0
        inspected = client.post(
            inspect_url, headers=headers, json={"expected_revision": 1}
        )
        assert inspected.status_code == 200
        assert inspected.json()["evidence"][0]["status"] == "not_found"
        assert inspected.json()["evidence"][0]["excerpt"] is None
        response = client.post(
            "/api/v1/conversations/search", headers=headers, json={"query": "private"}
        )
        assert response.status_code == 200 and response.json()["results"] == []
        assert (
            client.post(
                "/api/v1/conversations/import_file", files=payload, headers=headers
            ).json()["forgotten"]
            == 1
        )


def test_upgrade_backfills_unknown_provenance_and_exact_fence(ledger_engine):
    from gigamind.services.conversation_import import normalize_conversations
    from gigamind.services.conversation_ledger import get_receipt

    cid = normalize_conversations(export())[0]["id"]
    with ledger_engine.begin() as connection:
        connection.execute(text("DROP TABLE conversation_receipts"))
        connection.execute(text("DROP TABLE conversation_sources"))
        connection.execute(text("DELETE FROM schema_migrations WHERE version > 5"))
        connection.execute(text("INSERT INTO schema_migrations (version) VALUES (5)"))
        connection.execute(
            ConversationItem.__table__.insert().values(
                id=cid,
                platform="custom",
                title="old",
                summary="",
                messages_json='[{"role":"user","content":"private transcript"}]',
                embedding_json="[]",
                created_at="old",
                source_agent="claimed",
            )
        )
    migrations.migrate(ledger_engine)
    receipt = get_receipt(cid, engine=ledger_engine)
    assert receipt["provenance"] == receipt["identity_kind"] == "legacy_unknown"
    assert (
        receipt["imported_by"]
        is receipt["imported_at"]
        is receipt["upstream_id"]
        is None
    )
    assert memory.import_conversations_data(export())["duplicates"] == 1
    receipt = get_receipt(cid, engine=ledger_engine)
    assert (
        receipt["identity_kind"] == "upstream"
        and receipt["provenance"] == "legacy_unknown"
    )
    assert memory.delete_conversation(cid)
    assert memory.import_conversations_data(export("changed"))["forgotten"] == 1
    migrations.migrate(ledger_engine)
    assert migrations.schema_ready(ledger_engine)


@pytest.mark.parametrize("fail_migration", [False, True])
def test_v5_upgrade_preserves_credentials_knowledge_and_jobs(
    ledger_engine, monkeypatch, fail_migration
):
    from gigamind import security
    from gigamind.services import trust, jobs
    from gigamind.security import Actor
    from gigamind.db.conversation_ledger import ConversationReceipt, ConversationSource
    from sqlalchemy import inspect

    monkeypatch.setattr(security, "engine", ledger_engine)
    monkeypatch.setattr(trust, "engine", ledger_engine)
    actor = Actor("upgrade-admin", {"admin"}, None, True)
    client, token = security.create_client("kept", ["memory:read"], ["p"])
    proposal = trust.create_proposal(
        actor,
        content="kept fact",
        evidence=[
            {"source_type": "note", "source_id": "note", "quote": "kept evidence"}
        ],
        idempotency_key="upgrade-proposal",
    )["proposal"]
    trust.resolve_proposal(actor, proposal["id"], action="approve", expected_revision=1)
    job = jobs.enqueue("index_file", {"key": "kept.txt"}, engine=ledger_engine)
    memory.import_conversations_data(export())
    with ledger_engine.begin() as connection:
        before = {
            table: connection.execute(text(f'SELECT * FROM "{table}"')).all()
            for table in (
                "client_credentials",
                "trust_knowledge",
                "trust_revisions",
                "jobs",
                "resource_job_state",
                "conversations",
            )
        }
        ConversationReceipt.__table__.drop(connection)
        ConversationSource.__table__.drop(connection)
        connection.execute(text("DELETE FROM schema_migrations WHERE version >= 5"))
        connection.execute(text("INSERT INTO schema_migrations (version) VALUES (5)"))
    if fail_migration:
        original = migrations.register_legacy

        def fail(*args):
            original(*args)
            raise RuntimeError("injected ledger upgrade failure")

        monkeypatch.setattr(migrations, "register_legacy", fail)
        with pytest.raises(RuntimeError, match="injected ledger upgrade"):
            migrations.migrate(ledger_engine)
        assert migrations.schema_version(ledger_engine) == 5
        with ledger_engine.connect() as connection:
            assert not inspect(connection).has_table("conversation_receipts")
        monkeypatch.setattr(migrations, "register_legacy", original)
    migrations.migrate(ledger_engine)
    with ledger_engine.connect() as connection:
        for table, expected in before.items():
            assert (
                connection.execute(text(f'SELECT * FROM "{table}"')).all() == expected
            )
    assert security.get_actor("Bearer " + token).id == client.id
    assert jobs.status(job.id, engine=ledger_engine).state == "queued"
    assert migrations.schema_ready(ledger_engine)


def test_cli_receipt_and_forgetting_survive_new_processes(tmp_path):
    import json
    import os
    import subprocess
    import sys
    from gigamind.services.conversation_import import normalize_conversations

    source = tmp_path / "source.json"
    data = export()
    source.write_text(json.dumps(data))
    env = dict(
        os.environ,
        DB_PATH=str(tmp_path / "cli.db"),
        DATABASE_URL="",
        PYTHON_DOTENV_DISABLED="1",
    )
    command = [sys.executable, "-m", "gigamind.cli.importer", "--chatgpt", str(source)]
    result = subprocess.run(
        command, env=env, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    cid = normalize_conversations(data, "chatgpt")[0]["id"]
    script = "from gigamind.services.memory import get_conversation, delete_conversation; import sys; c=get_conversation(sys.argv[1]); assert c['provenance']['provenance']=='local_cli'; assert c['provenance']['imported_by'] is None; assert delete_conversation(sys.argv[1])"
    deleted = subprocess.run(
        [sys.executable, "-c", script, cid],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert deleted.returncode == 0, deleted.stderr
    source.write_text(json.dumps(export("changed after deletion")))
    result = subprocess.run(
        command, env=env, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0 and "1 forgotten source(s) blocked" in result.stdout
