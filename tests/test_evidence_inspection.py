import json
import pytest
from gigamind.db.memory_index import MemoryIndexState
from gigamind.services import evidence_inspection as inspection

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, select

from gigamind.db.database import MemoryItem, ConversationItem, StorageChunkItem
from gigamind.db.jobs import ResourceJobState
from gigamind.db.migrations import migrate
from gigamind.db.trust_models import ActivityEvent
from gigamind.routers.review import router
from gigamind.security import Actor, get_actor
from gigamind.services import trust


def test_inspection_contract_and_access(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path}/db", connect_args={"check_same_thread": False}
    )
    migrate(engine)
    monkeypatch.setattr(trust, "engine", engine)
    admin = Actor("admin", set(), None, True)
    agent = Actor("agent", {"memory:propose"}, {"a"})
    entries = [
        {"source_type": "memory", "source_id": "m", "quote": "🌟b"},
        {"source_type": "memory", "source_id": "m", "quote": "missing"},
        {
            "source_type": "conversation",
            "source_id": "c",
            "quote": "hello",
            "source_role": "user",
        },
        {"source_type": "file_chunk", "source_id": "f", "quote": "secret"},
        {"source_type": "memory", "source_id": "large", "quote": "absent"},
        {"source_type": "memory", "source_id": "absent", "quote": "x"},
        {"source_type": "url", "source_id": "x", "quote": "x"},
    ]
    p = trust.create_proposal(
        agent,
        content="claim",
        project_id="a",
        subject=None,
        category="general",
        tags=[],
        kind="fact",
        evidence=entries,
        idempotency_key="key",
    )["proposal"]
    with Session(engine) as s:
        s.add(MemoryItem(id="m", content="a🌟b", created_at="now", last_accessed="now"))
        s.add(
            MemoryItem(
                id="large", content="a" * 100001, created_at="now", last_accessed="now"
            )
        )
        s.add(
            ConversationItem(
                id="c",
                platform="test",
                title="",
                summary="",
                messages_json=json.dumps([{"role": "assistant", "content": "hello"}]),
                created_at="now",
            )
        )
        s.add(
            StorageChunkItem(
                id="f",
                file_id="file",
                file_key="key",
                filename="f",
                content="secret",
                created_at="now",
            )
        )
        s.add(
            ResourceJobState(
                key="key", deleted=True, created_at="now", updated_at="now"
            )
        )
        s.commit()
        before = len(s.exec(select(ActivityEvent)).all())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    url = f"/api/v1/review/proposals/{p['id']}/inspect-evidence"
    assert client.post(url, json={"expected_revision": 1}).status_code == 401
    app.dependency_overrides[get_actor] = lambda: agent
    assert client.post(url, json={"expected_revision": 1}).status_code == 403
    app.dependency_overrides[get_actor] = lambda: admin
    assert client.post(url, json={"expected_revision": True}).status_code == 422
    assert client.post(url, json={"expected_revision": 2}).status_code == 409
    assert (
        client.post(
            "/api/v1/review/proposals/no/inspect-evidence",
            json={"expected_revision": 1},
        ).status_code
        == 404
    )
    response = client.post(url, json={"expected_revision": 1})
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"proposal_id", "proposal_revision", "inspected_at", "evidence"}
    rows = data["evidence"]
    assert [x["status"] for x in rows] == [
        "matched",
        "quote_mismatch",
        "role_mismatch",
        "not_found",
        "unresolved",
        "not_found",
        "unsupported",
    ]
    assert rows[0]["matched_span"] == {"start": 1, "end": 3}
    assert rows[2]["recorded_role"] == "assistant" and not rows[2]["role_verified"]
    assert rows[3]["excerpt"] is None
    assert set(rows[0]) == {
        "index",
        "source_type",
        "source_id",
        "status",
        "quote_match",
        "claimed_role",
        "recorded_role",
        "role_verified",
        "excerpt",
        "matched_span",
        "source_hash",
        "source_revision",
        "locator",
        "note",
    }
    with Session(engine) as s:
        assert len(s.exec(select(ActivityEvent)).all()) == before


@pytest.fixture
def sources(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sources.db'}",
        connect_args={"check_same_thread": False},
    )
    migrate(engine)
    monkeypatch.setattr(trust, "engine", engine)
    admin = Actor("admin", set(), None, True)
    with Session(engine) as session:
        session.add(
            MemoryItem(id="m", content="a🌟b", created_at="now", last_accessed="now")
        )
        session.add(
            MemoryIndexState(
                memory_id="m", revision=7, created_at="now", updated_at="now"
            )
        )
        session.commit()

    def proposal(entries):
        return trust.create_proposal(
            admin, content="claim", evidence=entries, idempotency_key=trust.uid()
        )["proposal"]["id"]

    yield engine, admin, proposal
    engine.dispose()


def test_byte_budget_cache_revision_and_read_only(sources, monkeypatch):
    engine, admin, proposal = sources
    entries = [{"source_type": "memory", "source_id": "m", "quote": "🌟b"}] * 2
    pid = proposal(entries)
    monkeypatch.setattr(inspection, "MAX_REQUEST", 6)
    result = inspection.inspect(admin, pid, 1)
    assert all(
        row["status"] == "matched" and row["source_revision"] == 7
        for row in result["evidence"]
    )
    assert len(result["evidence"][0]["excerpt"]) <= 1200
    monkeypatch.setattr(inspection, "MAX_SOURCE", 5)
    assert inspection.inspect(admin, pid, 1)["evidence"][0]["status"] == "unresolved"
    with Session(engine) as session:
        assert session.get(MemoryIndexState, "m").revision == 7
        assert session.get(inspection.MemoryProposal, pid).revision == 1
        assert len(session.exec(select(ActivityEvent)).all()) == 1


