"""Bound HTTP request bodies before dispatching to application code."""

from tempfile import SpooledTemporaryFile

from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

DEFAULT_LIMIT = 1024 * 1024
MULTIPART_LIMIT = 21 * 1024 * 1024
BASE64_LIMIT = 28 * 1024 * 1024
SPOOL_MEMORY_LIMIT = 1024 * 1024
PATH_LIMITS = {
    "/api/v1/files/upload": MULTIPART_LIMIT,
    "/api/v1/conversations/import_file": MULTIPART_LIMIT,
    "/api/v1/files/upload_base64": BASE64_LIMIT,
}


class BodyLimitMiddleware:
    def __init__(self, app, default_limit=DEFAULT_LIMIT, path_limits=None):
        self.app = app
        self.default_limit = default_limit
        self.path_limits = dict(PATH_LIMITS if path_limits is None else path_limits)
        if any(
            type(value) is not int or value <= 0
            for value in (default_limit, *self.path_limits.values())
        ):
            raise ValueError("Body limits must be positive integers")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.path_limits.get(scope["path"], self.default_limit)
        headers = scope.get("headers", [])
        lengths = [
            value for name, value in headers if name.lower() == b"content-length"
        ]
        transfer = any(name.lower() == b"transfer-encoding" for name, _ in headers)
        if (
            len(lengths) > 1
            or (lengths and transfer)
            or (lengths and (not lengths[0] or not lengths[0].isdigit()))
        ):
            await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(
                scope, receive, send
            )
            return
        if lengths and (
            len(lengths[0].lstrip(b"0")) > len(str(limit))
            or (
                len(lengths[0].lstrip(b"0")) == len(str(limit))
                and lengths[0].lstrip(b"0") > str(limit).encode()
            )
        ):
            await JSONResponse({"detail": "Request body too large"}, status_code=413)(
                scope, receive, send
            )
            return
        expected = int(lengths[0].lstrip(b"0") or b"0") if lengths else None
        with SpooledTemporaryFile(max_size=SPOOL_MEMORY_LIMIT) as body:
            size = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                if message["type"] != "http.request":
                    raise RuntimeError("Unexpected ASGI request message")
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > limit:
                    await JSONResponse(
                        {"detail": "Request body too large"}, status_code=413
                    )(scope, receive, send)
                    return
                if expected is not None and size > expected:
                    await JSONResponse(
                        {"detail": "Content-Length mismatch"}, status_code=400
                    )(scope, receive, send)
                    return
                if size > SPOOL_MEMORY_LIMIT:
                    await run_in_threadpool(body.write, chunk)
                else:
                    body.write(chunk)
                if not message.get("more_body", False):
                    break
            if expected is not None and size != expected:
                await JSONResponse(
                    {"detail": "Content-Length mismatch"}, status_code=400
                )(scope, receive, send)
                return
            spilled = size > SPOOL_MEMORY_LIMIT
            if spilled:
                await run_in_threadpool(body.seek, 0)
            else:
                body.seek(0)
            remaining = size
            finished = False

            async def replay():
                nonlocal remaining, finished
                if finished:
                    return await receive()
                read_size = min(remaining, 64 * 1024)
                chunk = (
                    await run_in_threadpool(body.read, read_size)
                    if spilled
                    else body.read(read_size)
                )
                remaining -= len(chunk)
                finished = remaining == 0
                return {
                    "type": "http.request",
                    "body": chunk,
                    "more_body": not finished,
                }

            await self.app(scope, replay, send)
