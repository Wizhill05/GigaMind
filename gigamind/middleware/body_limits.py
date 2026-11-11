"""Bound HTTP request bodies before dispatching to application code."""

from tempfile import SpooledTemporaryFile

from starlette.responses import JSONResponse

DEFAULT_LIMIT = 1024 * 1024
MULTIPART_LIMIT = 21 * 1024 * 1024
BASE64_LIMIT = 28 * 1024 * 1024
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
        if any(type(value) is not int or value <= 0 for value in (default_limit, *self.path_limits.values())):
            raise ValueError("Body limits must be positive integers")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.path_limits.get(scope["path"], self.default_limit)
        headers = scope.get("headers", [])
        lengths = [value for name, value in headers if name.lower() == b"content-length"]
        transfer = any(name.lower() == b"transfer-encoding" for name, _ in headers)
        if len(lengths) > 1 or (lengths and transfer) or (lengths and (not lengths[0] or not lengths[0].isdigit())):
            await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(scope, receive, send)
            return
        if lengths and (len(lengths[0].lstrip(b"0")) > len(str(limit)) or
                        (len(lengths[0].lstrip(b"0")) == len(str(limit)) and
                         lengths[0].lstrip(b"0") > str(limit).encode())):
            await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
            return
        with SpooledTemporaryFile(max_size=1024 * 1024) as body:
            size = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > limit:
                    await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
                    return
                body.write(chunk)
                if not message.get("more_body", False):
                    break
            body.seek(0)
            remaining = size
            finished = False

            async def replay():
                nonlocal remaining, finished
                if finished:
                    return await receive()
                chunk = body.read(min(remaining, 64 * 1024))
                remaining -= len(chunk)
                finished = remaining == 0
                return {"type": "http.request", "body": chunk, "more_body": not finished}

            await self.app(scope, replay, send)
