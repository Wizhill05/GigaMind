import asyncio

import httpx
import pytest

from gigamind.middleware.body_limits import BodyLimitMiddleware, DEFAULT_LIMIT, PATH_LIMITS


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
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=limited), base_url="http://test") as client:
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
    for headers in [[(b"content-length", b"-1")], [(b"content-length", b"1"), (b"content-length", b"1")], [(b"content-length", b"1, 1")]]:
        assert (await run(headers, []))[0]["status"] == 400
    assert (await run([], [{"type": "http.request", "body": b"x" * 1000000}]))[0]["status"] == 413
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
        messages = iter([{"type": "http.request", "body": b"ok"}, {"type": "http.disconnect"}])
        async def receive():
            return next(messages)
        async def send(message):
            raise AssertionError(message)
        await BodyLimitMiddleware(app)({"type": "http", "path": "/", "headers": []}, receive, send)
    asyncio.run(run())
    assert files and files[0].closed
