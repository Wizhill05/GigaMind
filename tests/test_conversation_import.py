import json
import os
import subprocess
import sys

import pytest
from sqlmodel import Session, select, create_engine
from gigamind.db.database import ConversationItem, MemoryItem, ProfileItem
from gigamind.db import migrations
from gigamind.db.trust_models import AcceptedKnowledge
from gigamind.services import memory


@pytest.fixture(autouse=True)
def database(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'imports.db'}",
        connect_args={"check_same_thread": False},
    )
    migrations.migrate(engine)
    monkeypatch.setattr(memory, "engine", engine)
    monkeypatch.setattr(
        memory,
        "generate_embedding",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("provider called")),
    )
    yield engine
    engine.dispose()


def branch():
    def node(parent, role, content):
        return {
            "parent": parent,
            "message": {
                "author": {"role": role},
                "content": {"parts": [content]},
                "create_time": 123,
            },
        }

    return {
        "id": "source",
        "current_node": "b",
        "mapping": {
            "other": node("root", "assistant", "wrong"),
            "b": node("a", "assistant", "late"),
            "root": node(None, "system", "start"),
            "a": node("root", "user", "prefer tea"),
        },
    }


def rows(engine):
    with Session(engine) as session:
        return session.exec(select(ConversationItem)).all()


def test_branch_and_atomic_validation(database):
    data = branch()
    assert memory.import_conversations_data([data])["ingested"] == 1
    messages = json.loads(rows(database)[0].messages_json)
    assert [(m["id"], m["role"], m["content"], m["created_at"]) for m in messages] == [
        ("root", "system", "start", 123),
        ("a", "user", "prefer tea", 123),
        ("b", "assistant", "late", 123),
    ]
    assert rows(database)[0].embedding_json == "[]"
    for mutate in ("ambiguous", "cycle", "missing"):
        bad = branch()
        if mutate == "ambiguous":
            del bad["current_node"]
        elif mutate == "cycle":
            bad["mapping"]["a"]["parent"] = "b"
        else:
            bad["mapping"]["a"]["parent"] = "absent"
        with pytest.raises(ValueError):
            memory.import_conversations_data(
                [{"messages": [{"role": "user", "content": "new"}]}, bad]
            )
        assert len(rows(database)) == 1


def test_versions_roles_and_full_content(database):
    data = {
        "id": "same-prefix-123456789",
        "messages": [
            {"role": "tool", "content": [{"text": "tool output"}]},
            {"role": "developer", "content": "x" * 50000 + "late"},
        ],
    }
    assert memory.import_conversations_data(data)["ingested"] == 1
    assert memory.import_conversations_data(data)["skipped"] == 1
    other = dict(data, id="same-prefix-123456780")
    assert memory.import_conversations_data(other)["ingested"] == 1
    changed = dict(data, messages=[{"role": "human", "content": "changed"}])
    assert memory.import_conversations_data(changed)["ingested"] == 1
    no_id = {"chat_messages": [{"sender": "mystery", "content": [{"text": "hello"}]}]}
    assert memory.import_conversations_data(no_id)["ingested"] == 1
    assert memory.import_conversations_data(no_id)["skipped"] == 1
    assert json.loads(rows(database)[0].messages_json)[1]["content"].endswith("late")
    with Session(database) as session:
        assert not session.exec(select(AcceptedKnowledge)).all()
        assert not session.exec(select(MemoryItem)).all()
        assert not session.exec(select(ProfileItem)).all()


def test_cli(tmp_path):
    path = tmp_path / "export.json"
    path.write_text(json.dumps([branch()]))
    env = dict(
        os.environ,
        DB_PATH=str(tmp_path / "cli.db"),
        DATABASE_URL="",
        PYTHON_DOTENV_DISABLED="1",
    )
    cmd = [sys.executable, "-m", "gigamind.cli.importer", "--chatgpt", str(path)]
    first = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert "Imported 1" in first.stdout and "Indexing pending" in first.stdout
    second = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert second.returncode == 0 and "1 duplicate" in second.stdout
    assert (
        subprocess.run(
            cmd[:-1] + [str(tmp_path / "missing")], env=env, capture_output=True
        ).returncode
        != 0
    )


@pytest.mark.parametrize(
    "data",
    [
        {"messages": [{"role": [], "content": "bad role"}]},
        {"mapping": {"root": {"parent": {}, "message": None}}},
        {
            "messages": [{"role": "user", "content": "body"}],
            "create_time": float("nan"),
        },
        {"messages": [{"role": "user", "content": "body"}], "created_at": "nonsense"},
        {"messages": [{"role": "user", "content": "body"}], "platform": "x" * 513},
    ],
)
def test_invalid_import_cannot_partially_persist(database, data):
    valid = {"messages": [{"role": "user", "content": "valid source"}]}
    with pytest.raises(ValueError):
        memory.import_conversations_data([valid, data])
    assert rows(database) == []


def test_numeric_creation_time_and_unknown_creation_receipt(database):
    data = {
        "messages": [{"role": "user", "content": "timestamped"}],
        "create_time": 1700000000,
    }
    assert memory.import_conversations_data(data)["ingested"] == 1
    assert rows(database)[0].created_at == "2023-11-14T22:13:20+00:00"
    assert memory.import_conversations_data(data)["skipped"] == 1
    missing = {"messages": [{"role": "user", "content": "unknown original time"}]}
    assert memory.import_conversations_data(missing)["ingested"] == 1
    assert memory.import_conversations_data(missing)["skipped"] == 1
    assert all(row.created_at for row in rows(database))


def test_concurrent_repeat_import_is_idempotent(database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)

    def run(_):
        barrier.wait(timeout=5)
        return memory.import_conversations_data(branch())

    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(run, range(2)))
    assert sum(r["ingested"] for r in results) == 1
    assert sum(r["skipped"] for r in results) == 1
    assert len(rows(database)) == 1


def test_import_upload_boundary(database, monkeypatch):
    from fastapi.testclient import TestClient
    from gigamind.main import app
    from gigamind.services import conversation_import

    monkeypatch.setenv("GIGAMIND_API_KEY", "import-http-test-key")
    headers = {"Authorization": "Bearer import-http-test-key"}
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/import_file",
            headers=headers,
            files={"file": ("export.json", json.dumps([branch()]), "application/json")},
        )
        assert response.status_code == 200, response.text
        assert response.json()["ingested"] == response.json()["pending_indexing"] == 1
        invalid = {"messages": [{"role": [], "content": "untrusted-secret-content"}]}
        response = client.post(
            "/api/v1/conversations/import_file",
            headers=headers,
            files={"file": ("invalid.json", json.dumps(invalid), "application/json")},
        )
        assert (
            response.status_code == 400
            and "untrusted-secret-content" not in response.text
        )
        monkeypatch.setattr(conversation_import, "MAX_BYTES", 8)
        response = client.post(
            "/api/v1/conversations/import_file",
            headers=headers,
            files={"file": ("large.json", "x" * 9, "application/json")},
        )
        assert response.status_code == 413
    assert len(rows(database)) == 1
