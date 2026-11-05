"""Owner-managed additional bearer tokens; the main process credential is never listed."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import Field

from omnicore.pairing import DeviceCredential, require_owner
from omnicore.schemas import WireModel
from omnicore.text.types import TextError


class TokenCreate(WireModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[^\x00-\x1f\x7f]+$")
    expires_at: float | None = Field(default=None, allow_inf_nan=False)
    scopes: list[Literal["chat", "providers"]] = Field(
        default_factory=lambda: ["chat"], min_length=1, max_length=2
    )


class RevokeAll(WireModel):
    confirmed: bool = False


def routes(tokens, config):
    router = APIRouter(prefix="/api/v1/access")

    @router.get("/capabilities")
    def capabilities(request: Request):
        return {
            "scopes": request.scope.get("omnicore_scopes", []),
            "secure_transport": request.url.scheme == "https",
        }

    @router.get("/tokens")
    def list_tokens(request: Request):
        require_owner(request, config)
        return tokens.tokens()

    @router.post("/tokens", response_model=DeviceCredential)
    def create(body: TokenCreate, request: Request):
        require_owner(request, config)
        if "chat" not in body.scopes or not body.name.strip():
            raise TextError("validation_error", 422)
        return tokens.create_token(body.name.strip(), body.expires_at, sorted(set(body.scopes)))

    @router.delete("/tokens/{token_id}")
    def revoke(token_id: str, request: Request):
        require_owner(request, config)
        with tokens.db.connect() as c, c:
            c.execute("DELETE FROM lan_devices WHERE id=?", (token_id,))
        return {"status": "revoked"}

    @router.delete("/tokens")
    def revoke_all(body: RevokeAll, request: Request):
        require_owner(request, config)
        if not body.confirmed:
            raise TextError("confirmation_required", 422)
        with tokens.db.connect() as c, c:
            c.execute("DELETE FROM lan_pairing")
            c.execute("DELETE FROM lan_devices")
        return {"status": "revoked"}

    return router
