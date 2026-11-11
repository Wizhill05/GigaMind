import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlmodel import create_engine
from gigamind.db.trust_models import initialize_trust_tables
from gigamind.security import Actor, get_actor
from gigamind.services import trust
from gigamind.routers.review import router
from gigamind.services import context


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}
    )
    initialize_trust_tables(engine)
    monkeypatch.setattr(trust, "engine", engine)
    admin = Actor("human", set(), None, True)
    agent = Actor("agent", {"memory:read", "memory:propose", "memory:approve"}, {"a"})
    return admin, agent


def proposal(actor, key="one", content="first", project="a"):
    return trust.create_proposal(
        actor,
        content=content,
        project_id=project,
        subject="topic",
        evidence=[{"source_type": "doc", "source_id": "1", "quote": "text"}],
        idempotency_key=key,
    )["proposal"]


def error(code, fn, *args, **kwargs):
    with pytest.raises(HTTPException) as exc:
        fn(*args, **kwargs)
    assert exc.value.status_code == code


def test_delete_persists_and_hides_content(setup):
    admin, agent = setup
    p = proposal(agent)
    m = trust.resolve_proposal(admin, p["id"], action="approve", expected_revision=1)[
        "memory"
    ]
    error(403, trust.delete_memory, agent, m["id"], expected_revision=1)
    deleted = trust.delete_memory(admin, m["id"], expected_revision=1)["memory"]
    assert (deleted["status"], deleted["revision"], deleted["content"]) == (
        "deleted",
        2,
        "first",
    )
    trust.engine.dispose()
    error(409, trust.delete_memory, admin, m["id"], expected_revision=1)
    for fn in (trust.get_memory, trust.get_history, context.get_memory):
        error(404, fn, agent, m["id"])
    error(404, context.get_memory, admin, m["id"])
    assert context.search_accepted(agent, "first", "a") == []
    result = context.get_context(agent, "first", "a")
    assert result["memories"] == [] and result["rules"] == []
    assert [r["status"] for r in trust.get_history(admin, m["id"])["revisions"]] == [
        "accepted",
        "deleted",
    ]
    error(403, trust.restore_memory, agent, m["id"], revision=1, expected_revision=2)
    assert (
        trust.restore_memory(admin, m["id"], revision=1, expected_revision=2)["memory"][
            "status"
        ]
        == "accepted"
    )


def test_delete_restore_race(setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    admin, agent = setup
    p = proposal(agent)
    m = trust.resolve_proposal(admin, p["id"], action="approve", expected_revision=1)[
        "memory"
    ]
    barrier = Barrier(2)

    def run(fn):
        barrier.wait(timeout=5)
        try:
            fn()
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                run,
                [
                    lambda: trust.delete_memory(admin, m["id"], expected_revision=1),
                    lambda: trust.restore_memory(
                        admin, m["id"], revision=1, expected_revision=1
                    ),
                ],
            )
        )
    assert sorted(results) == [200, 409]
    assert len(trust.get_history(admin, m["id"])["revisions"]) == 2
    events = trust.list_activity(admin)["events"]
    assert sum(e["action"] in ("delete", "restore") for e in events) == 1


def test_delete_and_approval_race_preserves_subject_uniqueness(setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlmodel import Session, select
    from gigamind.db.trust_models import AcceptedKnowledge

    admin, agent = setup
    first = proposal(agent)
    memory = trust.resolve_proposal(
        admin, first["id"], action="approve", expected_revision=1
    )["memory"]
    second = proposal(agent, "second", "second")
    barrier = Barrier(2)

    def run(fn):
        barrier.wait(timeout=5)
        try:
            fn()
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                run,
                [
                    lambda: trust.delete_memory(
                        admin, memory["id"], expected_revision=1
                    ),
                    lambda: trust.resolve_proposal(
                        admin, second["id"], action="approve", expected_revision=1
                    ),
                ],
            )
        )
    assert results[0] == 200 and results[1] in (200, 409)
    with Session(trust.engine) as session:
        accepted = session.exec(
            select(AcceptedKnowledge).where(
                AcceptedKnowledge.project_id == "a",
                AcceptedKnowledge.subject == "topic",
                AcceptedKnowledge.status == "accepted",
            )
        ).all()
    assert len(accepted) <= 1
    assert len(trust.get_history(admin, memory["id"])["revisions"]) == 2
    assert (
        sum(e["action"] == "delete" for e in trust.list_activity(admin)["events"]) == 1
    )


