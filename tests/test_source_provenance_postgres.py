"""Native concurrency and atomicity for source writes and their receipts."""

import pytest
import test_postgres_migrations as postgres_fixtures
import test_source_provenance_integration as behavior
from gigamind import security
from gigamind.db import migrations
from gigamind.services import memory

postgres_engine = postgres_fixtures.postgres_engine


@pytest.fixture
def native_source_db(postgres_engine, monkeypatch):
    migrations.migrate(postgres_engine)
    monkeypatch.setattr(memory, "engine", postgres_engine)
    monkeypatch.setattr(memory, "is_postgres", True)
    monkeypatch.setattr(security, "engine", postgres_engine)
    monkeypatch.setattr(memory.embedding_config, "DEFAULT_DIM", 768)
    monkeypatch.setattr(
        memory, "generate_embedding", lambda *a, **kw: [1.0] + [0.0] * 767
    )
    return postgres_engine


def test_native_creator_and_edits(native_source_db):
    behavior.test_create_edit_delete_preserve_authenticated_creator(native_source_db)


def test_native_profile_serialization_and_memory_cas(native_source_db):
    behavior.test_parallel_profile_writes_and_memory_revision_conflict(native_source_db)


@pytest.mark.parametrize(
    "operation", ["create", "update", "delete", "reset", "profile"]
)
def test_native_source_receipt_rollback(native_source_db, operation):
    behavior.test_source_and_receipt_rollback_as_one_transaction(
        native_source_db, operation
    )


@pytest.mark.parametrize("operation", ["delete", "reset"])
def test_native_forgetting_waits_for_publisher(native_source_db, operation):
    behavior.test_delete_waits_for_publisher_and_removes_new_chunks(
        native_source_db, operation
    )


@pytest.mark.parametrize("fail_upgrade", [False, True])
def test_native_v6_upgrade_and_rollback(native_source_db, monkeypatch, fail_upgrade):
    behavior.test_v6_upgrade_preserves_sources_credentials_trust_jobs_and_forgetting(
        native_source_db, monkeypatch, fail_upgrade
    )


def test_native_snapshot_is_consistent(native_source_db):
    from test_source_provenance_core import (
        test_read_binds_receipts_to_head_snapshot as snapshot,
    )

    snapshot(native_source_db)


def test_native_legacy_profile_path_ids(native_source_db):
    behavior.test_legacy_profile_ids_with_reserved_path_characters(native_source_db)
