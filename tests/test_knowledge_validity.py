import pytest
from fastapi import HTTPException
from sqlmodel import create_engine

from gigamind.db.migrations import migrate, schema_ready
from gigamind.security import Actor
from gigamind.services import context, knowledge_validity as validity, trust


@pytest.fixture
def records(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/validity.db")
    migrate(engine)
    assert schema_ready(engine)
    monkeypatch.setattr(trust, "engine", engine)
    admin = Actor("admin", set(), None, True)
    agent = Actor("agent", {"memory:read", "memory:propose"}, {"a"})
    proposal = trust.create_proposal(
        agent,
        content="apple fact",
        project_id="a",
        evidence=[{"source_type": "doc", "source_id": "1", "quote": "x"}],
        idempotency_key="1",
    )["proposal"]
    memory = trust.resolve_proposal(
        admin, proposal["id"], action="approve", expected_revision=1
    )["memory"]
    return admin, agent, memory


def test_window_and_revision(records, monkeypatch):
    admin, agent, memory = records
    mid = memory["id"]
    updated = validity.set_validity(
        admin,
        mid,
        expected_revision=1,
        valid_from="2025-01-01T01:00:00+01:00",
        valid_until="2025-01-02T00:00:00Z",
    )["memory"]
    assert updated["valid_from"] == "2025-01-01T00:00:00.000000+00:00"
    assert updated["revision"] == 2
    monkeypatch.setattr(
        validity, "current_time", lambda: "2025-01-01T00:00:00.000000+00:00"
    )
    assert len(context.search_accepted(agent, "apple", "a")) == 1
    monkeypatch.setattr(
        validity, "current_time", lambda: "2025-01-02T00:00:00.000000+00:00"
    )
    assert context.search_accepted(agent, "apple", "a") == []
    for fn, actor in (
        (context.get_memory, admin),
        (trust.get_memory, agent),
        (trust.get_history, agent),
    ):
        with pytest.raises(HTTPException) as exc:
            fn(actor, mid)
        assert exc.value.status_code == 404
    assert len(trust.get_history(admin, mid)["revisions"]) == 2
    assert any(
        e["action"] == "validity" and e["revision"] == 2
        for e in trust.list_activity(admin)["events"]
    )
    with pytest.raises(HTTPException) as exc:
        trust.delete_memory(admin, mid, expected_revision=1)
    assert exc.value.status_code == 409
    trust.delete_memory(admin, mid, expected_revision=2)
    restored = trust.restore_memory(admin, mid, revision=2, expected_revision=3)[
        "memory"
    ]
    assert restored["valid_until"] == updated["valid_until"]
    assert context.search_accepted(agent, "apple", "a") == []


@pytest.mark.parametrize(
    "start,end",
    [
        ("2025-01-01", None),
        ("garbage", None),
        ("2025-01-02T00:00:00Z", "2025-01-01T00:00:00Z"),
    ],
)
def test_invalid_window_rolls_back(records, start, end):
    admin, agent, memory = records
    with pytest.raises(HTTPException) as exc:
        validity.set_validity(
            admin, memory["id"], expected_revision=1, valid_from=start, valid_until=end
        )
    assert exc.value.status_code == 422
    assert trust.get_memory(admin, memory["id"])["memory"]["revision"] == 1
    with pytest.raises(HTTPException) as exc:
        validity.set_validity(
            agent, memory["id"], expected_revision=1, valid_from=None, valid_until=None
        )
    assert exc.value.status_code == 403


def test_http_contract(records):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from gigamind.security import get_actor
    from gigamind.routers.review import router

    admin, agent, memory = records
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_actor] = lambda: admin
    client = TestClient(app)
    url = f"/api/v1/review/memories/{memory['id']}/validity"
    assert (
        client.post(
            url,
            json={"expected_revision": True, "valid_from": None, "valid_until": None},
        ).status_code
        == 422
    )
    assert (
        client.post(url, json={"expected_revision": 1, "valid_from": None}).status_code
        == 422
    )
    assert (
        client.post(
            url, json={"expected_revision": 1, "valid_from": None, "valid_until": None}
        ).status_code
        == 200
    )
    assert (
        client.post(
            url, json={"expected_revision": 1, "valid_from": None, "valid_until": None}
        ).status_code
        == 409
    )
    app.dependency_overrides[get_actor] = lambda: agent
    assert (
        client.post(
            url, json={"expected_revision": 2, "valid_from": None, "valid_until": None}
        ).status_code
        == 403
    )


