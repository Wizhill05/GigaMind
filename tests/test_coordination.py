import json
import pytest
from fastapi import HTTPException
from sqlmodel import create_engine
from gigamind.db.migrations import migrate
from gigamind.security import Actor
from gigamind.services import coordination, context, trust


def test_coordination_persistence_scope_and_budget(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    migrate(engine)
    monkeypatch.setattr(trust, "engine", engine)
    admin = Actor("admin", set(), None, True)
    agent = Actor("agent", {"memory:read", "memory:propose"}, {"a"})
    payload = dict(
        task_name="task",
        summary="report",
        status="working",
        project_id="a",
        verified_outcomes=["claim"],
        unresolved=[],
        next_actions=[],
        idempotency_key="one",
    )
    first = coordination.save_handoff(agent, **payload)["handoff"]
    assert first["writer_id"] == "agent" and first["record_type"] == "agent_report"
    assert coordination.save_handoff(agent, **payload)["handoff"] == first
    with pytest.raises(HTTPException) as exc:
        coordination.save_handoff(agent, **dict(payload, summary="changed"))
    assert exc.value.status_code == 409
    for project in (None, "b"):
        with pytest.raises(HTTPException):
            coordination.save_handoff(agent, **dict(payload, project_id=project))
    p = trust.create_proposal(
        admin, content="accepted", project_id="a", evidence=[], idempotency_key="p"
    )["proposal"]
    memory = trust.resolve_proposal(
        admin, p["id"], action="approve", expected_revision=1
    )["memory"]
    issue = coordination.report_memory_issue(
        agent,
        memory_id=memory["id"],
        project_id="a",
        reason="incorrect",
        idempotency_key="i",
    )["issue"]
    assert (
        coordination.list_issues(Actor("other", {"memory:read"}, {"a"}), "a")["total"]
        == 0
    )
    assert (
        coordination.resolve_issue(
            admin, issue["id"], status="resolved", expected_revision=1
        )["issue"]["revision"]
        == 2
    )
    assert trust.get_memory(agent, memory["id"])["memory"] == memory
    assert context.get_context(agent, "accepted", "a", 64)["handoff"] is None
    coordination.save_handoff(
        admin,
        **dict(
            payload, project_id="b", summary="outside scope", idempotency_key="outside"
        ),
    )
    result = context.get_context(agent, "accepted", "a", 10000)
    assert memory["content"] in str(result["memories"])
    assert "outside scope" not in json.dumps(result)
    assert result["handoff"]["id"] == first["id"]
    assert len(json.dumps(result, ensure_ascii=True).encode()) <= 10000
    with pytest.raises(HTTPException):
        coordination.save_handoff(agent, **dict(payload, writer_id="forged"))


def test_http_and_mcp(server):
    import asyncio
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = {"Authorization": "Bearer test-master-key"}
    payload = dict(
        task_name="http",
        summary="report",
        status="working",
        project_id="p",
        verified_outcomes=[],
        unresolved=[],
        next_actions=[],
        idempotency_key="http",
    )
    response = httpx.post(
        server + "/api/v1/review/handoffs",
        headers=headers,
        json=payload,
        trust_env=False,
    )
    assert response.status_code == 200
    assert (
        httpx.post(
            server + "/api/v1/review/handoffs",
            headers=headers,
            json=dict(payload, writer_id="forged"),
            trust_env=False,
        ).status_code
        == 422
    )
    assert (
        httpx.get(
            server + "/api/v1/review/handoffs/latest",
            headers=headers,
            params={"project_id": "p"},
            trust_env=False,
        ).json()["handoff"]["id"]
        == response.json()["handoff"]["id"]
    )

    async def exercise():
        async with httpx.AsyncClient(headers=headers, trust_env=False) as client:
            async with streamable_http_client(server + "/mcp", http_client=client) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "save_handoff", dict(payload, idempotency_key="mcp")
                    )
                    assert (
                        not result.isError
                        and result.structuredContent["handoff"]["writer_id"]
                    )
                    invalid = await session.call_tool(
                        "save_handoff", dict(payload, writer_id="forged")
                    )
                    assert invalid.isError

    asyncio.run(exercise())


from test_mcp_transport import server


