import json

import pytest
from fastapi import HTTPException
from sqlmodel import create_engine

from gigamind.db.trust_models import initialize_trust_tables
from gigamind.security import Actor
from gigamind.services import context, trust


def test_scoped_accepted_search_and_budget(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/db")
    initialize_trust_tables(engine)
    monkeypatch.setattr(trust, "engine", engine)
    admin = Actor("admin", set(), None, True)
    agent = Actor("agent", {"memory:read"}, {"a"})

    def create(project, key, content, action="approve", subject=None):
        p = trust.create_proposal(
            admin,
            content=content,
            project_id=project,
            subject=subject,
            evidence=[{"source_type": "file", "source_id": key, "quote": "🐈" * 200}],
            idempotency_key=key,
        )["proposal"]
        if action:
            return trust.resolve_proposal(
                admin, p["id"], action=action, expected_revision=1
            )
        return p

    old = create("a", "old", "purple old", subject="topic")["memory"]
    p = trust.create_proposal(
        admin,
        content="purple new",
        project_id="a",
        subject="topic",
        evidence=[{"source_type": "file", "source_id": "new", "quote": "🐈" * 200}],
        idempotency_key="new",
    )["proposal"]
    new = trust.resolve_proposal(
        admin, p["id"], action="approve", expected_revision=1, supersedes=[old["id"]]
    )["memory"]
    create("a", "pending", "purple pending", action=None)
    create("a", "rejected", "purple rejected", action="reject")
    create("b", "other", "purple other")
    create(None, "global", "purple global")
    rows = context.search_accepted(agent, "purple", "a")
    assert [r["id"] for r in rows] == [new["id"]]
    assert rows[0]["evidence"][0]["source_id"] == "new"
    assert context.search_accepted(agent, "unmatched", "a") == []
    for project in (None, "b"):
        with pytest.raises(HTTPException) as exc:
            context.search_accepted(agent, "purple", project)
        assert exc.value.status_code == 403
    for budget in (64, 512, 10000):
        result = context.get_context(agent, "purple", "a", budget)
        assert len(json.dumps(result, ensure_ascii=True).encode()) <= budget
    assert context.get_memory(agent, new["id"])["memory"]["status"] == "accepted"


def test_context_prioritizes_scoped_preferences_for_unrelated_tasks(
    tmp_path, monkeypatch
):
    engine = create_engine(f"sqlite:///{tmp_path}/rules.db")
    initialize_trust_tables(engine)
    monkeypatch.setattr(trust, "engine", engine)
    admin = Actor("admin", set(), None, True)
    agent = Actor("agent", {"memory:read"}, {"a"})
    for project in ("a", "b", None):
        p = trust.create_proposal(
            admin,
            content="Use Python",
            project_id=project,
            kind="preference",
            evidence=[],
            idempotency_key=str(project),
        )["proposal"]
        trust.resolve_proposal(admin, p["id"], action="approve", expected_revision=1)
    result = context.get_context(agent, "build a billing application", "a", 4096)
    assert len(result["rules"]) == 1
    assert result["rules"][0]["project_id"] == "a"
    assert result["memories"] == []
    assert context.search_accepted(agent, "what do I", "a") == []


def test_unauthorized_empty_search_and_admin_global_default(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path}/global.db')
    initialize_trust_tables(engine)
    monkeypatch.setattr(trust, 'engine', engine)
    admin = Actor('admin', set(), None, True)
    reader = Actor('reader', {'memory:read'}, {'a'})
    for project in ('a', None):
        p = trust.create_proposal(admin, content='python chosen', project_id=project, evidence=[], idempotency_key=str(project))['proposal']
        trust.resolve_proposal(admin, p['id'], action='approve', expected_revision=1)
    assert [row['project_id'] for row in context.search_accepted(admin, 'python')] == [None]
    with pytest.raises(HTTPException) as denied:
        context.search_accepted(reader, 'what do I', 'b')
    assert denied.value.status_code == 403