def test_v4_upgrade_preserves_row(records):
    from sqlalchemy import text
    from gigamind.db.migrations import schema_version, VERSION

    admin, _, memory = records
    with trust.engine.begin() as conn:
        conn.execute(text("ALTER TABLE trust_knowledge DROP COLUMN valid_from"))
        conn.execute(text("ALTER TABLE trust_knowledge DROP COLUMN valid_until"))
        conn.execute(text("DELETE FROM schema_migrations"))
        conn.execute(text("INSERT INTO schema_migrations (version) VALUES (4)"))
    migrate(trust.engine)
    assert schema_version(trust.engine) == VERSION and schema_ready(trust.engine)
    row = trust.get_memory(admin, memory["id"])["memory"]
    assert (
        row["content"] == "apple fact"
        and row["valid_from"] is None
        and row["valid_until"] is None
    )


def test_concurrent_edit_delete(records):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    admin, _, memory = records
    barrier = Barrier(2)

    def run(action):
        barrier.wait(timeout=5)
        try:
            action()
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                run,
                [
                    lambda: validity.set_validity(
                        admin,
                        memory["id"],
                        expected_revision=1,
                        valid_from=None,
                        valid_until="2020-01-01T00:00:00Z",
                    ),
                    lambda: trust.delete_memory(
                        admin, memory["id"], expected_revision=1
                    ),
                ],
            )
        )
    assert sorted(results) == [200, 409]
    assert len(trust.get_history(admin, memory["id"])["revisions"]) == 2


def test_inactive_preference_excluded_before_limit(records, monkeypatch):
    admin, agent, memory = records
    validity.set_validity(
        admin,
        memory["id"],
        expected_revision=1,
        valid_from=None,
        valid_until="2020-01-01T00:00:00Z",
    )
    proposal = trust.create_proposal(
        agent,
        content="apple preference",
        project_id="a",
        kind="preference",
        evidence=[{"source_type": "doc", "source_id": "1", "quote": "x"}],
        idempotency_key="2",
    )["proposal"]
    rule = trust.resolve_proposal(
        admin, proposal["id"], action="approve", expected_revision=1
    )["memory"]
    assert [x["id"] for x in context.search_accepted(agent, "apple", "a", 1)] == [
        rule["id"]
    ]
    validity.set_validity(
        admin,
        rule["id"],
        expected_revision=1,
        valid_from=None,
        valid_until="2020-01-01T00:00:00Z",
    )
    monkeypatch.setattr(
        "gigamind.services.coordination.latest_handoff", lambda *args: {"handoff": None}
    )
    result = context.get_context(agent, "apple", "a", 4096)
    assert not result["rules"] and not result["memories"]


@pytest.mark.parametrize("failure", ["snapshot", "event"])
def test_validity_write_rolls_back_on_persistence_failure(
    records, monkeypatch, failure
):
    admin, _, memory = records
    before = trust.get_memory(admin, memory["id"])["memory"]
    history = trust.get_history(admin, memory["id"])
    activity = trust.list_activity(admin)

    def fail(*args, **kwargs):
        raise RuntimeError("injected persistence failure")

    with monkeypatch.context() as patch:
        patch.setattr(trust, failure, fail)
        with pytest.raises(RuntimeError, match="injected"):
            validity.set_validity(
                admin,
                memory["id"],
                expected_revision=1,
                valid_from=None,
                valid_until="2020-01-01T00:00:00Z",
            )
    assert trust.get_memory(admin, memory["id"])["memory"] == before
    assert trust.get_history(admin, memory["id"]) == history
    assert trust.list_activity(admin) == activity


