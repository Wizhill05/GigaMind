import pytest
from fastapi import HTTPException
from sqlmodel import Session, create_engine
from gigamind.db.trust_models import ActivityEvent, initialize_trust_tables
from gigamind.security import Actor
from gigamind.services import trust


def test_scoped_count_and_stable_newest_pagination(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/activity.db")
    initialize_trust_tables(engine)
    monkeypatch.setattr(trust, "engine", engine)
    with Session(engine) as session:
        for id, project, created in [("a", "a", "1"), ("b", "a", "2"), ("c", "a", "2"), ("d", "b", "3"), ("e", None, "4")]:
            session.add(ActivityEvent(id=id, project_id=project, writer_id="writer", action="proposed", target_id=id, created_at=created, updated_at=created))
        session.commit()
    reader = Actor("reader", {"memory:read"}, {"a"})
    admin = Actor("admin", set(), None, True)
    first = trust.list_activity(reader, limit=2)
    second = trust.list_activity(reader, limit=2, offset=2)
    assert first["total"] == second["total"] == 3
    assert [e["id"] for e in first["events"] + second["events"]] == ["c", "b", "a"]
    assert trust.list_activity(admin)["total"] == 5
    assert trust.list_activity(admin, "b")["total"] == 1
    with pytest.raises(HTTPException) as exc:
        trust.list_activity(reader, "b")
    assert exc.value.status_code == 403
    assert all(e["project_id"] == "a" for e in first["events"] + second["events"])
    with pytest.raises(HTTPException):
        trust.list_activity(Actor("denied", set(), {"a"}))
