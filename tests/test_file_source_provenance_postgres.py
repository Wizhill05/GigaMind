"""Run the same file provenance checks against an isolated native PostgreSQL schema."""

from gigamind.db import migrations
from test_postgres_migrations import postgres_engine
from test_file_source_provenance import (
    test_registration_recovery_and_delete_are_attributed_and_idempotent as check_lifecycle,
    test_receipt_failure_rolls_back_registration_and_delete as check_rollback,
    test_failed_verification_receipt_rolls_back_manifest as check_verification_rollback,
    test_legacy_recovery_does_not_invent_creator as check_legacy_recovery,
    test_legacy_deletion_has_unknown_creator_and_gc_adds_no_receipt as check_legacy_deletion,
    test_concurrent_verifications_append_one_receipt as check_concurrent_verification,
    test_registration_and_deletion_order_is_atomic as check_registration_deletion_race,
)


def test_postgres_file_lifecycle(postgres_engine):
    migrations.migrate(postgres_engine)
    check_lifecycle(postgres_engine)


def test_postgres_file_receipt_rollback(postgres_engine, monkeypatch):
    migrations.migrate(postgres_engine)
    check_rollback(postgres_engine, monkeypatch)


def test_postgres_file_verification_rollback(postgres_engine, monkeypatch):
    migrations.migrate(postgres_engine)
    check_verification_rollback(postgres_engine, monkeypatch)


def test_postgres_legacy_recovery(postgres_engine):
    migrations.migrate(postgres_engine)
    check_legacy_recovery(postgres_engine)


def test_postgres_legacy_deletion(postgres_engine, monkeypatch):
    migrations.migrate(postgres_engine)
    check_legacy_deletion(postgres_engine, monkeypatch)


def test_postgres_concurrent_verification(postgres_engine):
    migrations.migrate(postgres_engine)
    check_concurrent_verification(postgres_engine)


def test_postgres_registration_before_deletion(postgres_engine, monkeypatch):
    migrations.migrate(postgres_engine)
    check_registration_deletion_race(postgres_engine, monkeypatch, "registration")


def test_postgres_deletion_before_registration(postgres_engine, monkeypatch):
    migrations.migrate(postgres_engine)
    check_registration_deletion_race(postgres_engine, monkeypatch, "deletion")