def test_lifecycle(setup):
    admin, agent = setup
    p = proposal(agent)
    assert proposal(agent)["id"] == p["id"]
    error(409, proposal, agent, content="different")
    error(404, trust.get_memory, agent, p["id"])
    error(
        403,
        trust.resolve_proposal,
        agent,
        p["id"],
        action="approve",
        expected_revision=1,
    )
    out = trust.resolve_proposal(admin, p["id"], action="approve", expected_revision=1)
    m = out["memory"]
    assert m["content"] == "first"
    error(
        409,
        trust.resolve_proposal,
        admin,
        p["id"],
        action="approve",
        expected_revision=1,
    )
    assert (
        trust.get_history(agent, m["id"])["revisions"][0]["snapshot"]["evidence"][0][
            "quote"
        ]
        == "text"
    )
    second = proposal(agent, "two", "second")
    assert trust.list_proposals(agent)["proposals"][1]["conflicts"] == [m["id"]]
    error(
        409,
        trust.resolve_proposal,
        admin,
        second["id"],
        action="approve",
        expected_revision=1,
    )
    trust.resolve_proposal(
        admin, second["id"], action="approve", expected_revision=1, supersedes=[m["id"]]
    )
    assert trust.get_memory(agent, m["id"])["memory"]["status"] == "superseded"
    error(409, trust.restore_memory, admin, m["id"], revision=1, expected_revision=2)
    restored = trust.restore_memory(admin, m["id"], revision=2, expected_revision=2)[
        "memory"
    ]
    assert restored["revision"] == 3
    error(409, trust.restore_memory, admin, m["id"], revision=2, expected_revision=2)
    assert len(trust.get_history(admin, m["id"])["revisions"]) == 3
    rejected = proposal(agent, "three", "third")
    assert (
        trust.resolve_proposal(
            admin, rejected["id"], action="reject", expected_revision=1
        )["proposal"]["status"]
        == "rejected"
    )
    assert trust.list_activity(agent)["events"]


def test_project_and_router(setup):
    admin, agent = setup
    p = proposal(admin, project="b")
    m = trust.resolve_proposal(admin, p["id"], action="approve", expected_revision=1)[
        "memory"
    ]
    assert trust.list_proposals(agent)["total"] == 0
    for fn in (trust.get_memory, trust.get_history):
        error(403, fn, agent, m["id"])
    error(403, trust.list_proposals, agent, "b")
    error(403, trust.restore_memory, agent, m["id"], revision=1, expected_revision=1)
    error(403, proposal, agent, project=None)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_actor] = lambda: agent
    client = TestClient(app)
    assert client.get("/api/v1/review/proposals").json()["total"] == 0
    assert client.get(f"/api/v1/review/memories/{m['id']}/history").status_code == 403
    assert (
        client.post(
            f"/api/v1/review/proposals/{p['id']}/resolve",
            json={"action": "approve", "expected_revision": 1},
        ).status_code
        == 403
    )
    app.dependency_overrides.clear()
    assert client.get("/api/v1/review/activity").status_code == 401


