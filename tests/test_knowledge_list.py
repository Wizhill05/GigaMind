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
        proposal = trust.create_proposal(
            admin, content=text, project_id=project, evidence=[], idempotency_key=key
        )["proposal"]
        return trust.resolve_proposal(
            admin, proposal["id"], action="approve", expected_revision=1
        )["memory"]

    first = create("a", "literal 100%_ value", "one")
    create("a", "literal 100xx value", "two")
    create(None, "global", "three")
    deleted = create("a", "deleted", "four")
    trust.delete_memory(admin, deleted["id"], expected_revision=1)
    result = knowledge_list.list_knowledge(reader, project_id="a", limit=1)
    assert result["total"] == 2 and len(result["memories"]) == 1
    second = knowledge_list.list_knowledge(reader, project_id="a", limit=1, offset=1)
    assert result["memories"][0]["id"] != second["memories"][0]["id"]
    assert (
        knowledge_list.list_knowledge(reader, q="%_", project_id="a")["memories"][0][
            "id"
        ]
        == first["id"]
    )
    assert knowledge_list.list_knowledge(admin)["total"] == 1
    for kwargs in ({}, {"project_id": "b"}, {"project_id": "a", "status": "deleted"}):
        with pytest.raises(HTTPException) as error:
            knowledge_list.list_knowledge(reader, **kwargs)
        assert error.value.status_code == 403


def test_authenticated_knowledge_list_filters_before_pagination(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from gigamind.main import app

    engine = create_engine(
        f"sqlite:///{tmp_path / 'knowledge-http.db'}",
        connect_args={"check_same_thread": False},
    )
    initialize_trust_tables(engine)
    monkeypatch.setattr(trust, "engine", engine)
    actor = Actor("admin", set(), None, True)

    def accept(project, content, key):
        p = trust.create_proposal(
            actor, content=content, project_id=project, evidence=[], idempotency_key=key
        )["proposal"]
        return trust.resolve_proposal(
            actor, p["id"], action="approve", expected_revision=1
        )["memory"]

    literal = accept("a", "literal %_ fact", "literal")
    newest = accept("a", "other fact", "newest")
    accept("b", "private elsewhere", "other")
    global_record = accept(None, "global fact", "global")
    removed = accept("a", "obsolete fact", "deleted")
    trust.delete_memory(actor, removed["id"], expected_revision=1)
    headers = {"Authorization": "Bearer offline-test-master-key"}
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/review/knowledge").status_code == 401
            issued = client.post(
                "/api/v1/admin/clients",
                headers=headers,
                json={
                    "name": "knowledge reader",
                    "scopes": ["memory:read"],
                    "project_ids": ["a"],
                },
            ).json()
            scoped = {"Authorization": "Bearer " + issued["token"]}

            def get(params, auth=scoped):
                return client.get(
                    "/api/v1/review/knowledge", headers=auth, params=params
                )

            for params in (
                {},
                {"project_id": "b"},
                {"project_id": "a", "status": "deleted"},
            ):
                assert get(params).status_code == 403
            page = get({"project_id": "a", "limit": 1}).json()
            assert page["total"] == 2 and [m["id"] for m in page["memories"]] == [
                newest["id"]
            ]
            assert (
                get({"project_id": "a", "offset": 1, "limit": 1}).json()["memories"][0][
                    "id"
                ]
                == literal["id"]
            )
            assert [
                m["id"] for m in get({"project_id": "a", "q": "%_"}).json()["memories"]
            ] == [literal["id"]]
            assert get({"project_id": "a", "q": "absent"}).json() == {
                "memories": [],
                "total": 0,
            }
            assert [m["id"] for m in get({}, headers).json()["memories"]] == [
                global_record["id"]
            ]
            assert (
                get({"project_id": "a", "status": "deleted"}, headers).json()["total"]
                == 1
            )
            for params in (
                {"offset": 100001},
                {"limit": 101},
                {"q": "x" * 1001},
                {"project_id": " "},
                {"status": "invalid"},
            ):
                assert get(params, headers).status_code == 422
    finally:
        engine.dispose()
