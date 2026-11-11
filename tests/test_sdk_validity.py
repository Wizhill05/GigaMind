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


def test_validity_sdk_scope_boundaries_and_budget(server):
    import json
    from datetime import datetime, timedelta, timezone

    instant = datetime.now(timezone.utc)
    before = (instant - timedelta(days=1)).isoformat()
    after = (instant + timedelta(days=1)).isoformat()
    admin = {"Authorization": "Bearer test-master-key"}
    with httpx.Client(base_url=server, headers=admin, trust_env=False) as http:

        def create(project, name, kind="fact", start=None, end=None):
            p = http.post(
                "/api/v1/review/proposals",
                json={
                    "content": "matrix apple " + name,
                    "kind": kind,
                    "project_id": project,
                    "evidence": [],
                    "idempotency_key": name,
                },
            )
            assert p.status_code == 200
            accepted = http.post(
                f"/api/v1/review/proposals/{p.json()['proposal']['id']}/resolve",
                json={"action": "approve", "expected_revision": 1},
            )
            assert accepted.status_code == 200
            record = accepted.json()["memory"]
            if start is not None or end is not None:
                changed = http.post(
                    f"/api/v1/review/memories/{record['id']}/validity",
                    json={
                        "expected_revision": 1,
                        "valid_from": start,
                        "valid_until": end,
                    },
                )
                assert changed.status_code == 200
                record = changed.json()["memory"]
            return record

        active = create("p", "active")
        rule = create("p", "rule", "preference", before, after)
        expired = create("p", "expired", end=before)
        future = create("p", "future", "preference", after)
        other = create("q", "other")
        global_record = create(None, "global")
        actors = {}
        for name, scopes in [
            ("reader", ["memory:read"]),
            ("unscoped", []),
            ("writer", ["memory:read", "memory:write", "memory:approve"]),
        ]:
            response = http.post(
                "/api/v1/admin/clients",
                json={"name": name, "scopes": scopes, "project_ids": ["p"]},
            )
            assert response.status_code == 200
            actors[name] = {"Authorization": "Bearer " + response.json()["token"]}
        for headers in actors.values():
            for record in (active, other, global_record):
                result = http.post(
                    f"/api/v1/review/memories/{record['id']}/validity",
                    headers=headers,
                    json={
                        "expected_revision": record["revision"],
                        "valid_from": None,
                        "valid_until": None,
                    },
                )
                assert result.status_code == 403
        assert (
            http.get(
                f"/api/v1/review/memories/{active['id']}", headers={"Authorization": ""}
            ).status_code
            == 401
        )
        for record in (other, global_record):
            assert (
                http.get(
                    f"/api/v1/review/memories/{record['id']}", headers=actors["reader"]
                ).status_code
                == 403
            )
        assert (
            http.get(
                f"/api/v1/review/memories/{active['id']}", headers=actors["unscoped"]
            ).status_code
            == 403
        )

    async def exercise():
        for name in ("reader", "unscoped"):
            async with httpx.AsyncClient(
                headers=actors[name], trust_env=False
            ) as transport:
                async with streamable_http_client(
                    server + "/mcp", http_client=transport
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(
                            "get_context",
                            {
                                "query": "matrix apple",
                                "project_id": "p",
                                "token_budget": 4096,
                            },
                        )
                        if name == "unscoped":
                            assert result.isError
                            continue
                        assert not result.isError
                        payload = result.structuredContent
                        assert [item["id"] for item in payload["rules"]] == [rule["id"]]
                        assert [item["id"] for item in payload["memories"]] == [
                            active["id"]
                        ]
                        assert (
                            len(json.dumps(payload, ensure_ascii=True).encode()) <= 4096
                        )
                        for budget in (64, 512):
                            bounded = await session.call_tool(
                                "get_context",
                                {
                                    "query": "matrix apple",
                                    "project_id": "p",
                                    "token_budget": budget,
                                },
                            )
                            assert not bounded.isError
                            assert (
                                len(
                                    json.dumps(
                                        bounded.structuredContent, ensure_ascii=True
                                    ).encode()
                                )
                                <= budget
                            )
                        for record in (expired, future, other, global_record):
                            assert (
                                await session.call_tool(
                                    "get_memory", {"memory_id": record["id"]}
                                )
                            ).isError
                        assert not (
                            await session.call_tool(
                                "get_memory", {"memory_id": rule["id"]}
                            )
                        ).isError
                        for project in (None, "q"):
                            assert (
                                await session.call_tool(
                                    "get_context",
                                    {"query": "matrix apple", "project_id": project},
                                )
                            ).isError
                        assert (
                            await session.call_tool(
                                "get_context",
                                {
                                    "query": "matrix apple",
                                    "project_id": "p",
                                    "as_of": "2024-01-01T00:00:00Z",
                                },
                            )
                        ).isError

    asyncio.run(exercise())
