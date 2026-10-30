"""Short-lived LAN pairing and revocable device credentials. Store only hashes."""

import hashlib
import hmac
import ipaddress
import json
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
    nonce: str | None = Field(
        default=None, min_length=64, max_length=64, pattern="^[a-f0-9]+$", repr=False
    )


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
            columns = {row[1] for row in c.execute("PRAGMA table_info(lan_pairing)")}
            for name, declaration in [("nonce_hash", "TEXT"), ("device_id", "TEXT")]:
                if name not in columns:
                    c.execute(f"ALTER TABLE lan_pairing ADD COLUMN {name} {declaration}")
            c.execute(
                "CREATE TABLE IF NOT EXISTS lan_token_info ("
                "id TEXT PRIMARY KEY REFERENCES lan_devices(id) ON DELETE CASCADE, "
                "name TEXT NOT NULL, expires REAL, last_used REAL, scopes TEXT NOT NULL)"
            )
            c.execute(
                "INSERT OR IGNORE INTO lan_token_info(id,name,scopes) "
                "SELECT id, 'Paired device', ? FROM lan_devices",
                (json.dumps(["chat", "providers"]),),
            )
            # Restart cancels offers; paired credentials survive restart.
            c.execute("DELETE FROM lan_pairing")

    def create(self):
        code, key = secrets.token_hex(32), secrets.token_hex(16)
        expires = time.time() + 120
        with self.db.connect() as c, c:
            c.execute(
                "DELETE FROM lan_pairing WHERE device_id IS NULL OR expires<=?", (time.time(),)
            )
            c.execute(
                "INSERT INTO lan_pairing(id,hash,expires) VALUES(?,?,?)",
                (key, digest(code), expires),
            )
        return PairingOffer(id=key, code=code, expires_at=expires)

    def redeem(self, code, peer, nonce=None):
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
        token = (
            hmac.new(bytes.fromhex(nonce), code.encode(), hashlib.sha256).hexdigest()
            if nonce
            else secrets.token_hex(32)
        )
        device = secrets.token_hex(16)
        with self.db.connect() as c, c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT id,expires,nonce_hash,device_id FROM lan_pairing WHERE hash=?",
                (digest(code),),
            ).fetchone()
            if not row:
                raise TextError("pairing_invalid", 403)
            if row[1] <= time.time():
                raise TextError("pairing_expired", 403)
            if row[3]:
                if nonce and row[2] and secrets.compare_digest(row[2], digest(nonce)):
                    # A consumed code is bound to the original client's high-entropy nonce.
                    # Retry cannot mint another token or revive a revoked credential.
                    if c.execute(
                        "SELECT 1 FROM lan_devices WHERE id=? AND hash=?", (row[3], digest(token))
                    ).fetchone():
                        return DeviceCredential(device_id=row[3], token=token)
                raise TextError("pairing_used", 403)
            if nonce:
                c.execute(
                    "UPDATE lan_pairing SET nonce_hash=?,device_id=? WHERE id=?",
                    (digest(nonce), device, row[0]),
                )
            else:
                c.execute("DELETE FROM lan_pairing WHERE id=?", (row[0],))
            c.execute("INSERT INTO lan_devices VALUES(?,?,?)", (device, digest(token), time.time()))
            c.execute(
                "INSERT INTO lan_token_info(id,name,scopes) VALUES(?,?,?)",
                (device, "Android QR", json.dumps(["chat", "providers"])),
            )
        return DeviceCredential(device_id=device, token=token)

    def authenticate(self, token):
        if not token or len(token) > 128:
            return None
        with self.db.connect() as c, c:
            row = c.execute(
                "SELECT d.id,i.scopes FROM lan_devices d JOIN lan_token_info i ON i.id=d.id "
                "WHERE d.hash=? AND (i.expires IS NULL OR i.expires>?)",
                (digest(token), time.time()),
            ).fetchone()
            if not row:
                return None
            now = time.time()
            c.execute(
                "UPDATE lan_token_info SET last_used=? WHERE id=? "
                "AND (last_used IS NULL OR last_used<?)",
                (now, row[0], now - 60),
            )
            return {"id": row[0], "scopes": json.loads(row[1])}

    def tokens(self):
        with self.db.connect() as c:
            return [
                dict(
                    zip(
                        ("id", "created_at", "name", "expires_at", "last_used_at", "scopes"),
                        (*r[:5], json.loads(r[5])),
                        strict=True,
                    )
                )
                for r in c.execute(
                    "SELECT d.id,d.created,i.name,i.expires,i.last_used,i.scopes "
                    "FROM lan_devices d JOIN lan_token_info i ON i.id=d.id ORDER BY d.created"
                )
            ]

    def create_token(self, name, expires_at=None, scopes=("chat",)):
        if expires_at is not None and not time.time() < expires_at <= time.time() + 366 * 86400:
            raise TextError("token_expiry_invalid", 422)
        token, device = secrets.token_hex(32), secrets.token_hex(16)
        with self.db.connect() as c, c:
            c.execute("INSERT INTO lan_devices VALUES(?,?,?)", (device, digest(token), time.time()))
            c.execute(
                "INSERT INTO lan_token_info(id,name,expires,scopes) VALUES(?,?,?,?)",
                (device, name, expires_at, json.dumps(scopes)),
            )
        return DeviceCredential(device_id=device, token=token)


def require_owner(request, config):
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


def routes(pairings, config):
    router = APIRouter(prefix="/api/v1/pairing")

    def admin(request):
        require_owner(request, config)
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
            c.execute("DELETE FROM lan_pairing WHERE id=? AND device_id IS NULL", (offer_id,))
        return {"status": "cancelled"}

    @router.post("/redeem", response_model=DeviceCredential, openapi_extra={"security": []})
    def redeem(body: Redeem, request: Request):
        peer = request.client.host if request.client else ""
        if not config.allow_remote or not private_peer(peer):
            raise TextError("pairing_lan_required", 403)
        return pairings.redeem(body.code, peer, body.nonce)

    @router.get("/offers/{offer_id}")
    def offer_status(offer_id: str, request: Request):
        admin(request)
        with pairings.db.connect() as c:
            row = c.execute(
                "SELECT expires,device_id FROM lan_pairing WHERE id=?", (offer_id,)
            ).fetchone()
        return {
            "status": "cancelled"
            if row is None
            else "used"
            if row[1]
            else "expired"
            if row[0] <= time.time()
            else "waiting"
        }

    @router.get("/devices")
    def devices(request: Request):
        admin(request)
        return pairings.tokens()

    @router.delete("/devices/{device_id}")
    def revoke(device_id: str, request: Request):
        admin(request)
        with pairings.db.connect() as c, c:
            c.execute("DELETE FROM lan_devices WHERE id=?", (device_id,))
        return {"status": "revoked"}

    return router
