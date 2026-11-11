import asyncio
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@pytest.fixture
def server(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.getcwd(),
        "DB_PATH": str(tmp_path / "test.db"),
        "GIGAMIND_API_KEY": "test-master-key",
        "PYTHON_DOTENV_DISABLED": "1",
    }
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import gigamind.main; import gigamind.services.memory as m; import uvicorn; m.generate_embedding = lambda *a, **k: []; m.add_memory('purple aardvark'); from gigamind.services import trust; from gigamind.security import Actor; actor=Actor('fixture-admin',set(),None,True); proposal=trust.create_proposal(actor,content='purple aardvark',evidence=[],idempotency_key='fixture-approved')['proposal']; trust.resolve_proposal(actor,proposal['id'],action='approve',expected_revision=1); uvicorn.run(gigamind.main.app, host='127.0.0.1', port="
            + str(port)
            + " )",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(url + "/health/live", trust_env=False).status_code == 200:
                    break
            except httpx.ConnectError:
                time.sleep(0.05)
        else:
            raise RuntimeError("Server did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_transport(server):
    admin = {"Authorization": "Bearer test-master-key"}
    assert httpx.post(server + "/mcp", json={}, trust_env=False).status_code == 401
    assert httpx.get(server + "/health/ready", trust_env=False).json() == {
        "status": "ready"
    }
    assert (
        httpx.get(
            server + "/api/v1/memories",
            headers=admin,
            trust_env=False,
            params={"page": 0},
        ).status_code
        == 422
    )
    filtered = httpx.get(
        server + "/api/v1/memories",
        headers=admin,
        params={"q": "unmatched"},
        trust_env=False,
    ).json()
    assert filtered["memories"] == []
    created = httpx.post(
        server + "/api/v1/admin/clients",
        headers=admin,
        trust_env=False,
        json={
            "name": "reader",
            "scopes": ["memory:read", "memory:propose"],
            "project_ids": ["p"],
        },
    ).json()

    async def exercise():
        async with httpx.AsyncClient(trust_env=False, headers=admin) as client:
            async with streamable_http_client(server + "/mcp", http_client=client) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    assert {t.name for t in (await session.list_tools()).tools} == {
                        "get_identity",
                        "get_user_profile",
                        "search_memory",
                        "get_server_status",
                        "get_context",
                        "get_memory",
                        "propose_memory",
                        "save_handoff",
                        "report_memory_issue",
                    }
                    assert (
                        await session.call_tool("get_server_status", {})
                    ).structuredContent == {"status": "online"}
                    assert (
                        await session.call_tool("get_user_profile", {})
                    ).structuredContent == {"rules": []}
                    found = await session.call_tool(
                        "search_memory", {"query": "purple aardvark"}
                    )
                    assert (
                        not found.isError
                        and found.structuredContent["results"][0]["source"]
                        == "accepted_knowledge"
                    )
                    assert (
                        found.structuredContent["results"][0]["id"]
                        in found.content[0].text
                    )
                    assert (
                        await session.call_tool(
                            "search_memory", {"query": "", "limit": 101}
                        )
                    ).isError
                    assert (await session.call_tool("delete_memory", {})).isError
        async with httpx.AsyncClient(
            trust_env=False, headers={"Authorization": "Bearer " + created["token"]}
        ) as client:
            async with streamable_http_client(server + "/mcp", http_client=client) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    identity = (
                        await session.call_tool("get_identity", {})
                    ).structuredContent
                    assert identity == {
                        "id": created["client"]["id"],
                        "scopes": ["memory:propose", "memory:read"],
                        "project_ids": ["p"],
                        "is_admin": False,
                    }
                    assert (
                        await session.call_tool("get_identity", {"extra": 1})
                    ).isError
                    assert (await session.call_tool("get_server_status", {})).isError
                    proposal = await session.call_tool(
                        "propose_memory",
                        {
                            "content": "azure bicycle",
                            "project_id": "p",
                            "evidence": [
                                {
                                    "source_type": "file",
                                    "source_id": "file1",
                                    "quote": "azure bicycle",
                                }
                            ],
                            "idempotency_key": "one",
                        },
                    )
                    assert not proposal.isError
                    proposal_id = proposal.structuredContent["proposal"]["id"]
                    approved = httpx.post(
                        server + "/api/v1/review/proposals/" + proposal_id + "/resolve",
                        headers=admin,
                        trust_env=False,
                        json={"action": "approve", "expected_revision": 1},
                    )
                    assert approved.status_code == 200
                    memory_id = approved.json()["memory"]["id"]
                    found = await session.call_tool(
                        "search_memory", {"query": "bicycle", "project_id": "p"}
                    )
                    assert found.structuredContent["results"][0]["id"] == memory_id
                    assert (
                        await session.call_tool("get_memory", {"memory_id": memory_id})
                    ).structuredContent["memory"]["evidence"][0]["source_id"] == "file1"
                    assert (
                        await session.call_tool(
                            "search_memory", {"query": "bicycle", "project_id": "other"}
                        )
                    ).isError
                    assert (
                        await session.call_tool(
                            "search_memory", {"query": "absent", "project_id": "p"}
                        )
                    ).structuredContent["results"] == []
                    assert (
                        await session.call_tool("search_memory", {"query": "bicycle"})
                    ).isError
                    assert (await session.call_tool("get_user_profile", {})).isError
                    assert (
                        httpx.post(
                            server
                            + "/api/v1/admin/clients/"
                            + created["client"]["id"]
                            + "/revoke",
                            headers=admin,
                            trust_env=False,
                        ).status_code
                        == 200
                    )
                    response = await client.post(
                        server + "/mcp",
                        json={
                            "jsonrpc": "2.0",
                            "id": 99,
                            "method": "tools/call",
                            "params": {"name": "get_server_status", "arguments": {}},
                        },
                    )
                    assert response.status_code == 401

    asyncio.run(exercise())


def test_concurrent_actor_isolation(server):
    admin = {"Authorization": "Bearer test-master-key"}
    created = httpx.post(
        server + "/api/v1/admin/clients",
        headers=admin,
        trust_env=False,
        json={"name": "scoped", "scopes": ["memory:read"], "project_ids": ["p"]},
    ).json()

    async def run():
        async def call(headers, expected_error):
            async with httpx.AsyncClient(trust_env=False, headers=headers) as client:
                async with streamable_http_client(
                    server + "/mcp", http_client=client
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        for _ in range(5):
                            result = await session.call_tool(
                                "search_memory",
                                {"query": "purple", "project_id": "other"},
                            )
                            assert bool(result.isError) == expected_error
                            identity = (
                                await session.call_tool("get_identity", {})
                            ).structuredContent
                            assert identity["is_admin"] is (not expected_error)
                            if expected_error:
                                assert identity["id"] == created["client"]["id"]
                                assert identity["project_ids"] == ["p"]

        await asyncio.gather(
            call(admin, False),
            call({"Authorization": "Bearer " + created["token"]}, True),
        )

    asyncio.run(run())


def test_transport_runs_across_successive_application_lifespans(monkeypatch):
    from fastapi.testclient import TestClient
    from mcp.types import LATEST_PROTOCOL_VERSION
    from gigamind.main import app

    monkeypatch.setenv("GIGAMIND_API_KEY", "repeat-lifespan-test-key")
    headers = {
        "Authorization": "Bearer repeat-lifespan-test-key",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
    }
    for _ in range(2):
        with TestClient(app) as client:
            initialized = client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": LATEST_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "restart-test", "version": "1.0"},
                    },
                },
            )
            assert initialized.status_code == 200, initialized.text
            called = client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "get_server_status", "arguments": {}},
                },
            )
            assert called.status_code == 200, called.text
            assert called.json()["result"]["structuredContent"] == {"status": "online"}


