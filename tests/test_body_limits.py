import asyncio

import httpx
import pytest

from gigamind.middleware.body_limits import (
    BodyLimitMiddleware,
    DEFAULT_LIMIT,
    PATH_LIMITS,
)


async def check_http_boundary_replays_and_rejects():
    seen = []

    async def app(scope, receive, send):
        data = b""
        while True:
            msg = await receive()
            data += msg.get("body", b"")
            if not msg.get("more_body"):
                break
        seen.append(data)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": data})

    limited = BodyLimitMiddleware(app, default_limit=4, path_limits={})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=limited), base_url="http://test"
    ) as client:
        assert (await client.post("/", content=b"abcd")).content == b"abcd"
        assert (await client.post("/", content=b"abcde")).status_code == 413

        async def chunks():
            yield b"abc"
            yield b"de"

        assert (await client.post("/", content=chunks())).status_code == 413
    assert seen == [b"abcd"]


async def check_headers_disconnect_and_large_chunk():
    calls = []

    async def app(scope, receive, send):
        calls.append(True)

    limited = BodyLimitMiddleware(app, default_limit=4, path_limits={})

    async def run(headers, messages):
        output = []

        async def receive():
            return messages.pop(0)

        async def send(message):
            output.append(message)

        await limited({"type": "http", "path": "/", "headers": headers}, receive, send)
        return output

    assert (await run([(b"content-length", b"5")], []))[0]["status"] == 413
    for headers in [
        [(b"content-length", b"-1")],
        [(b"content-length", b"1"), (b"content-length", b"1")],
        [(b"content-length", b"1, 1")],
    ]:
        assert (await run(headers, []))[0]["status"] == 400
    assert (await run([], [{"type": "http.request", "body": b"x" * 1000000}]))[0][
        "status"
    ] == 413
    assert await run([], [{"type": "http.disconnect"}]) == []
    assert not calls


def test_exact_path_limits_and_config():
    assert all(value > DEFAULT_LIMIT for value in PATH_LIMITS.values())
    assert "/api/v1/files/upload/anything" not in PATH_LIMITS
    with pytest.raises(ValueError):
        BodyLimitMiddleware(None, default_limit=0)


def test_http_boundary_replays_and_rejects():
    asyncio.run(check_http_boundary_replays_and_rejects())


def test_headers_disconnect_and_large_chunk():
    asyncio.run(check_headers_disconnect_and_large_chunk())


def test_cleanup_and_disconnect_after_replay(monkeypatch):
    import gigamind.middleware.body_limits as limits

    files = []
    original = limits.SpooledTemporaryFile

    def make_file(*args, **kwargs):
        file = original(*args, **kwargs)
        files.append(file)
        return file

    monkeypatch.setattr(limits, "SpooledTemporaryFile", make_file)

    async def run():
        async def app(scope, receive, send):
            assert (await receive())["body"] == b"ok"
            assert (await receive())["type"] == "http.disconnect"

        messages = iter(
            [{"type": "http.request", "body": b"ok"}, {"type": "http.disconnect"}]
        )

        async def receive():
            return next(messages)

        async def send(message):
            raise AssertionError(message)

        await BodyLimitMiddleware(app)(
            {"type": "http", "path": "/", "headers": []}, receive, send
        )

    asyncio.run(run())
    assert files and files[0].closed


@pytest.mark.parametrize("declared,body", [(b"0", b"x"), (b"2", b"x"), (b"1", b"xx")])
def test_declared_length_mismatch_never_dispatches(declared, body):
    async def run():
        output = []

        async def app(*args):
            raise AssertionError("mismatched body reached handler")

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            output.append(message)

        await BodyLimitMiddleware(app, default_limit=4, path_limits={})(
            {"type": "http", "path": "/", "headers": [(b"content-length", declared)]},
            receive,
            send,
        )
        assert output[0]["status"] == 400

    asyncio.run(run())


def test_exact_allowance_paths_are_enforced_at_http_boundary():
    async def run():
        seen = []

        async def app(scope, receive, send):
            seen.append((await receive())["body"])
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = BodyLimitMiddleware(
            app, default_limit=2, path_limits={path: 4 for path in PATH_LIMITS}
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=middleware), base_url="http://test"
        ) as client:
            for path in PATH_LIMITS:
                assert (await client.post(path, content=b"abcd")).status_code == 200
                assert (await client.post(path, content=b"abcde")).status_code == 413
                assert (
                    await client.post(path + "/extra", content=b"abc")
                ).status_code == 413
            assert (await client.post("/mcp", content=b"abc")).status_code == 413
        assert seen == [b"abcd"] * len(PATH_LIMITS)

    asyncio.run(run())


