import asyncio

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from test_mcp_transport import server  # noqa: F401


def test_inactive_memory_over_sdk_and_review(server):
    admin = {"Authorization": "Bearer test-master-key"}
    with httpx.Client(base_url=server, headers=admin, trust_env=False) as client:
        credential = client.post(
            "/api/v1/admin/clients",
            json={
                "name": "validity-reader",
                "scopes": ["memory:read"],
                "project_ids": ["p"],
            },
        ).json()
        reader = {"Authorization": "Bearer " + credential["token"]}
        proposal = client.post(
            "/api/v1/review/proposals",
            json={
                "content": "apple sdk validity",
                "project_id": "p",
                "evidence": [],
                "idempotency_key": "sdk-validity",
            },
        ).json()["proposal"]
        memory = client.post(
            f"/api/v1/review/proposals/{proposal['id']}/resolve",
            json={"action": "approve", "expected_revision": 1},
        ).json()["memory"]
        path = f"/api/v1/review/memories/{memory['id']}"
        response = client.post(
            path + "/validity",
            json={
                "expected_revision": 1,
                "valid_from": None,
                "valid_until": "2020-01-01T00:00:00Z",
            },
        )
        assert response.status_code == 200
        assert client.get(path, headers=reader).status_code == 404
        assert client.get(path + "/history", headers=reader).status_code == 404
        assert client.get(path + "/history").status_code == 200

    async def exercise(headers):
        async with httpx.AsyncClient(headers=headers, trust_env=False) as transport:
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
                    result = await session.call_tool(
                        "search_memory", {"query": "apple", "project_id": "p"}
                    )
                    assert result.structuredContent["results"] == []
                    result = await session.call_tool(
                        "get_context", {"query": "apple", "project_id": "p"}
                    )
                    assert result.structuredContent["memories"] == []

    asyncio.run(exercise(reader))
    asyncio.run(exercise(admin))