def test_validation_dedup_and_database_constraint(setup):
    from sqlalchemy.exc import IntegrityError
    from sqlmodel import Session
    from gigamind.db.trust_models import AcceptedKnowledge

    admin, agent = setup
    error(
        422,
        trust.create_proposal,
        agent,
        content="x",
        project_id="a",
        evidence=[{"source_type": "doc", "source_id": None, "quote": None}],
        idempotency_key="bad",
    )
    first = proposal(agent)
    memory = trust.resolve_proposal(
        admin, first["id"], action="approve", expected_revision=1
    )["memory"]
    second = proposal(agent, "same")
    result = trust.resolve_proposal(
        admin, second["id"], action="approve", expected_revision=1
    )
    assert result["memory"]["id"] == memory["id"]
    assert result["proposal"]["accepted_memory_id"] == memory["id"]
    assert proposal(agent)["id"] == first["id"]
    with Session(trust.engine) as session:
        session.add(
            AcceptedKnowledge(
                id="duplicate",
                proposal_id="x",
                project_id="a",
                subject="topic",
                content="x",
                data_json="{}",
                writer_id="x",
                created_at="x",
                updated_at="x",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_concurrent_approvals_global(setup, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    admin, _ = setup
    one = proposal(admin, "global1", "first", None)
    two = proposal(admin, "global2", "second", None)
    barrier = Barrier(2)
    original = trust.conflicts

    def synchronized(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(trust, "conflicts", synchronized)

    def approve(p):
        try:
            return trust.resolve_proposal(
                admin, p["id"], action="approve", expected_revision=1
            )
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(approve, (one, two)))
    assert sum(isinstance(x, dict) for x in outcomes) == 1
    assert 409 in outcomes


def test_postgresql_index_ddl():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex
    from gigamind.db.trust_models import AcceptedKnowledge

    index = next(
        i
        for i in AcceptedKnowledge.__table__.indexes
        if i.name == "uq_trust_accepted_project_subject"
    )
    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "UNIQUE INDEX" in ddl
    assert "coalesce" in ddl.lower()
    assert "status = 'accepted' AND subject IS NOT NULL" in ddl


@pytest.mark.parametrize("project", [None, "a"])
def test_restore_and_approval_compete_atomically(setup, monkeypatch, project):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlmodel import Session, select
    from gigamind.db.trust_models import (
        AcceptedKnowledge,
        MemoryProposal,
        KnowledgeRevision,
    )

    admin, _ = setup
    first = proposal(admin, "restore-initial", "original", project)
    memory = trust.resolve_proposal(
        admin, first["id"], action="approve", expected_revision=1
    )["memory"]
    with Session(trust.engine) as session:
        old = session.get(AcceptedKnowledge, memory["id"])
        old.status = "superseded"
        old.revision = 2
        trust.snapshot(session, old, admin)
        session.add(old)
        session.commit()
    candidate = proposal(admin, "restore-competitor", "replacement", project)
    barrier = Barrier(2)
    original = trust.conflicts

    def synchronized(*args, **kwargs):
        found = original(*args, **kwargs)
        barrier.wait(timeout=10)
        return found

    monkeypatch.setattr(trust, "conflicts", synchronized)

    def run(operation):
        try:
            return operation()
        except HTTPException as exc:
            return exc.status_code

    operations = [
        lambda: trust.restore_memory(
            admin, memory["id"], revision=1, expected_revision=2
        ),
        lambda: trust.resolve_proposal(
            admin, candidate["id"], action="approve", expected_revision=1
        ),
    ]
    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(run, operations))
    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert 409 in outcomes
    with Session(trust.engine) as session:
        active = session.exec(
            select(AcceptedKnowledge).where(AcceptedKnowledge.status == "accepted")
        ).all()
        assert len(active) == 1
        stored_proposal = session.get(MemoryProposal, candidate["id"])
        stored_original = session.get(AcceptedKnowledge, memory["id"])
        revisions = session.exec(
            select(KnowledgeRevision).where(KnowledgeRevision.memory_id == memory["id"])
        ).all()
        if active[0].id == memory["id"]:
            assert stored_proposal.status == "proposed"
            assert stored_proposal.revision == 1
            assert stored_original.revision == 3
            assert len(revisions) == 3
        else:
            assert stored_proposal.status == "accepted"
            assert stored_original.status == "superseded"
            assert stored_original.revision == 2
            assert len(revisions) == 2


def test_concurrent_idempotent_creation_has_one_proposal_and_event(setup, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlmodel import Session, select
    from gigamind.db.trust_models import MemoryProposal, ActivityEvent

    _, agent = setup
    barrier = Barrier(2)
    original = trust.event

    def synchronized(*args, **kwargs):
        original(*args, **kwargs)
        barrier.wait(timeout=10)

    monkeypatch.setattr(trust, "event", synchronized)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: proposal(agent), range(2)))
    assert results[0]["id"] == results[1]["id"]
    with Session(trust.engine) as session:
        assert len(session.exec(select(MemoryProposal)).all()) == 1
        assert len(session.exec(select(ActivityEvent)).all()) == 1


def test_upgrade_adds_missing_subject_index(setup):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from sqlmodel import Session
    from gigamind.db.trust_models import AcceptedKnowledge, initialize_trust_tables

    admin, agent = setup
    first = proposal(agent)
    trust.resolve_proposal(admin, first["id"], action="approve", expected_revision=1)
    with trust.engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_trust_accepted_project_subject"))
    initialize_trust_tables(trust.engine)
    initialize_trust_tables(trust.engine)
    with Session(trust.engine) as session:
        session.add(
            AcceptedKnowledge(
                id="upgrade-duplicate",
                proposal_id="x",
                project_id="a",
                subject="topic",
                content="different",
                data_json="{}",
                writer_id="x",
                created_at="x",
                updated_at="x",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_validation_normalization_and_global_visibility(setup):
    admin, agent = setup
    p = proposal(agent)
    accepted = trust.resolve_proposal(
        admin, p["id"], action="approve ", expected_revision="1"
    )["memory"]
    restored = trust.restore_memory(
        admin, accepted["id"], revision="1", expected_revision="1"
    )["memory"]
    assert restored["revision"] == 2
    proposal(admin, "global-secret", "private global fact", None)
    assert trust.list_proposals(agent)["total"] == 1
    error(403, trust.list_activity, agent, "b")
    assert all(
        event["project_id"] == "a" for event in trust.list_activity(agent)["events"]
    )
    for evidence in (
        [{"source_type": "message", "source_id": None, "quote": None}],
        [{"source_type": "message", "source_id": "x", "quote": "  "}],
        [],
    ):
        error(
            422,
            trust.create_proposal,
            agent,
            content="x",
            project_id="a",
            evidence=evidence,
            idempotency_key="invalid",
        )


def test_preview_tracks_edited_text_without_resolving(setup):
    from sqlmodel import Session
    from gigamind.db.trust_models import MemoryProposal

    admin, agent = setup
    first = proposal(agent)
    accepted = trust.resolve_proposal(
        admin, first["id"], action="approve", expected_revision=1
    )["memory"]
    second = proposal(agent, key="preview", content="different")
    changed = trust.preview_proposal(
        admin, second["id"], content="first", expected_revision=1
    )
    assert changed["conflicts"] == []
    changed = trust.preview_proposal(
        admin, second["id"], content="different", expected_revision=1
    )
    assert [record["id"] for record in changed["conflicts"]] == [accepted["id"]]
    error(
        403,
        trust.preview_proposal,
        agent,
        second["id"],
        content="different",
        expected_revision=1,
    )
    error(
        409,
        trust.preview_proposal,
        admin,
        second["id"],
        content="different",
        expected_revision=2,
    )
    with Session(trust.engine) as session:
        stored = session.get(MemoryProposal, second["id"])
        assert stored.status == "proposed" and stored.revision == 1


def test_approval_cannot_reclassify_a_deleted_conflict(setup, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from sqlmodel import Session
    from gigamind.db.trust_models import MemoryProposal

    admin, agent = setup
    first = proposal(agent)
    memory = trust.resolve_proposal(
        admin, first["id"], action="approve", expected_revision=1
    )["memory"]
    second = proposal(agent, "second", "second")
    captured, release = Event(), Event()
    conflicts = trust.conflicts

    def pause_after_conflict_read(*args, **kwargs):
        result = conflicts(*args, **kwargs)
        captured.set()
        assert release.wait(5), "test failed to release conflict scan"
        return result

    monkeypatch.setattr(trust, "conflicts", pause_after_conflict_read)
    with ThreadPoolExecutor(1) as pool:
        approval = pool.submit(
            trust.resolve_proposal,
            admin,
            second["id"],
            action="approve",
            expected_revision=1,
            supersedes=[memory["id"]],
        )
        assert captured.wait(5)
        deleter = Actor("deleting-admin", set(), None, True)
        try:
            trust.delete_memory(deleter, memory["id"], expected_revision=1)
        finally:
            release.set()
        error(409, approval.result, timeout=10)
    assert trust.get_memory(admin, memory["id"])["memory"]["status"] == "deleted"
    error(404, trust.get_memory, agent, memory["id"])
    history = trust.get_history(admin, memory["id"])["revisions"]
    assert [r["status"] for r in history] == ["accepted", "deleted"]
    assert history[-1]["writer_id"] == "deleting-admin"
    events = [
        e for e in trust.list_activity(admin)["events"] if e["action"] == "delete"
    ]
    assert [(e["revision"], e["writer_id"]) for e in events] == [(2, "deleting-admin")]
    with Session(trust.engine) as session:
        pending = session.get(MemoryProposal, second["id"])
        assert pending.status == "proposed" and pending.revision == 1


def test_delete_rollback_keeps_source_revision_and_activity(setup, monkeypatch):
    admin, agent = setup
    p = proposal(agent)
    memory = trust.resolve_proposal(
        admin, p["id"], action="approve", expected_revision=1
    )["memory"]
    before_events = trust.list_activity(admin)["events"]

    def fail_snapshot(*args):
        raise RuntimeError("audit storage failed")

    monkeypatch.setattr(trust, "snapshot", fail_snapshot)
    with pytest.raises(RuntimeError, match="audit storage failed"):
        trust.delete_memory(admin, memory["id"], expected_revision=1)
    assert trust.get_memory(agent, memory["id"])["memory"] == memory
    assert len(trust.get_history(admin, memory["id"])["revisions"]) == 1
    assert trust.list_activity(admin)["events"] == before_events