def test_identity_uses_current_key_and_expiry_on_every_request(server, tmp_path):
    from datetime import datetime, timedelta, timezone
    from sqlmodel import Session, create_engine
    from gigamind.security import ClientCredential

    admin = {"Authorization": "Bearer test-master-key"}
    response = httpx.post(
        server + "/api/v1/admin/clients",
        headers=admin,
        trust_env=False,
        json={
            "name": "identity lifecycle",
            "scopes": ["memory:read"],
            "project_ids": ["B", "A"],
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    created = response.json()
    expected = {
        "id": created["client"]["id"],
        "scopes": ["memory:read"],
        "project_ids": ["A", "B"],
        "is_admin": False,
    }
    call = {
        "jsonrpc": "2.0",
        "id": 99,
        "method": "tools/call",
        "params": {"name": "get_identity", "arguments": {}},
    }

    async def exercise():
        async with httpx.AsyncClient(
            trust_env=False, headers={"Authorization": "Bearer " + created["token"]}
        ) as client:
            async with streamable_http_client(server + "/mcp", http_client=client) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    assert (
                        await session.call_tool("get_identity", {})
                    ).structuredContent == expected
                    rotated_response = httpx.post(
                        server + "/api/v1/admin/clients/" + expected["id"] + "/rotate",
                        headers=admin,
                        trust_env=False,
                        json={"expected_revision": created["client"]["revision"]},
                    )
                    assert rotated_response.status_code == 200, rotated_response.text
                    rotated = rotated_response.json()
                    assert (
                        await client.post(server + "/mcp", json=call)
                    ).status_code == 401
        async with httpx.AsyncClient(
            trust_env=False, headers={"Authorization": "Bearer " + rotated["token"]}
        ) as client:
            async with streamable_http_client(server + "/mcp", http_client=client) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    assert (
                        await session.call_tool("get_identity", {})
                    ).structuredContent == expected
                    # Change only the isolated server database, avoiding timing sleeps.
                    db = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
                    try:
                        with Session(db) as db_session:
                            credential = db_session.get(
                                ClientCredential, expected["id"]
                            )
                            credential.expires_at = (
                                datetime.now(timezone.utc) - timedelta(seconds=1)
                            ).isoformat()
                            db_session.commit()
                    finally:
                        db.dispose()
                    assert (
                        await client.post(server + "/mcp", json=call)
                    ).status_code == 401

    asyncio.run(exercise())


def test_authenticated_delete(server):
    admin = {"Authorization": "Bearer test-master-key"}
    with httpx.Client(base_url=server, headers=admin, trust_env=False) as client:
        created = client.post(
            "/api/v1/admin/clients",
            json={
                "name": "delete-reader",
                "scopes": ["memory:read", "memory:approve", "memory:delete"],
                "project_ids": ["p"],
            },
        ).json()
        reader = {"Authorization": "Bearer " + created["token"]}
        proposed = client.post(
            "/api/v1/review/proposals",
            json={
                "content": "sensitive lavender setting",
                "project_id": "p",
                "evidence": [],
                "idempotency_key": "delete-sdk",
            },
        ).json()["proposal"]
        memory = client.post(
            f"/api/v1/review/proposals/{proposed['id']}/resolve",
            json={"action": "approve", "expected_revision": 1},
        ).json()["memory"]
        path = f"/api/v1/review/memories/{memory['id']}"
        assert (
            client.post(
                path + "/delete", headers=reader, json={"expected_revision": 1}
            ).status_code
            == 403
        )
        for payload in (
            {"expected_revision": "1"},
            {"expected_revision": True},
            {"expected_revision": 0},
            {"expected_revision": 1, "extra": 1},
        ):
            assert client.post(path + "/delete", json=payload).status_code == 422

        async def exercise():
            async with httpx.AsyncClient(headers=reader, trust_env=False) as transport:
                async with streamable_http_client(
                    server + "/mcp", http_client=transport
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        before = await session.call_tool(
                            "get_memory", {"memory_id": memory["id"]}
                        )
                        assert (
                            before.structuredContent["memory"]["content"]
                            == memory["content"]
                        )
                        deleted = client.post(
                            path + "/delete", json={"expected_revision": 1}
                        )
                        assert deleted.status_code == 200, deleted.text
                        assert deleted.json()["memory"]["revision"] == 2
                        assert (
                            client.post(
                                path + "/delete", json={"expected_revision": 1}
                            ).status_code
                            == 409
                        )
                        exact = await session.call_tool(
                            "get_memory", {"memory_id": memory["id"]}
                        )
                        assert exact.isError and memory["content"] not in str(exact)
                        found = await session.call_tool(
                            "search_memory", {"query": "lavender", "project_id": "p"}
                        )
                        assert found.structuredContent["results"] == []
                        context = await session.call_tool(
                            "get_context", {"query": "lavender", "project_id": "p"}
                        )
                        assert context.structuredContent["memories"] == []
                        assert memory["content"] not in str(context.structuredContent)
            async with httpx.AsyncClient(headers=admin, trust_env=False) as transport:
                async with streamable_http_client(
                    server + "/mcp", http_client=transport
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        assert (
                            await session.call_tool(
                                "get_memory", {"memory_id": memory["id"]}
                            )
                        ).isError

        asyncio.run(exercise())
        assert client.get(path, headers=reader).status_code == 404
        assert client.get(path + "/history", headers=reader).status_code == 404
        assert (
            client.post(
                path + "/restore",
                headers=reader,
                json={"revision": 1, "expected_revision": 2},
            ).status_code
            == 403
        )
        history = client.get(path + "/history").json()["revisions"]
        assert [revision["status"] for revision in history] == ["accepted", "deleted"]
        assert client.get(path).json()["memory"]["content"] == memory["content"]


def test_smoke_example(server):
    admin = {"Authorization": "Bearer test-master-key"}
    with httpx.Client(base_url=server, headers=admin, trust_env=False) as client:
        created = client.post(
            "/api/v1/admin/clients",
            json={"name": "smoke", "scopes": ["memory:read"], "project_ids": ["p"]},
        ).json()
        secret_content = "cobalt bicycle source content kept private"
        proposal = client.post(
            "/api/v1/review/proposals",
            json={
                "content": secret_content,
                "project_id": "p",
                "evidence": [],
                "idempotency_key": "smoke-fixture",
            },
        )
        assert proposal.status_code == 200, proposal.text
        approved = client.post(
            "/api/v1/review/proposals/"
            + proposal.json()["proposal"]["id"]
            + "/resolve",
            json={"action": "approve", "expected_revision": 1},
        )
        assert approved.status_code == 200, approved.text

        def smoke(project, query, token=created["token"]):
            result = subprocess.run(
                [
                    sys.executable,
                    "examples/mcp_smoke.py",
                    "--url",
                    server + "/mcp",
                    "--project",
                    project,
                    "--query",
                    query,
                ],
                env={"PATH": os.environ["PATH"], "GIGAMIND_CLIENT_TOKEN": token},
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert token not in result.stdout + result.stderr
            assert secret_content not in result.stdout + result.stderr
            return result

        found = smoke("p", "bicycle")
        assert found.returncode == 0, found.stderr
        assert "Accepted matches: 1" in found.stdout
        assert "is_admin': False" in found.stdout
        empty = smoke("p", "absent")
        assert empty.returncode == 0, empty.stderr
        assert "Accepted matches: 0" in empty.stdout
        assert smoke("other", "bicycle").returncode != 0
        revoked = client.post(
            "/api/v1/admin/clients/" + created["client"]["id"] + "/revoke"
        )
        assert revoked.status_code == 200
        assert smoke("p", "bicycle").returncode != 0
