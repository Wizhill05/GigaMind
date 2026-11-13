"""Same lifecycle guarantees against actual local PostgreSQL transactions."""

import pytest
from sqlalchemy import text

import test_postgres_migrations as postgres_fixtures
from test_conversation_ledger import (
    test_import_delete_race_both_transaction_orderings as race,
    test_ledger_and_source_rollback_together as rollback,
    test_upgrade_backfills_unknown_provenance_and_exact_fence as upgrade,
    export,
    test_v5_upgrade_preserves_credentials_knowledge_and_jobs as preserve,
)
from gigamind.db import migrations
from gigamind.services import memory


postgres_engine = postgres_fixtures.postgres_engine


@pytest.fixture
def native_ledger(postgres_engine, monkeypatch):
    migrations.migrate(postgres_engine)
    monkeypatch.setattr(memory, "engine", postgres_engine)
    yield postgres_engine


@pytest.mark.parametrize("first_operation", ["import", "delete"])
def test_native_import_delete_ordering(native_ledger, first_operation):
    race(native_ledger, first_operation)


@pytest.mark.parametrize("operation", ["import", "delete"])
def test_native_transaction_rollback(native_ledger, operation):
    rollback(native_ledger, operation)


def test_native_upgrade_and_legacy_identity(native_ledger):
    upgrade(native_ledger)


def test_native_duplicate_receipt_race(native_ledger):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    ready = Barrier(2)

    def ingest():
        ready.wait(timeout=10)
        return memory.import_conversations_data(export())

    with ThreadPoolExecutor(2) as pool:
        left, right = pool.submit(ingest), pool.submit(ingest)
        results = [left.result(10), right.result(10)]
    assert sum(r["ingested"] for r in results) == 1
    assert sum(r["duplicates"] for r in results) == 1
    with native_ledger.connect() as connection:
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM conversation_receipts")
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize("fail_migration", [False, True])
def test_native_v5_upgrade_preserves_other_services(
    native_ledger, monkeypatch, fail_migration
):
    preserve(native_ledger, monkeypatch, fail_migration)
