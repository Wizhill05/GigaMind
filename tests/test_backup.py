import os
import sqlite3
import subprocess
import sys

import pytest
from sqlalchemy import create_engine
from gigamind.db import database, migrations  # register models
from gigamind.db import memory_index
from gigamind import security
from gigamind.db.jobs import Job, UploadManifest
from gigamind.services.backup import backup, restore


def fixture_db(path):
    engine = create_engine(f"sqlite:///{path}")
    migrations.migrate(engine)
    from sqlmodel import Session

    with Session(engine) as session:
        session.add(
            database.MemoryItem(
                id="m", content="hello", created_at="now", last_accessed="now"
            )
        )
        session.add(
            security.ClientCredential(
                id="c",
                name="client",
                token_hash="hash",
                scopes_json='["memory:read"]',
                project_ids_json='["p"]',
                revoked=True,
                revision=4,
            )
        )
        session.add(
            Job(
                id="j",
                kind="index",
                resource_key="m",
                payload_json="{}",
                state="queued",
                available_at="now",
                created_at="now",
                updated_at="now",
            )
        )
        session.add(UploadManifest(key="k", job_id="j", sha256="abc", size_bytes=1))
        session.add(
            memory_index.MemoryIndexState(
                memory_id="m", revision=3, created_at="now", updated_at="now"
            )
        )
        session.commit()
    engine.dispose()


def test_roundtrip_and_exclusive_targets(tmp_path):
    source, snapshot, restored = (
        tmp_path / n for n in ("source", "snapshot", "restored")
    )
    fixture_db(source)
    before = source.read_bytes()
    assert len(backup(source, snapshot)) == 64
    assert snapshot.stat().st_mode & 0o777 == 0o600
    restore(snapshot, restored)
    with sqlite3.connect(restored) as conn:
        assert conn.execute("select content from memories").fetchone() == ("hello",)
        assert conn.execute(
            "select revoked, revision, scopes_json from client_credentials"
        ).fetchone() == (1, 4, '["memory:read"]')
        assert conn.execute("select state from jobs").fetchone() == ("queued",)
        assert conn.execute("select job_id from upload_manifests").fetchone() == ("j",)
        assert conn.execute("select revision from memory_index_state").fetchone() == (
            3,
        )
    assert source.read_bytes() == before
    with pytest.raises(FileExistsError):
        backup(source, snapshot)
    link = tmp_path / "link"
    link.symlink_to(snapshot)
    with pytest.raises((FileExistsError, ValueError)):
        backup(source, link)
    assert link.is_symlink()


