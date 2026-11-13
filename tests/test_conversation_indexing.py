import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select, update

from gigamind.db.database import ConversationItem
from gigamind.db.jobs import Job
from gigamind.db.migrations import migrate
from gigamind.services import conversation_index as index, conversation_ledger, embedding, jobs


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}", connect_args={"check_same_thread": False})
    migrate(engine)
    yield engine
    engine.dispose()


def add(engine, cid="same", messages=None):
    with engine.begin() as conn:
        conn.execute(ConversationItem.__table__.insert().values(id=cid, platform="test", title="Title", summary="Summary", source_agent="user", messages_json=json.dumps(messages or [{"role": "user", "content": "hello"}], ensure_ascii=False), embedding_json="[]", created_at="now"))


@pytest.fixture
def vector(monkeypatch):
    monkeypatch.setattr(embedding, "generate_embedding", lambda **kwargs: [1.0] * embedding.DEFAULT_DIM)


def test_complete_unicode_and_restart(engine, vector):
    messages = [{"role": "user", "content": "一" * 9000}, {"role": "assistant", "content": "late turn 🌙"}]
    add(engine, messages=messages)
    queued = index.enqueue_conversation("same", engine=engine)
    assert queued.state == "queued"
    url = engine.url
    engine.dispose()
    reopened = create_engine(url, connect_args={"check_same_thread": False})
    assert jobs.run_once(engine=reopened).state == "completed"
    reopened.dispose()
    reopened = create_engine(url, connect_args={"check_same_thread": False})
    pieces = index.segment_vectors("same", engine=reopened)
    content = "".join(p["content"] for p in pieces)
    assert "late turn 🌙" in content and "一" * 9000 in content and '"role":"assistant"' in content
    assert len(pieces) > 1 and index.metadata("same", engine=reopened)["indexed"]
    reopened.dispose()


def test_failures_preserve_source(engine, monkeypatch):
    add(engine)
    monkeypatch.setattr(embedding, "generate_embedding", lambda **kwargs: [float('nan')] * embedding.DEFAULT_DIM)
    index.enqueue_conversation("same", engine=engine)
    assert jobs.run_once(engine=engine).state == "retrying"
    assert index.metadata("same", engine=engine)["indexed"] is False
    with engine.connect() as conn:
        assert conn.execute(select(ConversationItem.id)).scalar_one() == "same"
    assert index.segment_vectors("same", engine=engine) == []


def test_idempotence_and_file_identity(engine, vector):
    add(engine)
    file_job = jobs.enqueue("index_file", {"key": "same"}, engine=engine)
    first = index.enqueue_conversation("same", idempotency_key="unique", engine=engine)
    assert index.enqueue_conversation("same", idempotency_key="unique", engine=engine).id == first.id
    jobs.forget_resource("same", engine=engine)
    assert jobs.status(file_job.id, engine=engine).state == "cancelled"
    assert jobs.status(first.id, engine=engine).state == "queued"
    assert jobs.run_once(engine=engine).state == "completed"


@pytest.mark.parametrize("action", ["cancel", "forget", "supersede", "change"])
def test_late_provider_is_fenced(engine, monkeypatch, action):
    add(engine)
    started, release = threading.Event(), threading.Event()
    def blocked(**kwargs):
        started.set()
        assert release.wait(5)
        return [1.0] * embedding.DEFAULT_DIM
    monkeypatch.setattr(embedding, "generate_embedding", blocked)
    job = index.enqueue_conversation("same", engine=engine)
    worker = threading.Thread(target=lambda: jobs.run_once(engine=engine))
    worker.start()
    assert started.wait(5)
    if action == "cancel":
        jobs.cancel(job.id, engine=engine)
    elif action == "forget":
        conversation_ledger.forget("same", engine=engine)
    elif action == "supersede":
        index.enqueue_conversation("same", engine=engine)
    else:
        with engine.begin() as conn:
            conn.execute(update(ConversationItem).where(ConversationItem.id == "same").values(title="changed"))
    release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert index.segment_vectors("same", engine=engine) == []
    assert jobs.status(job.id, engine=engine).state in ("cancelled", "failed")


