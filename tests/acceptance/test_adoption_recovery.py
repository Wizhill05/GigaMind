import asyncio
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[2]
MASTER = "acceptance-local-master"
OLD = "cobalt otter original secret"
NEW = "cobalt otter corrected secret"


def environment(db):
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(ROOT),
        "PYTHON_DOTENV_DISABLED": "1",
        "DB_PATH": str(db),
        "GIGAMIND_API_KEY": MASTER,
    }


@contextmanager
def server(db, logs):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.listen(128)
        sock.set_inheritable(True)
        with server_on_socket(db, logs, sock, port) as url:
            yield url


@contextmanager
def server_on_socket(db, logs, sock, port):
    url = f"http://127.0.0.1:{port}"
    with logs.open("ab") as output:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "gigamind.main:app",
                "--fd",
                str(sock.fileno()),
            ],
            cwd=ROOT,
            pass_fds=(sock.fileno(),),
            env=environment(db),
            stdout=output,
            stderr=output,
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError("server exited before readiness")
                try:
                    if (
                        httpx.get(
                            url + "/health/ready", trust_env=False, timeout=1
                        ).status_code
                        == 200
                    ):
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                raise TimeoutError("server readiness deadline")
            yield url
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def ok(response):
    assert response.status_code == 200, (response.status_code, response.text)
    return response.json()


@pytest.fixture
def isolated_dir():
    with tempfile.TemporaryDirectory(prefix="gigamind-acceptance-") as directory:
        yield Path(directory)