def test_concurrent_idempotency_and_issue_scope(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    engine = create_engine(
        f"sqlite:///{tmp_path}/concurrent.db", connect_args={"timeout": 10}
    )
    migrate(engine)
    monkeypatch.setattr(trust, "engine", engine)
    admin = Actor("admin", set(), None, True)
    agent = Actor("agent", {"memory:read", "memory:propose"}, {"a"})
    payload = dict(
        task_name="task",
        summary="summary",
        status="done",
        project_id="a",
        verified_outcomes=[],
        unresolved=[],
        next_actions=[],
        idempotency_key="shared",
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: coordination.save_handoff(agent, **payload), range(4))
        )
    assert len({r["handoff"]["id"] for r in results}) == 1
    p = trust.create_proposal(
        admin, content="fact", project_id="b", evidence=[], idempotency_key="p"
    )["proposal"]
    memory = trust.resolve_proposal(
        admin, p["id"], action="approve", expected_revision=1
    )["memory"]
    with pytest.raises(HTTPException):
        coordination.report_memory_issue(
            agent,
            memory_id=memory["id"],
            reason="wrong",
            project_id="a",
            idempotency_key="i",
        )
    with pytest.raises(HTTPException):
        coordination.report_memory_issue(
            Actor("reader", {"memory:read"}, {"a"}),
            memory_id=memory["id"],
            reason="wrong",
            project_id="a",
            idempotency_key="i",
        )


def test_issue_idempotency_resolution_and_rollback(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from sqlmodel import Session, select
    from gigamind.db.trust_models import ActivityEvent
    from gigamind.db.coordination import MemoryIssue

    engine = create_engine(
        f"sqlite:///{tmp_path}/issues.db", connect_args={"timeout": 10}
    )
    migrate(engine)
    monkeypatch.setattr(trust, "engine", engine)
    admin = Actor("admin", set(), None, True)
    agent = Actor("writer", {"memory:read", "memory:propose"}, {"a"})
    proposal = trust.create_proposal(
        admin,
        content="unchanged fact",
        project_id="a",
        evidence=[],
        idempotency_key="p",
    )["proposal"]
    memory = trust.resolve_proposal(
        admin, proposal["id"], action="approve", expected_revision=1
    )["memory"]
    payload = dict(
        memory_id=memory["id"], project_id="a", reason="wrong", idempotency_key="issue"
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: coordination.report_memory_issue(agent, **payload), range(4)
            )
        )
    issue = results[0]["issue"]
    assert all(result["issue"] == issue for result in results)
    with pytest.raises(HTTPException) as mismatch:
        coordination.report_memory_issue(agent, **dict(payload, reason="different"))
    assert mismatch.value.status_code == 409
    for invalid in (
        dict(payload, reason=" "),
        dict(payload, reason=3),
        dict(payload, writer_id="forged"),
    ):
        with pytest.raises(HTTPException) as error:
            coordination.report_memory_issue(agent, **invalid)
        assert error.value.status_code == 422
    assert (
        coordination.list_issues(Actor("other", {"memory:read"}, {"a"}), "a")["total"]
        == 0
    )
    with Session(engine) as session:
        before = len(session.exec(select(ActivityEvent)).all())
    original = trust.event

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("event failure")

    monkeypatch.setattr(trust, "event", fail)
    with pytest.raises(RuntimeError, match="event failure"):
        coordination.resolve_issue(
            admin, issue["id"], status="resolved", expected_revision=1
        )
    with Session(engine) as session:
        row = session.get(MemoryIssue, issue["id"])
        assert (row.status, row.revision) == ("open", 1)
        assert len(session.exec(select(ActivityEvent)).all()) == before
    monkeypatch.setattr(trust, "event", original)

    def resolve(_):
        try:
            return coordination.resolve_issue(
                admin, issue["id"], status="resolved", expected_revision=1
            )
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(resolve, range(2)))
    assert sum(isinstance(value, dict) for value in outcomes) == 1
    assert 409 in outcomes
    assert trust.get_memory(agent, memory["id"])["memory"] == memory


