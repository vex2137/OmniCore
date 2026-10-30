"""Short-lived LAN pairing and revocable device credentials. Store only hashes."""

import hashlib
import ipaddress
import secrets
import threading
import time
from collections import OrderedDict

from fastapi import APIRouter, Request
from pydantic import Field

from omnicore.schemas import WireModel
from omnicore.text.types import TextError


def private_peer(host):
    try:
        address = ipaddress.ip_address(host)
        return address.is_loopback or (
            address.version == 4
            and any(
                address in ipaddress.ip_network(n)
                for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
            )
        )
    except ValueError:
        return False


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Redeem(WireModel):
    code: str = Field(min_length=64, max_length=64, pattern="^[a-f0-9]+$", repr=False)


class PairingOffer(WireModel):
    id: str
    code: str = Field(repr=False)
    expires_at: float


class DeviceCredential(WireModel):
    device_id: str
    token: str = Field(repr=False)


class Pairings:
    def __init__(self, db):
        self.db = db
        self.attempts = OrderedDict()
        self.attempts_lock = threading.Lock()

    def initialize(self):
        with self.db.connect() as c, c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS lan_pairing "
                "(id TEXT PRIMARY KEY, hash TEXT, expires REAL)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS lan_devices "
                "(id TEXT PRIMARY KEY, hash TEXT UNIQUE, created REAL)"
            )
            # Restart cancels offers; paired credentials survive restart.
            c.execute("DELETE FROM lan_pairing")

    def create(self):
        code, key = secrets.token_hex(32), secrets.token_hex(16)
        expires = time.time() + 120
        with self.db.connect() as c, c:
            c.execute("DELETE FROM lan_pairing")
            c.execute("INSERT INTO lan_pairing VALUES(?,?,?)", (key, digest(code), expires))
        return PairingOffer(id=key, code=code, expires_at=expires)

    def redeem(self, code, peer):
        now = time.monotonic()
        with self.attempts_lock:
            count, start = self.attempts.pop(peer, (0, now))
            if now - start >= 60:
                count, start = 0, now
            self.attempts[peer] = (count + 1, start)
            while len(self.attempts) > 512:
                self.attempts.popitem(last=False)
        if count >= 10:
            raise TextError("pairing_rate_limited", 429)
        token, device = secrets.token_hex(32), secrets.token_hex(16)
        with self.db.connect() as c, c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT id FROM lan_pairing WHERE hash=? AND expires>?", (digest(code), time.time())
            ).fetchone()
            if not row:
                raise TextError("pairing_invalid", 403)
            c.execute("DELETE FROM lan_pairing WHERE id=?", (row[0],))
            c.execute("INSERT INTO lan_devices VALUES(?,?,?)", (device, digest(token), time.time()))
        return DeviceCredential(device_id=device, token=token)

    def authenticate(self, token):
        if not token or len(token) > 128:
            return False
        with self.db.connect() as c:
            return (
                c.execute("SELECT 1 FROM lan_devices WHERE hash=?", (digest(token),)).fetchone()
                is not None
            )


def routes(pairings, config):
    router = APIRouter(prefix="/api/v1/pairing")

    def admin(request):
        peer = request.client.host if request.client else ""
        try:
            local = ipaddress.ip_address(peer).is_loopback
        except ValueError:
            local = False
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
        if (
            not local
            or not config.api_token
            or not secrets.compare_digest(supplied.encode(), config.api_token.encode())
        ):
            raise TextError("pairing_admin_required", 403)
        if not config.allow_remote:
            raise TextError("pairing_lan_required", 409)

    @router.post("/offers", response_model=PairingOffer)
    def create_offer(request: Request):
        admin(request)
        return pairings.create()

    @router.delete("/offers/{offer_id}")
    def cancel_offer(offer_id: str, request: Request):
        admin(request)
        with pairings.db.connect() as c, c:
            c.execute("DELETE FROM lan_pairing WHERE id=?", (offer_id,))
        return {"status": "cancelled"}

    @router.post("/redeem", response_model=DeviceCredential, openapi_extra={"security": []})
    def redeem(body: Redeem, request: Request):
        peer = request.client.host if request.client else ""
        if not config.allow_remote or not private_peer(peer):
            raise TextError("pairing_lan_required", 403)
        return pairings.redeem(body.code, peer)

    @router.get("/devices")
    def devices(request: Request):
        admin(request)
        with pairings.db.connect() as c:
            return [
                {"id": r[0], "created_at": r[1]}
                for r in c.execute("SELECT id,created FROM lan_devices ORDER BY created")
            ]

    @router.delete("/devices/{device_id}")
    def revoke(device_id: str, request: Request):
        admin(request)
        with pairings.db.connect() as c, c:
            c.execute("DELETE FROM lan_devices WHERE id=?", (device_id,))
        return {"status": "revoked"}

    return router