def test_adoption_recovery(isolated_dir, monkeypatch):
    tmp_path = isolated_dir
    monkeypatch.setenv("DATABASE_URL", "postgresql://invalid.example/hostile")
    monkeypatch.setenv("GEMINI_API_KEY", "hostile-provider-key")
    assert "DATABASE_URL" not in environment(tmp_path / "source.db")
    assert "GEMINI_API_KEY" not in environment(tmp_path / "source.db")
    db, snapshot, restored, logs = (
        tmp_path / x for x in ("source.db", "snapshot.db", "restored.db", "server.log")
    )
    secrets = [
        MASTER,
        OLD,
        NEW,
        "cobalt otter hidden other",
        "cobalt otter hidden global",
    ]
    with server(db, logs) as url:
        with httpx.Client(
            base_url=url,
            headers={"Authorization": "Bearer " + MASTER},
            trust_env=False,
            timeout=10,
        ) as admin:

            def create(name):
                return ok(
                    admin.post(
                        "/api/v1/admin/clients",
                        json={
                            "name": name,
                            "scopes": ["memory:read", "memory:propose"],
                            "project_ids": ["a"],
                        },
                    )
                )

            a, b = create("client-a"), create("client-b")
            assert a["client"]["id"] != b["client"]["id"] and a["token"] != b["token"]
            secrets.extend([a["token"], b["token"]])

            def approve(proposal, supersedes=()):
                return ok(
                    admin.post(
                        "/api/v1/review/proposals/" + proposal + "/resolve",
                        json={
                            "action": "approve",
                            "expected_revision": 1,
                            "supersedes": list(supersedes),
                        },
                    )
                )["memory"]

            def other(project, key):
                p = ok(
                    admin.post(
                        "/api/v1/review/proposals",
                        json={
                            "content": "cobalt otter hidden " + key,
                            "project_id": project,
                            "evidence": [],
                            "idempotency_key": key,
                        },
                    )
                )["proposal"]
                return approve(p["id"])

            hidden = [other("b", "other"), other(None, "global")]
            job = ok(
                admin.post(
                    "/api/v1/jobs",
                    json={
                        "kind": "index_file",
                        "payload": {"key": "unprocessed.txt"},
                        "idempotency_key": "queued",
                    },
                )
            )
            assert job["state"] == "queued"

            async def adoption():
                async with httpx.AsyncClient(
                    headers={"Authorization": "Bearer " + a["token"]},
                    trust_env=False,
                    timeout=10,
                ) as transport:
                    async with streamable_http_client(
                        url + "/mcp", http_client=transport
                    ) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()

                            async def propose(content, key):
                                result = await session.call_tool(
                                    "propose_memory",
                                    {
                                        "content": content,
                                        "subject": "otter",
                                        "project_id": "a",
                                        "evidence": [
                                            {
                                                "source_type": "doc",
                                                "source_id": "local-evidence",
                                                "quote": content,
                                            }
                                        ],
                                        "idempotency_key": key,
                                    },
                                )
                                assert not result.isError, result
                                return result.structuredContent["proposal"]["id"]

                            first = approve(await propose(OLD, "first"))
                            handoff = await session.call_tool(
                                "save_handoff",
                                {
                                    "task_name": "adoption",
                                    "summary": "reported handoff",
                                    "status": "working",
                                    "project_id": "a",
                                    "verified_outcomes": [],
                                    "unresolved": [],
                                    "next_actions": [],
                                    "idempotency_key": "handoff",
                                },
                            )
                            assert not handoff.isError, handoff
                            replacement = approve(
                                await propose(NEW, "second"), [first["id"]]
                            )
                            issue = await session.call_tool(
                                "report_memory_issue",
                                {
                                    "memory_id": replacement["id"],
                                    "reason": "review requested",
                                    "project_id": "a",
                                    "idempotency_key": "issue",
                                },
                            )
                            assert not issue.isError, issue
                            rotated = ok(
                                admin.post(
                                    "/api/v1/admin/clients/"
                                    + a["client"]["id"]
                                    + "/rotate",
                                    json={"expected_revision": a["client"]["revision"]},
                                )
                            )
                            secrets.append(rotated["token"])
                            assert (
                                await transport.post(url + "/mcp", json={})
                            ).status_code == 401
                            assert ok(
                                admin.post(
                                    "/api/v1/admin/clients/"
                                    + a["client"]["id"]
                                    + "/revoke"
                                )
                            )
                            return (
                                first,
                                replacement,
                                handoff.structuredContent["handoff"]["id"],
                                rotated["token"],
                            )

            first, current, handoff_id, rotated_token = asyncio.run(
                asyncio.wait_for(adoption(), 30)
            )

    async def verify(url):
        with httpx.Client(
            base_url=url,
            headers={"Authorization": "Bearer " + MASTER},
            trust_env=False,
            timeout=10,
        ) as admin:
            assert ok(admin.get("/api/v1/jobs/" + job["id"]))["state"] == "queued"
            assert ok(admin.get("/api/v1/review/memories/" + first["id"] + "/history"))
            assert (
                ok(admin.get("/api/v1/review/memories/" + first["id"]))["memory"][
                    "status"
                ]
                == "superseded"
            )
            assert (
                ok(admin.get("/api/v1/review/memories/" + current["id"]))["memory"][
                    "revision"
                ]
                == 1
            )
            assert ok(admin.get("/api/v1/review/proposals"))["proposals"]
            assert ok(admin.get("/api/v1/review/issues", params={"project_id": "a"}))[
                "issues"
            ]
            for token in (a["token"], rotated_token):
                assert (
                    admin.get(
                        "/api/v1/review/memories/" + current["id"],
                        headers={"Authorization": "Bearer " + token},
                    ).status_code
                    == 401
                )
        async with httpx.AsyncClient(
            headers={"Authorization": "Bearer " + b["token"]},
            trust_env=False,
            timeout=10,
        ) as transport:
            async with streamable_http_client(url + "/mcp", http_client=transport) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    assert (
                        await session.call_tool("get_identity", {})
                    ).structuredContent["id"] == b["client"]["id"]
                    exact = await session.call_tool(
                        "get_memory", {"memory_id": current["id"]}
                    )
                    assert (
                        not exact.isError
                        and exact.structuredContent["memory"]["content"] == NEW
                    )
                    context = await session.call_tool(
                        "get_context",
                        {
                            "query": "cobalt otter",
                            "project_id": "a",
                            "token_budget": 10000,
                        },
                    )
                    assert (
                        not context.isError
                        and context.structuredContent["handoff"]["id"] == handoff_id
                    )
                    assert NEW in str(context.structuredContent) and OLD not in str(
                        context.structuredContent
                    )
                    for item in hidden:
                        assert (
                            await session.call_tool(
                                "get_memory", {"memory_id": item["id"]}
                            )
                        ).isError
                    assert (
                        await session.call_tool(
                            "get_context", {"query": "cobalt", "project_id": "b"}
                        )
                    ).isError

    with server(db, logs) as url:
        asyncio.run(asyncio.wait_for(verify(url), 30))
    env = environment(db)

    def cli(*args):
        subprocess.run(
            [sys.executable, "-m", "gigamind.cli.backup", *map(str, args)],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            timeout=30,
        )

    cli("backup", "--db", db, "--output", snapshot)
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    cli("restore", "--db", snapshot, "--output", restored, "--expected-sha256", digest)
    with server(restored, logs) as url:
        asyncio.run(asyncio.wait_for(verify(url), 30))
    captured = logs.read_text()
    for secret in secrets:
        assert secret not in captured