@pytest.mark.parametrize(
    "phase", ["success", "overflow", "disconnect", "handler-error"]
)
def test_rolled_spool_replay_and_cleanup(monkeypatch, phase):
    import gigamind.middleware.body_limits as limits

    files = []
    original = limits.SpooledTemporaryFile

    def make_file(*args, **kwargs):
        file = original(*args, **kwargs)
        files.append(file)
        return file

    monkeypatch.setattr(limits, "SpooledTemporaryFile", make_file)
    monkeypatch.setattr(limits, "SPOOL_MEMORY_LIMIT", 4)

    async def run():
        seen, output = [], []
        messages = [{"type": "http.request", "body": b"first", "more_body": True}]
        if phase == "disconnect":
            messages.append({"type": "http.disconnect"})
        else:
            messages.append(
                {
                    "type": "http.request",
                    "body": b"last" * (5 if phase == "overflow" else 1),
                    "more_body": False,
                }
            )

        async def receive():
            return messages.pop(0)

        async def send(message):
            output.append(message)

        async def app(scope, replay, send):
            data = b""
            while True:
                message = await replay()
                data += message["body"]
                if not message["more_body"]:
                    break
            seen.append(data)
            if phase == "handler-error":
                raise LookupError("test handler failed")

        middleware = BodyLimitMiddleware(app, default_limit=12, path_limits={})
        if phase == "handler-error":
            with pytest.raises(LookupError, match="test handler"):
                await middleware(
                    {"type": "http", "path": "/", "headers": []}, receive, send
                )
        else:
            await middleware(
                {"type": "http", "path": "/", "headers": []}, receive, send
            )
        assert seen == ([b"firstlast"] if phase in ("success", "handler-error") else [])
        assert [
            message["status"]
            for message in output
            if message["type"] == "http.response.start"
        ] == ([413] if phase == "overflow" else [])

    asyncio.run(run())
    assert len(files) == 1 and files[0].closed


def test_non_http_scopes_pass_through_without_receiving():
    async def run():
        scopes = []

        async def app(scope, receive, send):
            scopes.append(scope["type"])

        async def unexpected():
            raise AssertionError("non-HTTP scope read as a request body")

        for kind in ("websocket", "lifespan"):
            await BodyLimitMiddleware(app)({"type": kind}, unexpected, unexpected)
        assert scopes == ["websocket", "lifespan"]

    asyncio.run(run())


def test_malformed_and_oversized_lengths_are_rejected_before_receive():
    async def run():
        async def app(*args):
            raise AssertionError("bad header reached handler")

        async def unexpected():
            raise AssertionError("bad header caused a body read")

        async def check(headers, expected):
            output = []

            async def send(message):
                output.append(message)

            await BodyLimitMiddleware(app, default_limit=4, path_limits={})(
                {"type": "http", "path": "/", "headers": headers}, unexpected, send
            )
            assert output[0]["status"] == expected

        for value in (b"", b"1.0", b"+1", b" 1", b"1 ", b"-1"):
            await check([(b"content-length", value)], 400)
        await check(
            [(b"content-length", b"1"), (b"transfer-encoding", b"chunked")], 400
        )
        await check([(b"content-length", b"9" * 10000)], 413)

    asyncio.run(run())


def test_real_app_limits_mcp_and_keeps_cors_headers(tmp_path):
    import os
    import subprocess
    import sys

    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.getcwd(),
        "PYTHON_DOTENV_DISABLED": "1",
        "DATABASE_URL": "",
        "DB_PATH": str(tmp_path / "app-body.db"),
        "GIGAMIND_API_KEY": "isolated-body-key",
        "GIGAMIND_CORS_ORIGINS": "https://console.example.test",
    }
    script = """
from fastapi.testclient import TestClient
from gigamind.main import app
from gigamind.middleware.body_limits import DEFAULT_LIMIT
with TestClient(app) as c:
    origin = {'Origin':'https://console.example.test'}
    response = c.options('/mcp', headers={**origin,'Access-Control-Request-Method':'POST'})
    assert response.status_code == 200
    oversized = c.post('/mcp', headers={**origin,'Content-Length':str(DEFAULT_LIMIT + 1)}, content=b'')
    assert oversized.status_code == 413, oversized.text
    assert oversized.headers['access-control-allow-origin'] == origin['Origin']
    headers = {'Authorization':'Bearer isolated-body-key'}
    data = b'x' * (DEFAULT_LIMIT + 1)
    assert c.post('/api/v1/memories', headers=headers, content=data).status_code == 413
    # The exact upload allowance reaches validation, without executing storage IO.
    assert c.post('/api/v1/files/upload', headers=headers, content=data).status_code == 422
    assert c.post('/api/v1/files/upload/extra', headers=headers, content=data).status_code == 413
    assert c.get('/api/v1/memories', headers=headers).json()['memories'] == []
"""
    subprocess.run([sys.executable, "-c", script], env=env, check=True, timeout=30)
