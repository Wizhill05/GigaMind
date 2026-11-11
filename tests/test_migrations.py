import pytest
from sqlalchemy import create_engine, text
from gigamind.db import database, migrations


def test_fresh_and_repeat(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'db'}")
    assert not migrations.schema_ready(engine)
    migrations.migrate(engine)
    assert migrations.schema_version(engine) == 1
    assert migrations.schema_ready(engine)
    migrations.migrate(engine)
    assert migrations.schema_ready(engine)


def test_legacy_upgrade_and_index(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'db'}")
    with engine.begin() as c:
        c.exec_driver_sql(
            "CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT, category TEXT, tags_json TEXT, embedding_json TEXT, created_at TEXT, last_accessed TEXT)"
        )
        c.exec_driver_sql(
            "INSERT INTO memories VALUES ('a','old','general','[]','[]','now','now')"
        )
    migrations.migrate(engine)
    with engine.begin() as c:
        assert c.execute(text("SELECT content, media_type FROM memories")).one() == (
            "old",
            "text",
        )
        c.exec_driver_sql("DROP INDEX uq_trust_accepted_project_subject")
    migrations.migrate(engine)
    assert migrations.schema_ready(engine)


def test_failure_rolls_back(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'db'}")

    def fail(conn):
        conn.exec_driver_sql("CREATE TABLE partial (id INTEGER)")
        raise RuntimeError("injected")

    monkeypatch.setattr(migrations, "_upgrade", fail)
    with pytest.raises(RuntimeError, match="injected"):
        migrations.migrate(engine)
    assert migrations.schema_version(engine) == 0
    with engine.connect() as c:
        assert not c.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE name='partial'"
        ).first()


def test_duplicate_trust_rejected(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'db'}")
    migrations.migrate(engine)
    with engine.begin() as c:
        c.exec_driver_sql("DROP INDEX uq_trust_accepted_project_subject")
        c.exec_driver_sql("DELETE FROM schema_migrations")
        c.exec_driver_sql(
            "INSERT INTO trust_knowledge (id, proposal_id, subject, content, data_json, writer_id, status, revision, created_at, updated_at) VALUES ('1','p1','same','a','{}','w','accepted',1,'x','x'), ('2','p2','same','b','{}','w','accepted',1,'x','x')"
        )
    with pytest.raises(Exception, match="UNIQUE constraint failed"):
        migrations.migrate(engine)
    assert migrations.schema_version(engine) == 0


def test_attachment_backfill_pending_and_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'db'}")
    with engine.begin() as c:
        c.exec_driver_sql(
            "CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT, category TEXT, tags_json TEXT, embedding_json TEXT, created_at TEXT, last_accessed TEXT, media_url TEXT)"
        )
        c.exec_driver_sql(
            "INSERT INTO memories VALUES ('a','old','general','[]','[]','now','now','docs/a.pdf')"
        )
    migrations.migrate(engine)
    migrations.migrate(engine)
    with engine.connect() as c:
        assert c.exec_driver_sql(
            "SELECT key, indexing_status FROM storage_files"
        ).all() == [("docs/a.pdf", "pending")]


def test_trust_index_compiles_for_postgresql():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex
    from gigamind.db.trust_models import AcceptedKnowledge

    index = next(
        i
        for i in AcceptedKnowledge.__table__.indexes
        if i.name == "uq_trust_accepted_project_subject"
    )
    ddl = str(
        CreateIndex(index, if_not_exists=True).compile(dialect=postgresql.dialect())
    )
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in ddl
    assert "coalesce" in ddl.lower()
    assert "status = 'accepted'" in ddl


def test_application_readiness_checks_schema(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from gigamind import main

    engine = create_engine(
        f"sqlite:///{tmp_path / 'ready.db'}", connect_args={"check_same_thread": False}
    )
    migrations.migrate(engine)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setenv("GIGAMIND_API_KEY", "readiness-test-admin")
    client = TestClient(main.app)
    assert client.get("/health/ready").status_code == 200
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_trust_accepted_project_subject"))
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["detail"] == "Database schema is not ready"
    migrations.migrate(engine)
    assert client.get("/health/ready").status_code == 200
    monkeypatch.delenv("GIGAMIND_API_KEY")
    assert client.get("/health/ready").status_code == 503


def test_invalid_attachment_backfill_rolls_back_version(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'attachments.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT, category TEXT, tags_json TEXT, embedding_json TEXT, created_at TEXT, last_accessed TEXT, attachments_json TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO memories VALUES ('invalid', 'retained', 'general', '[]', '[]', 'now', 'now', '{\"key\":\"wrong-shape\"}')"
            )
        )
    with pytest.raises(ValueError, match="Invalid attachment list for memory invalid"):
        migrations.migrate(engine)
    assert migrations.schema_version(engine) == 0
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT content FROM memories")).scalar_one()
            == "retained"
        )
