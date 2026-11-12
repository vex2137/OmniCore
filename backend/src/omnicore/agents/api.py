"""Permission and approval endpoints belong to the human client, never the tool registry."""

from fastapi import APIRouter
from pydantic import Field

from omnicore.agents.capabilities import capability
from omnicore.agents.service import AgentRequest, AgentSettings
from omnicore.schemas import WireModel
from omnicore.text.types import GenerationParameters, TextError


class FolderGrant(WireModel):
    path: str = Field(min_length=1, max_length=4096)
    include_sensitive: bool = False
    confirmed: bool = False


class CompatibilityTest(WireModel):
    confirmed: bool = False
    parameters: GenerationParameters | None = None
    protocol: str = Field(default="auto", pattern=r"^(auto|structured)$")


class RetryRequest(WireModel):
    parameters: GenerationParameters | None = None


class Approval(WireModel):
    proposal_id: str = Field(min_length=1, max_length=64)
    approved: bool


def routes(service):
    router = APIRouter(prefix="/api/v1/agents", tags=["Local agents"])
    agents = service.agents

    @router.get("/models/{model_id}/compatibility")
    def model_compatibility(model_id: str):
        return capability(service, service.store.model(model_id))

    @router.post("/models/{model_id}/compatibility-test")
    async def test_compatibility(model_id: str, body: CompatibilityTest):
        if not body.confirmed:
            raise TextError("agent_confirmation_required", 422)
        return await agents.test_compatibility(model_id, body.parameters, body.protocol)

    @router.post("/runs/{run_id}/retry", status_code=202)
    async def retry(run_id: str, body: RetryRequest | None = None):
        return await agents.retry(run_id, body.parameters if body else None)

    @router.get("/conversations/{conversation_id}/settings", response_model=AgentSettings)
    def settings(conversation_id: str):
        return agents.settings(conversation_id)

    @router.put("/conversations/{conversation_id}/settings", response_model=AgentSettings)
    async def save_settings(conversation_id: str, body: AgentSettings):
        async with service.generations.submission_lock:
            service.history.get(conversation_id)
            service.require_idle(conversation_id=conversation_id)
            service.store.save_job("agent-settings", conversation_id, body.model_dump())
        return body

    @router.get("/conversations/{conversation_id}/folders")
    async def folders(conversation_id: str):
        service.history.get(conversation_id)
        return [
            agents.files.describe(g)
            for g in agents.files.grants.values()
            if g.active and g.conversation_id == conversation_id
        ]

    @router.post("/conversations/{conversation_id}/folders")
    async def grant(conversation_id: str, body: FolderGrant):
        service.history.get(conversation_id)
        if not body.confirmed:
            raise TextError("agent_confirmation_required", 422)
        try:
            return agents.files.grant(conversation_id, body.path, body.include_sensitive)
        except (OSError, ValueError, RuntimeError):
            raise TextError("agent_permission_denied", 403) from None

    @router.delete("/conversations/{conversation_id}/folders/{grant_id}")
    async def revoke(conversation_id: str, grant_id: str):
        for run_id in list(agents.tasks):
            if agents.record(run_id)["conversation_id"] == conversation_id:
                await agents.cancel(run_id)
        agents.files.revoke(grant_id, conversation_id)
        return {"revoked": True}

    @router.post("/conversations/{conversation_id}/runs", status_code=202)
    async def run(conversation_id: str, body: AgentRequest):
        return await agents.submit(conversation_id, body)

    @router.get("/conversations/{conversation_id}/runs")
    def history(conversation_id: str):
        service.history.get(conversation_id)
        return [
            agents.snapshot(r["id"])
            for r in agents.store.jobs("agent-run")
            if r["conversation_id"] == conversation_id
        ][:100]

    @router.get("/runs/{run_id}")
    def snapshot(run_id: str):
        return agents.snapshot(run_id)

    @router.post("/runs/{run_id}/cancel")
    async def cancel(run_id: str):
        return await agents.cancel(run_id)

    @router.post("/runs/{run_id}/steps/{step_id}/approval")
    async def approve(run_id: str, step_id: str, body: Approval):
        agents.approve(run_id, step_id, body.proposal_id, body.approved)
        return {"accepted": True}

    return router
