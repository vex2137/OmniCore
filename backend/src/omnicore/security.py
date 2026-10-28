"""ASGI boundary: authenticate before parsing, bound incoming bodies, check origins."""

import secrets
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from omnicore.config import RuntimeConfig, is_loopback
from omnicore.localization import message


def error_response(code: str, status: int, language: str | None = None) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(
        {"error": {"code": code, "message": message(code, language)}},
        status_code=status,
        headers=headers,
    )


class SecurityBoundary:
    def __init__(self, app: ASGIApp, config: RuntimeConfig):
        self.app = app
        self.config = config
        self.origins = set(config.allowed_origins)
        self.hosts = {host.lower() for host in config.allowed_hosts}
        if config.host not in {"0.0.0.0", "::"}:  # noqa: S104 — comparison, not a binding.
            self.hosts.add(config.host.lower())
        if is_loopback(config.host):
            host = f"[{config.host}]" if ":" in config.host else config.host
            self.origins.add(f"http://{host}:{config.port}")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        websocket = scope["type"] == "websocket"
        preflight = (
            not websocket
            and scope["method"] == "OPTIONS"
            and "access-control-request-method" in headers
        )
        authorization = headers.get("authorization", "")
        scheme, _, credentials = authorization.partition(" ")
        token = credentials if scheme.lower() == "bearer" else ""
        if websocket and not token:
            protocols = scope.get("subprotocols", [])
            token = next((item[7:] for item in protocols if item.startswith("bearer.")), "")
        code, status = None, 0
        try:
            host = urlsplit("//" + headers.get("host", "")).hostname
        except ValueError:
            host = None
        if host not in self.hosts:
            code, status = "forbidden_host", 403
        if self.config.api_token and not preflight:
            if not secrets.compare_digest(token.encode(), self.config.api_token.encode()):
                code, status = "unauthorized", 401
        if code is None and "origin" in headers and headers["origin"] not in self.origins:
            code, status = "forbidden_origin", 403
        if code:
            if websocket:
                await send({"type": "websocket.close", "code": 4401 if status == 401 else 4403})
            else:
                await error_response(code, status, headers.get("accept-language"))(
                    scope, receive, send
                )
            return
        if websocket:
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            chunk = event.get("body", b"")
            if len(body) + len(chunk) > self.config.max_body_bytes:
                await error_response("request_too_large", 413, headers.get("accept-language"))(
                    scope, receive, send
                )
                return
            body.extend(chunk)
            if not event.get("more_body", False):
                break
        consumed = False

        async def bounded_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
