import os
import time

import jwt
from fastapi.testclient import TestClient
from test_oauth_verifier import issuer


def test_external_binding_and_discovery(issuer, monkeypatch, tmp_path):
    keys, _, config, _ = issuer
    monkeypatch.setenv("OAUTH_ISSUER", config.issuer)
    monkeypatch.setenv("OAUTH_JWKS_URL", config.jwks_url)
    monkeypatch.setenv("OAUTH_AUDIENCE", "https://resource.example/mcp")
    monkeypatch.setenv("GIGAMIND_PUBLIC_URL", "https://resource.example")
    monkeypatch.setenv("OAUTH_ALLOW_LOOPBACK_HTTP", "true")
    monkeypatch.setenv("GIGAMIND_API_KEY", "test-master-secret")
    from gigamind.main import app
    import gigamind.main as main
    import gigamind.security as security
    import gigamind.routers.oauth as router
    from sqlmodel import SQLModel, create_engine

    engine = create_engine(
        f"sqlite:///{tmp_path / 'bindings.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    for module in (main, security, router):
        monkeypatch.setattr(module, "engine", engine)
    from gigamind.security import get_actor, require_scope
    from fastapi import HTTPException
    import pytest

    def signed(**changes):
        claims = {
            "iss": config.issuer,
            "sub": "person",
            "aud": "https://resource.example/mcp",
            "exp": int(time.time()) + 300,
            "scope": "memory:read memory:write admin",
        }
        claims.update(changes)
        return jwt.encode(claims, keys[0], algorithm="RS256", headers={"kid": "0"})

    with TestClient(app) as client:
        master = {"Authorization": "Bearer test-master-secret"}
        created = client.post(
            "/api/v1/admin/clients",
            headers=master,
            json={
                "name": "test",
                "scopes": ["memory:read"],
                "project_ids": ["projectA"],
            },
        ).json()
        local = created["token"]
        assert get_actor("Bearer " + local).scopes == {"memory:read"}
        bearer = "Bearer " + signed()
        with pytest.raises(HTTPException):
            get_actor(bearer)
        binding = client.post(
            "/api/v1/admin/oauth/bindings",
            headers=master,
            json={
                "issuer": config.issuer,
                "subject": "person",
                "client_id": created["client"]["id"],
            },
        )
        assert binding.status_code == 201
        actor = get_actor(bearer)
        assert (
            actor.scopes == {"memory:read"}
            and actor.project_ids == {"projectA"}
            and not actor.is_admin
        )
        with pytest.raises(HTTPException):
            require_scope("admin")(actor)
        assert (
            client.get(
                "/api/v1/admin/oauth/bindings", headers={"Authorization": bearer}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/v1/admin/oauth/bindings?limit=0", headers=master
            ).status_code
            == 422
        )
        assert (
            len(
                client.get(
                    "/api/v1/admin/oauth/bindings?limit=1", headers=master
                ).json()["bindings"]
            )
            == 1
        )
        for bad in [signed(aud="wrong"), signed(sub="other"), signed()[:-3] + "xyz"]:
            with pytest.raises(HTTPException):
                get_actor("Bearer " + bad)
        metadata = client.get(
            "/.well-known/oauth-protected-resource/mcp",
            headers={"Host": "evil.example"},
        ).json()
        assert metadata["resource"] == "https://resource.example/mcp"
        response = client.post("/mcp", headers={"Host": "evil.example"})
        assert response.status_code == 401
        assert (
            "https://resource.example/.well-known/oauth-protected-resource/mcp"
            in response.headers["www-authenticate"]
        )
        assert (
            client.post(
                "/api/v1/admin/oauth/bindings",
                headers=master,
                json={
                    "issuer": config.issuer,
                    "subject": "person",
                    "client_id": created["client"]["id"],
                },
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/v1/admin/oauth/bindings/" + binding.json()["id"] + "/revoke",
                headers=master,
            ).status_code
            == 200
        )
        with pytest.raises(HTTPException):
            get_actor(bearer)

        second = client.post(
            "/api/v1/admin/oauth/bindings",
            headers=master,
            json={
                "issuer": config.issuer,
                "subject": "second",
                "client_id": created["client"]["id"],
            },
        )
        assert second.status_code == 201
        second_bearer = "Bearer " + signed(sub="second")
        assert get_actor(second_bearer).id == created["client"]["id"]
        assert (
            client.post(
                "/api/v1/admin/clients/" + created["client"]["id"] + "/revoke",
                headers=master,
            ).status_code
            == 200
        )
        with pytest.raises(HTTPException):
            get_actor(second_bearer)
        with pytest.raises(HTTPException):
            get_actor("Bearer " + local)


def test_signed_token_through_sdk(issuer, tmp_path):
    """Exercise verified JWTs through the real SDK and project-scoped services."""
    import asyncio
    import socket
    import subprocess
    import sys

    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    keys, _, config, _ = issuer
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.getcwd(),
        "DB_PATH": str(tmp_path / "oauth.db"),
        "PYTHON_DOTENV_DISABLED": "1",
        "GIGAMIND_API_KEY": "sdk-test-master",
        "OAUTH_ISSUER": config.issuer,
        "OAUTH_JWKS_URL": config.jwks_url,
        "OAUTH_AUDIENCE": origin + "/mcp",
        "GIGAMIND_PUBLIC_URL": origin,
        "OAUTH_ALLOW_LOOPBACK_HTTP": "true",
    }
    with (tmp_path / "server.log").open("w+") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                f'import uvicorn; from gigamind.main import app; uvicorn.run(app, host="127.0.0.1", port={port})',
            ],
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            for _ in range(100):
                try:
                    if (
                        httpx.get(origin + "/health/ready", trust_env=False).status_code
                        == 200
                    ):
                        break
                except httpx.ConnectError:
                    pass
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                time.sleep(0.05)
            else:
                raise RuntimeError("OAuth test server did not become ready")
            with httpx.Client(
                base_url=origin,
                headers={"Authorization": "Bearer sdk-test-master"},
                trust_env=False,
            ) as admin:
                created = admin.post(
                    "/api/v1/admin/clients",
                    json={
                        "name": "oauth-reader",
                        "scopes": ["memory:read", "memory:propose"],
                        "project_ids": ["projectA"],
                    },
                )
                assert created.status_code == 200
                binding = admin.post(
                    "/api/v1/admin/oauth/bindings",
                    json={
                        "issuer": config.issuer,
                        "subject": "sdk-user",
                        "client_id": created.json()["client"]["id"],
                    },
                )
                assert binding.status_code == 201
                memories = {}
                for project in ("projectA", "projectB", None):
                    proposed = admin.post(
                        "/api/v1/review/proposals",
                        json={
                            "content": "zircon " + str(project),
                            "project_id": project,
                            "evidence": [],
                            "idempotency_key": "fixture-" + str(project),
                        },
                    )
                    assert proposed.status_code == 200, proposed.text
                    approved = admin.post(
                        "/api/v1/review/proposals/"
                        + proposed.json()["proposal"]["id"]
                        + "/resolve",
                        json={
                            "action": "approve",
                            "expected_revision": 1,
                        },
                    )
                    assert approved.status_code == 200, approved.text
                    memories[project] = approved.json()["memory"]["id"]
                token = jwt.encode(
                    {
                        "iss": config.issuer,
                        "sub": "sdk-user",
                        "aud": origin + "/mcp",
                        "exp": int(time.time()) + 300,
                        "scope": "memory:read admin",
                    },
                    keys[0],
                    algorithm="RS256",
                    headers={"kid": "0"},
                )

                async def exercise():
                    async with httpx.AsyncClient(
                        headers={"Authorization": "Bearer " + token}, trust_env=False
                    ) as client:
                        async with streamable_http_client(
                            origin + "/mcp", http_client=client
                        ) as (read, write, _):
                            async with ClientSession(read, write) as session:
                                await session.initialize()
                                found = await session.call_tool(
                                    "search_memory",
                                    {"query": "zircon", "project_id": "projectA"},
                                )
                                assert not found.isError
                                assert [
                                    item["id"]
                                    for item in found.structuredContent["results"]
                                ] == [memories["projectA"]]
                                exact = await session.call_tool(
                                    "get_memory", {"memory_id": memories["projectA"]}
                                )
                                assert (
                                    not exact.isError
                                    and exact.structuredContent["memory"]["id"]
                                    == memories["projectA"]
                                )
                                context = await session.call_tool(
                                    "get_context",
                                    {"query": "zircon", "project_id": "projectA"},
                                )
                                assert not context.isError
                                assert memories["projectB"] not in str(
                                    context.structuredContent
                                )
                                assert memories[None] not in str(
                                    context.structuredContent
                                )
                                for project in ("projectB", None):
                                    args = {"query": "zircon"}
                                    if project:
                                        args["project_id"] = project
                                    assert (
                                        await session.call_tool("search_memory", args)
                                    ).isError
                                    assert (
                                        await session.call_tool(
                                            "get_memory",
                                            {"memory_id": memories[project]},
                                        )
                                    ).isError
                                assert (
                                    await session.call_tool("get_server_status", {})
                                ).isError
                                assert (
                                    await session.call_tool(
                                        "propose_memory",
                                        {
                                            "content": "forbidden",
                                            "project_id": "projectA",
                                            "evidence": [],
                                            "idempotency_key": "forbidden",
                                        },
                                    )
                                ).isError
                                assert (
                                    admin.post(
                                        "/api/v1/admin/oauth/bindings/"
                                        + binding.json()["id"]
                                        + "/revoke"
                                    ).status_code
                                    == 200
                                )
                                response = await client.post(
                                    origin + "/mcp",
                                    json={
                                        "jsonrpc": "2.0",
                                        "id": 99,
                                        "method": "tools/list",
                                    },
                                )
                                assert response.status_code == 401
                                assert (
                                    origin + "/.well-known/oauth-protected-resource/mcp"
                                    in response.headers["www-authenticate"]
                                )

                asyncio.run(exercise())
        finally:
            process.terminate()
            process.wait(timeout=10)