def test_context_uses_one_instant(records, monkeypatch):
    admin, agent, memory = records
    proposal = trust.create_proposal(
        agent,
        content="Use Rust for coding",
        project_id="a",
        kind="preference",
        evidence=[{"source_type": "doc", "source_id": "1", "quote": "x"}],
        idempotency_key="clock-rule",
    )["proposal"]
    rule = trust.resolve_proposal(
        admin, proposal["id"], action="approve", expected_revision=1
    )["memory"]
    for item in (memory, rule):
        validity.set_validity(
            admin,
            item["id"],
            expected_revision=1,
            valid_from=None,
            valid_until="2025-01-02T00:00:00Z",
        )
    times = iter(
        ["2025-01-01T00:00:00.000000+00:00", "2025-01-02T00:00:00.000000+00:00"]
    )
    monkeypatch.setattr(validity, "current_time", lambda: next(times))
    result = context.get_context(agent, "apple", "a")
    assert [x["id"] for x in result["rules"]] == [rule["id"]]
    assert [x["id"] for x in result["memories"]] == [memory["id"]]


def test_restore_legacy_missing_bounds_and_explicit_null(records):
    import json
    from sqlmodel import Session, select
    from gigamind.db.trust_models import KnowledgeRevision

    admin, _, memory = records
    mid = memory["id"]
    validity.set_validity(
        admin,
        mid,
        expected_revision=1,
        valid_from=None,
        valid_until="2020-01-01T00:00:00Z",
    )
    with Session(trust.engine) as session:
        old = session.exec(
            select(KnowledgeRevision).where(
                KnowledgeRevision.memory_id == mid, KnowledgeRevision.revision == 1
            )
        ).one()
        data = json.loads(old.snapshot_json)
        del data["valid_from"], data["valid_until"]
        old.snapshot_json = json.dumps(data)
        session.add(old)
        session.commit()
    restored = trust.restore_memory(admin, mid, revision=1, expected_revision=2)[
        "memory"
    ]
    assert restored["valid_until"] == "2020-01-01T00:00:00.000000+00:00"
    validity.set_validity(
        admin, mid, expected_revision=3, valid_from=None, valid_until=None
    )
    validity.set_validity(
        admin,
        mid,
        expected_revision=4,
        valid_from=None,
        valid_until="2020-01-01T00:00:00Z",
    )
    restored = trust.restore_memory(admin, mid, revision=4, expected_revision=5)[
        "memory"
    ]
    assert restored["valid_until"] is None

@pytest.mark.parametrize("instant,expected", [
    ("2024-12-31T23:59:59.999999+00:00", "future"),
    ("2025-01-01T00:00:00.000000+00:00", "active"),
    ("2025-01-01T00:00:00.000001+00:00", "active"),
    ("2025-01-01T00:00:00.000002+00:00", "expired"),
])
def test_list_status_uses_one_instant(records, monkeypatch, instant, expected):
    from gigamind.services import knowledge_list

    admin, agent, memory = records
    validity.set_validity(admin, memory["id"], expected_revision=1,
                          valid_from="2025-01-01T01:00:00+01:00",
                          valid_until="2025-01-01T00:00:00.000002Z")
    history = trust.get_history(admin, memory["id"])
    calls = []
    def clock():
        calls.append(instant)
        return instant
    monkeypatch.setattr(validity, "current_time", clock)
    result = knowledge_list.list_knowledge(admin, project_id="a")
    assert result["as_of"] == instant
    assert result["memories"][0]["validity_status"] == expected
    assert len(calls) == 1
    calls.clear()
    scoped = knowledge_list.list_knowledge(agent, project_id="a")
    assert len(calls) == 1
    assert bool(scoped["memories"]) == (expected == "active")
    assert trust.get_history(admin, memory["id"]) == history


def test_list_http_inactive_and_scope(records, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from gigamind.routers.review import router
    from gigamind.security import get_actor

    admin, agent, memory = records
    trust.delete_memory(admin, memory["id"], expected_revision=1)
    monkeypatch.setattr(validity, "current_time", lambda: "2025-01-01T00:00:00.000001+00:00")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_actor] = lambda: admin
    client = TestClient(app)
    result = client.get("/api/v1/review/knowledge", params={"project_id": "a", "status": "deleted"})
    assert result.status_code == 200
    assert result.json()["as_of"] == "2025-01-01T00:00:00.000001+00:00"
    assert result.json()["memories"][0]["validity_status"] == "inactive"
    app.dependency_overrides[get_actor] = lambda: agent
    assert client.get("/api/v1/review/knowledge", params={"project_id": "a", "status": "deleted"}).status_code == 403
    assert client.get("/api/v1/review/knowledge", params={"project_id": "b"}).status_code == 403