def test_coordination_read_bounds(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/bounds.db")
    migrate(engine)
    monkeypatch.setattr(trust, "engine", engine)
    reader = Actor("reader", {"memory:read"}, {"a"})
    for listing in (coordination.list_handoffs, coordination.list_issues):
        for project in (None, "b"):
            with pytest.raises(HTTPException) as denied:
                listing(reader, project)
            assert denied.value.status_code == 403
        for limit, offset in ((0, 0), (101, 0), (1, -1)):
            with pytest.raises(HTTPException) as invalid:
                listing(reader, "a", limit, offset)
            assert invalid.value.status_code == 422
        with pytest.raises(HTTPException) as denied:
            listing(Actor("no-scope", set(), {"a"}), "a")
        assert denied.value.status_code == 403


def test_scoped_sdk_coordination_and_revocation(server):
    import asyncio
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    admin = {"Authorization": "Bearer test-master-key"}
    with httpx.Client(base_url=server, headers=admin, trust_env=False) as http:
        client = http.post(
            "/api/v1/admin/clients",
            json={
                "name": "coord-sdk",
                "scopes": ["memory:read", "memory:propose"],
                "project_ids": ["sdk-a"],
            },
        ).json()
        proposal = http.post(
            "/api/v1/review/proposals",
            json={
                "content": "sdk accepted preference",
                "project_id": "sdk-a",
                "evidence": [],
                "idempotency_key": "sdk-coord-proposal",
            },
        ).json()["proposal"]
        memory = http.post(
            f"/api/v1/review/proposals/{proposal['id']}/resolve",
            json={"action": "approve", "expected_revision": 1},
        ).json()["memory"]

        async def exercise():
            headers = {"Authorization": "Bearer " + client["token"]}
            async with httpx.AsyncClient(headers=headers, trust_env=False) as transport:
                async with streamable_http_client(
                    server + "/mcp", http_client=transport
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        handoff = dict(
                            task_name="sdk task",
                            summary="sdk handoff",
                            status="working",
                            project_id="sdk-a",
                            verified_outcomes=[],
                            unresolved=[],
                            next_actions=[],
                            idempotency_key="sdk-handoff",
                        )
                        result = await session.call_tool("save_handoff", handoff)
                        assert not result.isError
                        issue = await session.call_tool(
                            "report_memory_issue",
                            {
                                "memory_id": memory["id"],
                                "reason": "check",
                                "project_id": "sdk-a",
                                "idempotency_key": "sdk-issue",
                            },
                        )
                        assert (
                            not issue.isError
                            and issue.structuredContent["issue"]["memory_id"]
                            == memory["id"]
                        )
                        context_result = await session.call_tool(
                            "get_context",
                            {
                                "query": "sdk accepted preference",
                                "project_id": "sdk-a",
                                "token_budget": 10000,
                            },
                        )
                        assert not context_result.isError
                        assert (
                            context_result.structuredContent["handoff"]["id"]
                            == result.structuredContent["handoff"]["id"]
                        )
                        assert memory["content"] in str(
                            context_result.structuredContent["memories"]
                        )
                        for changes in (
                            {"project_id": "sdk-b"},
                            {"project_id": None},
                            {"writer_id": "forged"},
                        ):
                            assert (
                                await session.call_tool(
                                    "save_handoff", dict(handoff, **changes)
                                )
                            ).isError
                        assert (
                            http.post(
                                "/api/v1/admin/clients/"
                                + client["client"]["id"]
                                + "/revoke"
                            ).status_code
                            == 200
                        )
                        await session.call_tool("save_handoff", handoff)

        with pytest.raises(ExceptionGroup) as revoked:
            asyncio.run(exercise())
        assert "401 Unauthorized" in str(revoked.value.exceptions[0])


def test_http_coordination_pagination_bounds(server):
    import httpx

    headers = {"Authorization": "Bearer test-master-key"}
    with httpx.Client(base_url=server, headers=headers, trust_env=False) as http:
        for path in ("handoffs", "issues"):
            for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
                response = http.get("/api/v1/review/" + path, params=params)
                assert response.status_code == 422


def test_sdk_coordination_denies_client_without_scopes(server):
    import asyncio
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    with httpx.Client(
        base_url=server,
        headers={"Authorization": "Bearer test-master-key"},
        trust_env=False,
    ) as http:
        response = http.post(
            "/api/v1/admin/clients",
            json={"name": "no-scope", "scopes": [], "project_ids": ["a"]},
        )
        assert response.status_code == 200
        token = response.json()["token"]

    async def exercise():
        async with httpx.AsyncClient(
            headers={"Authorization": "Bearer " + token}, trust_env=False
        ) as http:
            async with streamable_http_client(server + "/mcp", http_client=http) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    requests = {
                        "save_handoff": dict(
                            task_name="task",
                            summary="report",
                            status="working",
                            project_id="a",
                            verified_outcomes=[],
                            unresolved=[],
                            next_actions=[],
                            idempotency_key="denied",
                        ),
                        "report_memory_issue": dict(
                            memory_id="hidden",
                            reason="check",
                            project_id="a",
                            idempotency_key="denied",
                        ),
                        "get_context": dict(query="task", project_id="a"),
                    }
                    for name, arguments in requests.items():
                        result = await session.call_tool(name, arguments)
                        assert result.isError
                        assert "403" in str(result.content)

    asyncio.run(exercise())
