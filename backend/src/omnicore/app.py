"""Functional foundation API; no generation routes until real adapters exist."""

import asyncio
import sqlite3
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.websockets import WebSocketDisconnect

from omnicore import __version__
from omnicore.adapters import AdapterRegistry
from omnicore.config import RuntimeConfig
from omnicore.database import Database
from omnicore.events import EventHub
from omnicore.localization import catalog, message
from omnicore.schemas import (
    BackendInfo,
    ClientEvent,
    ErrorDetail,
    ErrorResponse,
    Health,
    Locale,
    LocaleCatalog,
    Preferences,
    ServerEvent,
)
from omnicore.security import SecurityBoundary, error_response


def create_app(config: RuntimeConfig | None = None) -> FastAPI:
    config = config or RuntimeConfig.from_env()
    db = Database(config.data_dir)
    hub = EventHub()
    registry = AdapterRegistry()
    settings_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_in_threadpool(db.initialize)
        yield

    errors = {code: {"model": ErrorResponse} for code in [401, 403, 404, 405, 413, 422, 500, 503]}
    app = FastAPI(
        title="OmniCore",
        version=__version__,
        description="Stage 1 foundation. Inference engines and clients are not implemented yet.",
        lifespan=lifespan,
        responses=errors,
        docs_url=None,
        redoc_url=None,
    )
    app.state.db = db
    app.state.registry = registry
    app.state.hub = hub

    def openapi():
        if app.openapi_schema is None:
            spec = get_openapi(
                title=app.title, version=app.version, description=app.description, routes=app.routes
            )
            spec["components"]["securitySchemes"] = {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": (
                        "Required remotely and whenever a runtime API token is configured."
                    ),
                }
            }
            spec["security"] = [{}, {"BearerAuth": []}]
            app.openapi_schema = spec
        return app.openapi_schema

    app.openapi = openapi
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.allowed_origins),
        allow_methods=["GET", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept-Language"],
    )
    app.add_middleware(SecurityBoundary, config=config)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Do not echo inputs: future requests may contain sensitive user data.
        return error_response("validation_error", 422, request.headers.get("accept-language"))

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "internal_error")
        return error_response(code, exc.status_code, request.headers.get("accept-language"))

    @app.exception_handler(sqlite3.Error)
    async def database_error(request: Request, exc: sqlite3.Error):
        return error_response("database_unavailable", 503, request.headers.get("accept-language"))

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        return error_response("internal_error", 500, request.headers.get("accept-language"))

    @app.get("/api/v1/health", response_model=Health, operation_id="getHealth")
    def health():
        return Health(version=__version__, database_version=db.version())

    @app.get("/api/v1/settings", response_model=Preferences, operation_id="getSettings")
    def get_settings():
        return db.preferences()

    @app.put("/api/v1/settings", response_model=Preferences, operation_id="replaceSettings")
    async def replace_settings(preferences: Preferences):
        async with settings_lock:
            saved = await run_in_threadpool(db.save_preferences, preferences)
            hub.publish(ServerEvent(type="settings.updated", settings=saved))
        return saved

    @app.get("/api/v1/locales", response_model=list[Locale], operation_id="listLocales")
    def list_locales():
        return list(Locale)

    @app.get("/api/v1/locales/{locale}", response_model=LocaleCatalog, operation_id="getLocale")
    def get_locale(locale: Locale):
        return LocaleCatalog(locale=locale, messages=catalog(locale))

    @app.get("/api/v1/backends", response_model=list[BackendInfo], operation_id="listBackends")
    async def list_backends():
        return await registry.discover()

    @app.websocket("/api/v1/events")
    async def events(websocket: WebSocket):
        subprotocol = "omnicore.v1" if "omnicore.v1" in websocket.scope["subprotocols"] else None
        await websocket.accept(subprotocol=subprotocol)

        async def sender(queue):
            while True:
                event = await queue.get()
                await websocket.send_text(event.model_dump_json(exclude_none=True))

        async def receiver(queue):
            while True:
                event = await websocket.receive()
                if event["type"] == "websocket.disconnect":
                    return
                text = event.get("text")
                if text is None:
                    await websocket.close(code=1003)
                    return
                if len(text.encode()) > config.max_body_bytes:
                    await websocket.close(code=1009)
                    return
                try:
                    ClientEvent.model_validate_json(text)
                except ValidationError:
                    hub.enqueue(
                        queue,
                        ServerEvent(
                            type="error",
                            error=ErrorDetail(
                                code="validation_error",
                                message=message(
                                    "validation_error", websocket.headers.get("accept-language")
                                ),
                            ),
                        ),
                    )
                else:
                    hub.enqueue(queue, ServerEvent(type="pong"))

        with hub.subscribe() as queue:
            try:
                async with settings_lock:
                    # The initial snapshot supersedes changes queued while acquiring the lock.
                    while not queue.empty():
                        queue.get_nowait()
                    preferences = await run_in_threadpool(db.preferences)
                    hub.enqueue(queue, ServerEvent(type="hello", settings=preferences))
            except sqlite3.Error:
                await websocket.send_text(
                    ServerEvent(
                        type="error",
                        error=ErrorDetail(
                            code="database_unavailable",
                            message=message(
                                "database_unavailable", websocket.headers.get("accept-language")
                            ),
                        ),
                    ).model_dump_json(exclude_none=True)
                )
                await websocket.close(code=1011)
                return
            async with anyio.create_task_group() as group:

                async def send_events():
                    try:
                        await sender(queue)
                    except WebSocketDisconnect:
                        pass
                    finally:
                        group.cancel_scope.cancel()

                group.start_soon(send_events)
                try:
                    await receiver(queue)
                except WebSocketDisconnect:
                    pass
                finally:
                    group.cancel_scope.cancel()

    return app
