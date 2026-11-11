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
    from gigamind.db.migrations import schema_version

    admin, _, memory = records
    with trust.engine.begin() as conn:
        conn.execute(text("ALTER TABLE trust_knowledge DROP COLUMN valid_from"))
        conn.execute(text("ALTER TABLE trust_knowledge DROP COLUMN valid_until"))
        conn.execute(text("DELETE FROM schema_migrations"))
        conn.execute(text("INSERT INTO schema_migrations (version) VALUES (4)"))
    migrate(trust.engine)
    assert schema_version(trust.engine) == 5 and schema_ready(trust.engine)
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
