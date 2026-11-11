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
                        "get_user_profile",
                        "search_memory",
                        "get_server_status",
                        "get_context",
                        "get_memory",
                        "propose_memory",
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

        await asyncio.gather(
            call(admin, False),
            call({"Authorization": "Bearer " + created["token"]}, True),
        )

    asyncio.run(run())