def test_publication_rollback_preserves_previous_segments(engine, monkeypatch, vector):
    from sqlalchemy import event
    from gigamind.db.conversation_index import ConversationIndexSegment

    add(engine)
    index.enqueue_conversation("same", engine=engine)
    assert jobs.run_once(engine=engine).state == "completed"
    before = index.segment_vectors("same", engine=engine)
    index.enqueue_conversation("same", engine=engine)

    def fail_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO CONVERSATION_INDEX_SEGMENTS"):
            raise RuntimeError("simulated write failure")

    event.listen(engine, "before_cursor_execute", fail_insert)
    try:
        assert jobs.run_once(engine=engine).state == "retrying"
    finally:
        event.remove(engine, "before_cursor_execute", fail_insert)
    assert index.segment_vectors("same", engine=engine) == before
    with engine.connect() as connection:
        assert len(connection.execute(select(ConversationIndexSegment)).all()) == len(before)


def test_model_and_source_changes_hide_vectors(engine, vector, monkeypatch):
    add(engine)
    index.enqueue_conversation("same", engine=engine)
    jobs.run_once(engine=engine)
    assert index.segment_vectors("same", engine=engine)[0]["segment_index"] == 0
    monkeypatch.setattr(embedding, "MODEL_NAME", "different-model")
    assert not index.metadata("same", engine=engine)["indexed"]
    assert index.segment_vectors("same", engine=engine) == []
    monkeypatch.undo()
    with engine.begin() as conn:
        conn.execute(update(ConversationItem).where(ConversationItem.id == "same").values(title="new title"))
    assert index.segment_vectors("same", engine=engine) == []


def test_options_and_forgotten_idempotent_replay(engine):
    add(engine)
    job = index.enqueue_conversation("same", "idempotency", 5, engine=engine)
    assert job.max_attempts == 5
    assert index.enqueue_conversation("same", "idempotency", 5, engine=engine).id == job.id
    with pytest.raises(jobs.Conflict):
        index.enqueue_conversation("same", "idempotency", 2, engine=engine)
    conversation_ledger.forget("same", engine=engine)
    with pytest.raises(LookupError):
        index.enqueue_conversation("same", "idempotency", 5, engine=engine)


def test_retry_after_provider_failure_then_publish(engine, monkeypatch):
    add(engine)
    attempt = 0

    def provider(**kwargs):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise embedding.EmbeddingUnavailable("unavailable")
        return [1.0] * embedding.DEFAULT_DIM

    monkeypatch.setattr(embedding, "generate_embedding", provider)
    job = index.enqueue_conversation("same", engine=engine)
    now = jobs.utcnow() + timedelta(seconds=1)
    assert jobs.run_once(engine=engine, clock=lambda: now).state == "retrying"
    now += timedelta(seconds=5)
    assert jobs.run_once(engine=engine, clock=lambda: now).state == "completed"
    assert jobs.status(job.id, engine=engine).attempts == 2
    assert "hello" in "".join(row["content"] for row in index.segment_vectors("same", engine=engine))
    with engine.connect() as connection:
        assert "hello" in connection.execute(select(ConversationItem.messages_json)).scalar_one()


def test_expired_lease_and_reclaimed_owner_fence_late_provider(engine, monkeypatch):
    add(engine)
    job = index.enqueue_conversation("same", engine=engine)
    now = jobs.utcnow() + timedelta(seconds=1)
    first = jobs.claim(engine=engine, clock=lambda: now, lease_seconds=1)
    started, release = threading.Event(), threading.Event()

    def blocked(**kwargs):
        started.set()
        assert release.wait(5)
        return [1.0] * embedding.DEFAULT_DIM

    monkeypatch.setattr(embedding, "generate_embedding", blocked)
    lease = jobs.JobLease(job.id, first.lease_token, lambda: now, engine)
    failures = []

    def publish():
        try:
            index.index_conversation({"conversation_id": "same"}, lease)
        except Exception as exc:
            failures.append(exc)

    worker = threading.Thread(target=publish)
    worker.start()
    assert started.wait(5)
    now += timedelta(seconds=2)
    second = jobs.claim(engine=engine, clock=lambda: now, lease_seconds=60)
    assert second.id == first.id and second.lease_token != first.lease_token
    release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert len(failures) == 1 and isinstance(failures[0], jobs.PermanentFailure)
    assert index.segment_vectors("same", engine=engine) == []
    new_lease = jobs.JobLease(job.id, second.lease_token, lambda: now, engine)
    index.index_conversation({"conversation_id": "same"}, new_lease)
    assert index.metadata("same", engine=engine)["indexed"]


