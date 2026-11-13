"""Exercise the same indexing lifecycle on an explicitly configured local Postgres."""
import pytest

import test_postgres_migrations as postgres_fixtures
from test_conversation_indexing import add, test_late_provider_is_fenced as late_provider
from gigamind.db.migrations import migrate
from gigamind.services import conversation_index as index, embedding, jobs

postgres_engine = postgres_fixtures.postgres_engine


@pytest.fixture
def native(postgres_engine):
    migrate(postgres_engine)
    return postgres_engine


def test_native_publication(native, monkeypatch):
    add(native)
    monkeypatch.setattr(embedding, "generate_embedding", lambda **kwargs: [1.0] * embedding.DEFAULT_DIM)
    index.enqueue_conversation("same", engine=native)
    assert jobs.run_once(engine=native).state == "completed"
    assert index.metadata("same", engine=native)["indexed"]


@pytest.mark.parametrize("action", ["cancel", "forget", "supersede", "change"])
def test_native_late_provider(native, monkeypatch, action):
    late_provider(native, monkeypatch, action)


@pytest.mark.parametrize("fail_migration", [False, True])
def test_native_schema7_upgrade(postgres_engine, fail_migration):
    from test_conversation_indexing import schema7_upgrade

    schema7_upgrade(postgres_engine, fail_migration)


def test_native_concurrent_backfill(native):
    from test_conversation_indexing import test_concurrent_backfill_does_not_replace_active_job as race

    race(native)


def test_native_expired_lease(native, monkeypatch):
    from test_conversation_indexing import test_expired_lease_and_reclaimed_owner_fence_late_provider as expiry

    expiry(native, monkeypatch)


def test_native_heartbeat(native, monkeypatch):
    from test_conversation_indexing import test_heartbeat_extends_conversation_job_lease as heartbeat

    monkeypatch.setattr(embedding, "generate_embedding", lambda **kwargs: [1.0] * embedding.DEFAULT_DIM)
    heartbeat(native, None)