def test_failure_cleans_output(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    fixture_db(source)

    def fail(engine):
        raise RuntimeError("migration failed")

    monkeypatch.setattr(migrations, "migrate", fail)
    with pytest.raises(RuntimeError, match="migration failed"):
        restore(source, target)
    assert not target.exists()
    source.write_bytes(b"corrupt")
    with pytest.raises(sqlite3.DatabaseError):
        restore(source, target)
    assert not target.exists()


def test_future_version_rejected(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    fixture_db(source)
    with sqlite3.connect(source) as conn:
        conn.execute(
            "insert into schema_migrations values (?)", (migrations.VERSION + 1,)
        )
    with pytest.raises(ValueError, match="Unsupported schema"):
        restore(source, target)
    assert not target.exists()


def test_cli_ignores_hostile_environment(tmp_path):
    source, target, sentinel = (tmp_path / n for n in ("source", "target", "sentinel"))
    fixture_db(source)
    sentinel.write_bytes(b"do not touch")
    env = dict(
        os.environ,
        DATABASE_URL="postgresql://invalid/remote",
        DB_PATH=str(sentinel),
        ENVIRONMENT="production",
        RENDER="1",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gigamind.cli.backup",
            "restore",
            "--db",
            str(source),
            "--output",
            str(target),
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert sentinel.read_bytes() == b"do not touch"


def test_expected_input_digest_and_cli(tmp_path):
    source, snapshot, target = (tmp_path / n for n in ("source", "snapshot", "target"))
    fixture_db(source)
    digest = backup(source, snapshot)
    original = snapshot.read_bytes()
    for invalid in ("bad", "0" * 64):
        with pytest.raises(ValueError):
            restore(snapshot, target, invalid)
        assert not target.exists()
        assert snapshot.read_bytes() == original
    target.write_bytes(b"existing")
    with pytest.raises(ValueError):
        restore(snapshot, target, "0" * 64)
    assert target.read_bytes() == b"existing"
    target.unlink()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gigamind.cli.backup",
            "restore",
            "--db",
            str(snapshot),
            "--output",
            str(target),
            "--expected-sha256",
            digest,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert target.exists()


def test_snapshot_during_wal_transactions(tmp_path):
    from threading import Barrier, Thread

    source, snapshot, restored = (
        tmp_path / n for n in ("source", "snapshot", "restored")
    )
    fixture_db(source)
    writer = sqlite3.connect(source)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute(
        "CREATE TABLE pairs (generation INTEGER, side INTEGER, PRIMARY KEY(generation, side))"
    )
    writer.commit()
    writer.execute("INSERT INTO pairs VALUES (0, 0), (0, 1)")
    writer.commit()
    barrier = Barrier(2)
    errors = []

    def write():
        try:
            with sqlite3.connect(source, timeout=5) as conn:
                barrier.wait(timeout=5)
                for generation in range(1, 201):
                    with conn:
                        conn.execute("INSERT INTO pairs VALUES (?, 0)", (generation,))
                        conn.execute("INSERT INTO pairs VALUES (?, 1)", (generation,))
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=write)
    thread.start()
    try:
        barrier.wait(timeout=5)
        backup(source, snapshot)
    finally:
        thread.join(timeout=10)
        writer.close()
    assert not thread.is_alive()
    assert not errors
    restore(snapshot, restored)
    with sqlite3.connect(restored) as conn:
        rows = conn.execute(
            "SELECT generation, count(*), sum(side) FROM pairs GROUP BY generation ORDER BY generation"
        ).fetchall()
    assert rows and rows[0] == (0, 2, 1)
    assert all(count == 2 and total == 1 for _, count, total in rows)
    assert [row[0] for row in rows] == list(range(len(rows)))


def test_service_workflows_survive_restore(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from sqlmodel import Session
    from gigamind.services import trust, context
    from gigamind.db.jobs import ResourceJobState

    source, snapshot, restored = (
        tmp_path / n for n in ("source", "snapshot", "restored")
    )
    fixture_db(source)
    engine = create_engine(f"sqlite:///{source}")
    monkeypatch.setattr(security, "engine", engine)
    monkeypatch.setattr(trust, "engine", engine)
    client, token = security.create_client(
        "reader", ["memory:read", "memory:propose"], ["p"]
    )
    revoked, revoked_token = security.create_client("revoked", ["memory:read"], ["p"])
    with Session(engine) as session:
        credential = session.get(security.ClientCredential, revoked.id)
        credential.revoked = True
        session.add(credential)
        session.add(
            ResourceJobState(
                key="m", current_job_id="j", created_at="now", updated_at="now"
            )
        )
        manifest = session.get(UploadManifest, "k")
        manifest.sha256 = "a" * 64
        session.add(manifest)
        session.commit()
    actor = security.get_actor("Bearer " + token)
    admin = security.Actor("admin", set(), None, True)

    def propose(key, content):
        return trust.create_proposal(
            actor,
            content=content,
            project_id="p",
            subject="topic",
            evidence=[{"source_type": "doc", "source_id": "1", "quote": "text"}],
            idempotency_key=key,
        )["proposal"]

    first = propose("first", "original knowledge")
    old = trust.resolve_proposal(
        admin, first["id"], action="approve", expected_revision=1
    )["memory"]
    second = propose("second", "replacement knowledge")
    new = trust.resolve_proposal(
        admin,
        second["id"],
        action="approve",
        expected_revision=1,
        supersedes=[old["id"]],
    )["memory"]
    trust.delete_memory(admin, new["id"], expected_revision=1)
    third = trust.create_proposal(
        actor,
        content="active replacement",
        project_id="p",
        subject="other",
        evidence=[{"source_type": "doc", "source_id": "1", "quote": "text"}],
        idempotency_key="third",
    )["proposal"]
    trust.resolve_proposal(admin, third["id"], action="approve", expected_revision=1)
    before_history = trust.get_history(admin, new["id"])
    before_context = context.get_context(actor, "replacement", "p")
    assert before_context["memories"]
    digest = backup(source, snapshot)
    restore(snapshot, restored, digest)
    restored_engine = create_engine(f"sqlite:///{restored}")
    monkeypatch.setattr(security, "engine", restored_engine)
    monkeypatch.setattr(trust, "engine", restored_engine)
    restored_actor = security.get_actor("Bearer " + token)
    assert restored_actor.id == client.id and restored_actor.project_ids == {"p"}
    with pytest.raises(HTTPException) as denied:
        security.get_actor("Bearer " + revoked_token)
    assert denied.value.status_code == 401
    assert trust.get_history(admin, new["id"]) == before_history
    assert context.get_context(restored_actor, "replacement", "p") == before_context
    assert (
        trust.get_memory(restored_actor, old["id"])["memory"]["status"] == "superseded"
    )
    with Session(restored_engine) as session:
        assert session.get(ResourceJobState, "m").current_job_id == "j"
        assert session.get(UploadManifest, "k").sha256 == "a" * 64
        assert session.get(Job, "j").state == "queued"
        assert session.get(memory_index.MemoryIndexState, "m").revision == 3
    engine.dispose()
    restored_engine.dispose()
