import pytest
from fastapi import HTTPException
from sqlmodel import create_engine

from gigamind.db.trust_models import initialize_trust_tables
from gigamind.security import Actor
from gigamind.services import knowledge_list, trust


def test_list_scope_pagination_and_literal_search(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/knowledge.db")
    initialize_trust_tables(engine)
    monkeypatch.setattr(trust, "engine", engine)
    admin = Actor("admin", set(), None, True)
    reader = Actor("reader", {"memory:read"}, {"a"})
    def create(project, text, key):
        proposal = trust.create_proposal(admin, content=text, project_id=project, evidence=[], idempotency_key=key)["proposal"]
        return trust.resolve_proposal(admin, proposal["id"], action="approve", expected_revision=1)["memory"]
    first = create("a", "literal 100%_ value", "one")
    create("a", "literal 100xx value", "two")
    create(None, "global", "three")
    deleted = create("a", "deleted", "four")
    trust.delete_memory(admin, deleted["id"], expected_revision=1)
    result = knowledge_list.list_knowledge(reader, project_id="a", limit=1)
    assert result["total"] == 2 and len(result["memories"]) == 1
    second = knowledge_list.list_knowledge(reader, project_id="a", limit=1, offset=1)
    assert result["memories"][0]["id"] != second["memories"][0]["id"]
    assert knowledge_list.list_knowledge(reader, q="%_", project_id="a")["memories"][0]["id"] == first["id"]
    assert knowledge_list.list_knowledge(admin)["total"] == 1
    for kwargs in ({}, {"project_id": "b"}, {"project_id": "a", "status": "deleted"}):
        with pytest.raises(HTTPException) as error:
            knowledge_list.list_knowledge(reader, **kwargs)
        assert error.value.status_code == 403
