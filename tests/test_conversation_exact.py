import json

from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from gigamind import main, security
from gigamind.db.database import ConversationItem
from gigamind.db.migrations import migrate
from gigamind.services import memory


def test_exact_conversation_is_admin_only_and_reflects_current_source(
    tmp_path, monkeypatch
):
    engine = create_engine(
        f"sqlite:///{tmp_path}/exact.db", connect_args={"check_same_thread": False}
    )
    migrate(engine)
    monkeypatch.setattr(memory, "engine", engine)
    monkeypatch.setattr(security, "engine", engine)
    messages = [
        {
            "role": "tool",
            "content": "Source output",
            "id": "message-1",
            "created_at": 123,
        }
    ]
    with Session(engine) as session:
        session.add(
            ConversationItem(
                id="source",
                platform="generic",
                title="Source",
                summary="Report",
                messages_json=json.dumps(messages),
                source_agent="user",
                created_at="now",
            )
        )
        session.commit()
    _, token = security.create_client("reader", ["memory:read"], ["p"])
    admin = {"Authorization": "Bearer offline-test-master-key"}
    with TestClient(main.app) as client:
        assert client.get("/api/v1/conversations/source").status_code == 401
        assert (
            client.get(
                "/api/v1/conversations/source",
                headers={"Authorization": "Bearer " + token},
            ).status_code
            == 403
        )
        response = client.get("/api/v1/conversations/source", headers=admin)
        assert response.status_code == 200
        assert response.json()["conversation"]["messages"] == messages
        assert response.json()["conversation"]["is_vectorized"] is False
        with Session(engine) as session:
            row = session.get(ConversationItem, "source")
            row.embedding_json = "[1, 0, 0]"
            session.add(row)
            session.commit()
        assert (
            client.get("/api/v1/conversations/source", headers=admin).json()[
                "conversation"
            ]["is_vectorized"]
            is False
        )
        assert client.get("/api/v1/conversations/source", headers=admin).json()["conversation"]["index_status"] == "legacy"
        assert (
            client.delete("/api/v1/conversations/source", headers=admin).status_code
            == 200
        )
        assert (
            client.get("/api/v1/conversations/source", headers=admin).status_code == 404
        )
    engine.dispose()
