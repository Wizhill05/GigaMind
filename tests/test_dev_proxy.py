"""Exercise advertised dashboard links through an owned Vite HTTP server."""

import asyncio
import os
import subprocess
import time
from contextlib import contextmanager

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from acceptance.test_adoption_recovery import MASTER, ROOT, server


@contextmanager
def frontend(backend, directory):
    logs = directory / "vite.log"
    code = """
import { createServer } from 'vite';
const server = await createServer({
  server: { host: '127.0.0.1', port: 0, strictPort: true },
});
await server.listen();
console.log('GIGAMIND_PROXY_READY ' + server.httpServer.address().port);
"""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "GIGAMIND_DEV_API_ORIGIN": backend,
        "GIGAMIND_DEMO_ENV_DIR": str(directory),
    }
    with logs.open("w") as output:
        proc = subprocess.Popen(
            ["node", "--input-type=module", "-e", code],
            cwd=ROOT / "frontend",
            env=env,
            stdout=output,
            stderr=output,
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                assert proc.poll() is None, "Owned Vite server exited before readiness"
                for line in logs.read_text().splitlines():
                    if line.startswith("GIGAMIND_PROXY_READY "):
                        port = int(line.removeprefix("GIGAMIND_PROXY_READY "))
                        assert 0 < port < 65536
                        yield f"http://127.0.0.1:{port}"
                        return
                time.sleep(0.05)
            raise TimeoutError("Owned Vite server readiness deadline")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def test_advertised_dev_endpoints_reach_backend(tmp_path):
    async def identity(url):
        async with httpx.AsyncClient(
            headers={"Authorization": "Bearer " + MASTER}, trust_env=False, timeout=10
        ) as transport:
            async with streamable_http_client(url + "/mcp", http_client=transport) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("get_identity", {})
                    assert not result.isError
                    assert result.structuredContent["id"] == "master"

    with server(tmp_path / "backend.db", tmp_path / "backend.log") as backend:
        with frontend(backend, tmp_path) as url:
            with httpx.Client(base_url=url, trust_env=False, timeout=10) as client:
                page = client.get("/")
                assert page.status_code == 200 and 'id="root"' in page.text
                for source in ("/src/main.tsx", "/src/App.tsx", "/src/index.css"):
                    transformed = client.get(source)
                    assert transformed.status_code == 200, source
                    if source.endswith(".tsx"):
                        assert "javascript" in transformed.headers["content-type"]
                assert client.get("/health/ready").status_code == 200
                assert client.get("/api/v1/stats").status_code == 401
                response = client.get(
                    "/api/v1/stats", headers={"Authorization": "Bearer " + MASTER}
                )
                assert response.status_code == 200
                document = client.get("/openapi.json")
                assert document.status_code == 200
                assert "/api/v1/stats" in document.json()["paths"]
                response = client.post("/mcp", json={})
                assert response.status_code == 401
                assert "text/html" not in response.headers.get("content-type", "")
            asyncio.run(asyncio.wait_for(identity(url), 20))