def test_backfill_pages_skip_active_and_complete(engine, vector):
    for cid in ("a", "b", "c", "d", "e"):
        add(engine, cid)
    first = index.enqueue_backfill(limit=2, engine=engine)
    assert first == {"queued": 2, "skipped": 0, "next_cursor": "b"}
    assert jobs.run_once(engine=engine).state == "completed"
    assert index.enqueue_backfill(limit=2, engine=engine) == {
        "queued": 0, "skipped": 2, "next_cursor": "b"
    }
    second = index.enqueue_backfill(cursor=first["next_cursor"], limit=2, engine=engine)
    third = index.enqueue_backfill(cursor=second["next_cursor"], limit=2, engine=engine)
    assert second == {"queued": 2, "skipped": 0, "next_cursor": "d"}
    assert third == {"queued": 1, "skipped": 0, "next_cursor": None}
    with engine.connect() as connection:
        ids = connection.execute(select(Job.resource_key).where(Job.kind == "index_conversation")).scalars().all()
    assert sorted(ids) == ["a", "b", "c", "d", "e"]


def test_concurrent_backfill_does_not_replace_active_job(engine):
    add(engine)
    barrier = threading.Barrier(2)

    def run():
        barrier.wait(timeout=5)
        return index.enqueue_backfill(limit=1, engine=engine)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sorted(result["queued"] for result in results) == [0, 1]
    with engine.connect() as connection:
        records = connection.execute(select(Job.id, Job.state).where(Job.kind == "index_conversation")).all()
    assert len(records) == 1 and records[0].state == "queued"