def test_resource_origin_validation(monkeypatch):
    import pytest
    from gigamind.services.oauth import resource_config

    monkeypatch.setenv("OAUTH_ISSUER", "https://issuer.example")
    monkeypatch.setenv("OAUTH_JWKS_URL", "https://issuer.example/keys")
    for origin in (
        " https://resource.example",
        "https://resource.example#",
        "https://resource.example?",
        "https://res\nource.example",
    ):
        monkeypatch.setenv("GIGAMIND_PUBLIC_URL", origin)
        monkeypatch.setenv("OAUTH_AUDIENCE", origin + "/mcp")
        with pytest.raises(ValueError):
            resource_config()


def test_non_ascii_bearer_is_unauthorized(monkeypatch, tmp_path):
    import pytest
    from fastapi import HTTPException
    from gigamind.security import get_actor
    from gigamind import security
    from sqlmodel import create_engine

    engine = create_engine(f"sqlite:///{tmp_path / 'bad-bearer.db'}")
    security.ClientCredential.__table__.create(engine)
    monkeypatch.setattr(security, "engine", engine)
    for name in (
        "GIGAMIND_PUBLIC_URL",
        "OAUTH_ISSUER",
        "OAUTH_JWKS_URL",
        "OAUTH_AUDIENCE",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("GIGAMIND_API_KEY", "test-master-secret")
    with pytest.raises(HTTPException) as caught:
        get_actor("Bearer café")
    assert caught.value.status_code == 401
