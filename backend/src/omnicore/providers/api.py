"""Redacted provider management. Only explicit model selection can send chat content out."""

import ipaddress

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from omnicore.providers.service import CloudModel, ProviderInfo, ProviderInput
from omnicore.text.types import TextError


def routes(service):
    router = APIRouter(prefix="/api/v1/providers", tags=["External AI providers"])
    providers = service.providers

    def manage(request, key_transfer=False):
        if not providers.authenticated:
            raise TextError("provider_requires_server_auth", 403)
        if "providers" not in request.scope.get("omnicore_scopes", []):
            raise TextError("provider_permission_required", 403)
        if key_transfer and request.url.scheme != "https":
            try:
                local = ipaddress.ip_address(request.client.host).is_loopback
            except (ValueError, AttributeError):
                local = False
            if not local:
                raise TextError("provider_key_requires_https", 403)

    @router.get("/configs", response_model=list[ProviderInfo])
    def configs():
        return providers.list()

    @router.post("/configs", response_model=ProviderInfo, status_code=201)
    async def create(body: ProviderInput, request: Request):
        manage(request, body.api_key is not None)
        async with service.generations.submission_lock:
            return await run_in_threadpool(providers.save, body)

    @router.put("/configs/{provider_id}", response_model=ProviderInfo)
    async def update(provider_id: str, body: ProviderInput, request: Request):
        manage(request, body.api_key is not None)
        async with service.generations.submission_lock:
            service.require_idle()
            await service.generations.titles.interrupt()
            return await run_in_threadpool(providers.save, body, provider_id)

    @router.delete("/configs/{provider_id}")
    async def delete(provider_id: str, request: Request):
        manage(request)
        async with service.generations.submission_lock:
            service.require_idle()
            await service.generations.titles.interrupt()
            await run_in_threadpool(providers.delete, provider_id)
        return {"status": "deleted"}

    @router.get("/configs/{provider_id}/models", response_model=list[str])
    async def list_models(provider_id: str, request: Request):
        manage(request)
        return await providers.models(provider_id)

    @router.post("/configs/{provider_id}/test")
    async def test(provider_id: str, request: Request):
        manage(request)
        models = await providers.models(provider_id)
        return {"status": "ok", "model_count": len(models)}

    @router.post("/configs/{provider_id}/models")
    async def add_model(provider_id: str, body: CloudModel, request: Request):
        manage(request)
        if not body.confirmed_external:
            raise TextError("provider_confirmation_required", 422)
        async with service.generations.submission_lock:
            return await run_in_threadpool(providers.add_model, provider_id, body.model_id)

    return router