def schema7_upgrade(engine, fail_migration):
    from sqlalchemy import event, inspect, text
    from gigamind.db import migrations
    from gigamind.db.source_provenance import SourceHead, SourceReceipt
    from gigamind.db.trust_models import AcceptedKnowledge
    from gigamind.security import ClientCredential

    migrate(engine)
    add(engine, "preserved")
    imported = conversation_ledger.import_sources(
        {"platform": "custom", "id": "upstream", "messages": [{"role": "user", "content": "kept"}]},
        engine=engine,
    )
    file_job = jobs.enqueue("index_file", {"key": "kept-file"}, engine=engine)
    with engine.begin() as connection:
        connection.execute(ClientCredential.__table__.insert().values(
            id="credential", name="kept", token_hash="hash", scopes_json="[]",
            project_ids_json="[]", revoked=False, revision=0,
        ))
        connection.execute(AcceptedKnowledge.__table__.insert().values(
            id="knowledge", proposal_id="proposal", content="kept knowledge",
            data_json="{}", writer_id="writer", revision=1, status="accepted",
            created_at="now", updated_at="now",
        ))
        connection.execute(SourceHead.__table__.insert().values(
            kind="memory", source_id="memory", revision=1, active=True,
            creator_provenance="authenticated",
        ))
        connection.execute(SourceReceipt.__table__.insert().values(
            kind="memory", source_id="memory", revision=1, operation="created",
            writer_provenance="authenticated", timestamp="now",
        ))
        connection.execute(text("DROP TABLE conversation_index_segments"))
        connection.execute(text("DROP TABLE conversation_index_state"))
        connection.execute(text("DELETE FROM schema_migrations WHERE version > 7"))
        connection.execute(text("INSERT INTO schema_migrations (version) VALUES (7)"))

    queries = {
        "credential": "SELECT id, name, token_hash FROM client_credentials",
        "knowledge": "SELECT id, content FROM trust_knowledge",
        "file_job": "SELECT id, resource_key, state FROM jobs WHERE kind='index_file'",
        "sources": "SELECT key, platform, upstream_id FROM conversation_sources ORDER BY key",
        "receipts": "SELECT conversation_id, source_key FROM conversation_receipts ORDER BY conversation_id",
        "heads": "SELECT kind, source_id, revision FROM source_provenance_heads ORDER BY source_id",
        "provenance": "SELECT kind, source_id, revision FROM source_provenance_receipts ORDER BY source_id",
        "conversations": "SELECT id, messages_json FROM conversations ORDER BY id",
    }

    def snapshot():
        with engine.connect() as connection:
            return {key: connection.execute(text(sql)).all() for key, sql in queries.items()}

    before = snapshot()
    assert before["file_job"][0].id == file_job.id
    assert imported["ingested"] == 1
    if fail_migration:
        def fail_after_tables(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO schema_migrations"):
                assert inspect(connection).has_table("conversation_index_state")
                assert inspect(connection).has_table("conversation_index_segments")
                raise RuntimeError("injected after index tables")

        event.listen(engine, "before_cursor_execute", fail_after_tables)
        try:
            with pytest.raises(RuntimeError, match="injected after index tables"):
                migrations.migrate(engine)
        finally:
            event.remove(engine, "before_cursor_execute", fail_after_tables)
        assert migrations.schema_version(engine) == 7
        assert not inspect(engine).has_table("conversation_index_state")
        assert not inspect(engine).has_table("conversation_index_segments")
        assert snapshot() == before
    migrations.migrate(engine)
    assert migrations.schema_version(engine) == 8
    assert migrations.schema_ready(engine)
    assert snapshot() == before
    assert inspect(engine).has_table("conversation_index_state")
    assert inspect(engine).has_table("conversation_index_segments")


@pytest.mark.parametrize("fail_migration", [False, True])
def test_schema7_upgrade_preserves_data_and_rolls_back(engine, fail_migration):
    schema7_upgrade(engine, fail_migration)


def test_unusable_completed_index_reports_not_indexed(engine, vector, monkeypatch):
    from gigamind.db.conversation_index import ConversationIndexSegment

    add(engine)
    index.enqueue_conversation("same", engine=engine)
    jobs.run_once(engine=engine)
    with monkeypatch.context() as patch:
        patch.setattr(embedding, "MODEL_NAME", "different-model")
        info = index.metadata("same", engine=engine)
        assert info["state"] == "not_indexed" and info["error"]
    with engine.begin() as connection:
        connection.execute(
            update(ConversationIndexSegment)
            .where(ConversationIndexSegment.conversation_id == "same")
            .values(embedding_json="[null]")
        )
    info = index.metadata("same", engine=engine)
    assert info["state"] == "not_indexed" and info["error"]
    assert index.segment_vectors("same", engine=engine) == []
    with engine.begin() as connection:
        connection.execute(
            update(ConversationItem)
            .where(ConversationItem.id == "same")
            .values(title="changed")
        )
    info = index.metadata("same", engine=engine)
    assert info["state"] == "not_indexed" and info["error"]


def test_heartbeat_extends_conversation_job_lease(engine, vector):
    add(engine)
    index.enqueue_conversation("same", engine=engine)
    now = jobs.utcnow() + timedelta(seconds=1)
    job = jobs.claim(engine=engine, clock=lambda: now, lease_seconds=1)
    now += timedelta(milliseconds=500)
    assert jobs.heartbeat(
        job.id, job.lease_token, engine=engine, clock=lambda: now, lease_seconds=5
    )
    now += timedelta(seconds=2)
    assert jobs.claim(engine=engine, clock=lambda: now, lease_seconds=5) is None
    lease = jobs.JobLease(job.id, job.lease_token, lambda: now, engine)
    assert index.index_conversation({"conversation_id": "same"}, lease)["segments"] > 0
    assert index.metadata("same", engine=engine)["indexed"]


def test_forget_conversation_does_not_touch_same_file_key(engine):
    from gigamind.db.jobs import ResourceJobState

    add(engine)
    file_job = jobs.enqueue("index_file", {"key": "same"}, engine=engine)
    conversation_job = index.enqueue_conversation("same", engine=engine)
    assert conversation_ledger.forget("same", engine=engine)
    assert jobs.status(conversation_job.id, engine=engine).state == "cancelled"
    assert jobs.status(file_job.id, engine=engine).state == "queued"
    with engine.connect() as connection:
        owner = connection.execute(
            select(ResourceJobState.__table__).where(ResourceJobState.key == "same")
        ).mappings().one()
    assert not owner["deleted"] and owner["current_job_id"] == file_job.id