def test_tombstone_at_source_read_never_returns_text(sources):
    from sqlalchemy import event

    engine, admin, proposal = sources
    with Session(engine) as session:
        session.add(
            StorageChunkItem(
                id="f",
                file_id="parent",
                file_key="file-key",
                filename="file",
                content="private",
                created_at="now",
            )
        )
        session.add(
            ResourceJobState(key="file-key", created_at="now", updated_at="now")
        )
        session.commit()
    pid = proposal(
        [{"source_type": "file_chunk", "source_id": "f", "quote": "private"}]
    )
    fired = []

    def deletion(connection, cursor, statement, parameters, context, many):
        if not fired and "CASE WHEN" in statement and "storage_chunks" in statement:
            fired.append(True)
            with Session(engine) as session:
                owner = session.get(ResourceJobState, "file-key")
                owner.deleted = True
                session.add(owner)
                session.commit()

    event.listen(engine, "before_cursor_execute", deletion)
    try:
        row = inspection.inspect(admin, pid, 1)["evidence"][0]
        assert fired and row["status"] == "not_found" and row["excerpt"] is None
    finally:
        event.remove(engine, "before_cursor_execute", deletion)


def test_revision_change_during_inspection_fails_closed(sources, monkeypatch):
    from fastapi import HTTPException

    engine, admin, proposal = sources
    pid = proposal([{"source_type": "memory", "source_id": "m", "quote": "🌟b"}])
    original = inspection._load

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        with Session(engine) as session:
            record = session.get(inspection.MemoryProposal, pid)
            record.revision = 2
            session.add(record)
            session.commit()
        return result

    monkeypatch.setattr(inspection, "_load", changed)
    with pytest.raises(HTTPException) as exc:
        inspection.inspect(admin, pid, 1)
    assert exc.value.status_code == 409


def test_actual_http_credentials_are_checked_before_loading_sources(
    sources, monkeypatch
):
    from gigamind.main import app

    engine, admin, proposal = sources
    pid = proposal([{"source_type": "memory", "source_id": "m", "quote": "🌟b"}])
    with TestClient(app) as client:
        url = f"/api/v1/review/proposals/{pid}/inspect-evidence"
        header = {"Authorization": "Bearer offline-test-master-key"}
        issued = client.post(
            "/api/v1/admin/clients",
            headers=header,
            json={
                "name": "inspector-denial",
                "scopes": ["memory:read", "memory:propose"],
                "project_ids": ["a"],
            },
        ).json()
        assert client.post(url, json={"expected_revision": 1}).status_code == 401
        assert (
            client.post(
                url,
                headers={"Authorization": "Bearer " + issued["token"]},
                json={"expected_revision": 1},
            ).status_code
            == 403
        )
        response = client.post(url, headers=header, json={"expected_revision": 1})
        assert (
            response.status_code == 200
            and response.json()["evidence"][0]["source_revision"] == 7
        )


def test_native_source_bytes_and_backslashes(postgres_engine, monkeypatch):
    migrate(postgres_engine)
    monkeypatch.setattr(trust, "engine", postgres_engine)
    admin = Actor("admin", set(), None, True)
    value = "Unicode 🌟 and \\xnotbytea\\ literal"
    with Session(postgres_engine) as session:
        session.add(
            MemoryItem(id="m", content=value, created_at="now", last_accessed="now")
        )
        session.commit()
    pid = trust.create_proposal(
        admin,
        content="claim",
        evidence=[{"source_type": "memory", "source_id": "m", "quote": value}],
        idempotency_key="native",
    )["proposal"]["id"]
    row = inspection.inspect(admin, pid, 1)["evidence"][0]
    assert row["status"] == "matched" and row["excerpt"] == value


from tests.test_postgres_migrations import postgres_engine  # noqa: F401, fixture


def test_invalid_unicode_source_is_unresolved(sources):
    engine, admin, proposal = sources
    with Session(engine) as session:
        session.add(
            ConversationItem(
                id="invalid",
                platform="test",
                title="",
                summary="",
                messages_json=json.dumps([{"role": "user", "content": "quote\ud800"}]),
                created_at="now",
            )
        )
        session.commit()
    pid = proposal(
        [{"source_type": "conversation", "source_id": "invalid", "quote": "quote"}]
    )
    row = inspection.inspect(admin, pid, 1)["evidence"][0]
    assert row["status"] == "unresolved" and row["excerpt"] is None


def test_programming_and_database_failures_are_not_source_mismatches(
    sources, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    engine, admin, proposal = sources
    pid = proposal([{"source_type": "memory", "source_id": "m", "quote": "🌟b"}])
    with monkeypatch.context() as patch:

        def broken(*args, **kwargs):
            raise RuntimeError("programming failure")

        patch.setattr(inspection, "_load", broken)
        with pytest.raises(RuntimeError, match="programming failure"):
            inspection.inspect(admin, pid, 1)
    MemoryItem.__table__.drop(engine)
    with pytest.raises(OperationalError):
        inspection.inspect(admin, pid, 1)
