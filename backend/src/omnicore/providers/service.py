"""Provider configuration, OS-secret references and one TextEngine for remote models."""

import asyncio
import ipaddress
import json
import re
import uuid
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field, SecretStr

from omnicore.providers import protocols
from omnicore.providers.vault import SystemVault
from omnicore.schemas import BackendInfo, Capability, WireModel
from omnicore.text.reasoning import normalize_stream
from omnicore.text.types import TextError

ProviderKind = Literal["openai", "anthropic", "gemini", "openrouter", "custom"]


class ProviderInput(WireModel):
    kind: ProviderKind
    label: str = Field(default="", max_length=80, pattern=r"^[^\x00-\x1f\x7f]*$")
    endpoint: str = Field(default="", max_length=2048)
    api_key: SecretStr | None = Field(default=None, repr=False)
    clear_key: bool = False
    sampling: bool = False


class ProviderInfo(WireModel):
    id: str
    kind: ProviderKind
    label: str
    endpoint: str
    key_present: bool
    sampling: bool
    execution: Literal["backend"] = "backend"
    secret_store: Literal["linux-secret-service"] = "linux-secret-service"  # noqa: S105 — store type


class CloudModel(WireModel):
    model_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]*$")
    confirmed_external: bool = False


def endpoint_for(kind, value):
    if kind != "custom":
        if value and value.rstrip("/") != protocols.ENDPOINTS[kind]:
            raise TextError("provider_endpoint_invalid", 422)
        return protocols.ENDPOINTS[kind]
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not 1 <= (parsed.port or 443) <= 65535
            or not re.fullmatch(r"[A-Za-z0-9.-]+", parsed.hostname)
            or parsed.hostname == "localhost"
            or parsed.hostname.endswith((".localhost", ".local", ".internal"))
        ):
            raise ValueError
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError
    except ValueError:
        raise TextError("provider_endpoint_invalid", 422) from None
    return value.rstrip("/")


class Providers:
    def __init__(self, store, *, vault=None, transport=None, authenticated=True):
        self.store = store
        self.vault = vault or SystemVault(store.db.path.parent)
        self.transport = transport
        self.authenticated = authenticated

    def initialize(self):
        with self.store.db.connect() as c, c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS ai_providers "
                "(id TEXT PRIMARY KEY, record TEXT NOT NULL)"
            )
            c.execute("CREATE TABLE IF NOT EXISTS ai_retired_keys (reference TEXT PRIMARY KEY)")

    def raw(self, provider_id):
        with self.store.db.connect() as c:
            row = c.execute("SELECT record FROM ai_providers WHERE id=?", (provider_id,)).fetchone()
        if not row:
            raise TextError("provider_not_found", 404)
        return json.loads(row[0])

    def info(self, record):
        return ProviderInfo(
            **{key: record[key] for key in ("id", "kind", "label", "endpoint", "sampling")},
            key_present=bool(record.get("key_ref")),
        )

    def list(self):
        with self.store.db.connect() as c:
            return [
                self.info(json.loads(row[0]))
                for row in c.execute("SELECT record FROM ai_providers ORDER BY rowid")
            ]

    def cleanup(self):
        with self.store.db.connect() as c:
            references = [r[0] for r in c.execute("SELECT reference FROM ai_retired_keys")]
        for ref in references:
            try:
                self.vault.delete(ref)
            except TextError:
                continue
            with self.store.db.connect() as c, c:
                c.execute("DELETE FROM ai_retired_keys WHERE reference=?", (ref,))

    def save(self, body, provider_id=None):
        old = self.raw(provider_id) if provider_id else {}
        endpoint = endpoint_for(body.kind, body.endpoint)
        if body.api_key and body.clear_key:
            raise TextError("validation_error", 422)
        if (
            old.get("key_ref")
            and (endpoint != old["endpoint"] or body.kind != old["kind"])
            and body.api_key is None
        ):
            raise TextError("provider_key_reentry_required", 422)
        record = {
            "id": provider_id or uuid.uuid4().hex,
            "kind": body.kind,
            "label": body.label.strip() or body.kind,
            "endpoint": endpoint,
            "sampling": body.sampling,
            "key_ref": old.get("key_ref"),
        }
        created_ref = None
        if body.api_key is not None:
            key = body.api_key.get_secret_value()
            if not 1 <= len(key) <= 8192 or any(ord(ch) < 33 or ord(ch) > 126 for ch in key):
                raise TextError("provider_key_invalid", 422)
            created_ref = uuid.uuid4().hex
            self.vault.put(created_ref, key)
            record["key_ref"] = created_ref
        elif body.clear_key:
            if record["key_ref"]:
                self.vault.delete(record["key_ref"])
            record["key_ref"] = None
        try:
            with self.store.db.connect() as c, c:
                c.execute(
                    "INSERT INTO ai_providers VALUES(?,?) ON CONFLICT(id) "
                    "DO UPDATE SET record=excluded.record",
                    (record["id"], json.dumps(record)),
                )
                if old.get("key_ref") and old["key_ref"] != record["key_ref"]:
                    c.execute("INSERT OR IGNORE INTO ai_retired_keys VALUES(?)", (old["key_ref"],))
        except Exception:
            if created_ref:
                self.vault.delete(created_ref)
            raise
        self.cleanup()
        return self.info(record)

    def delete(self, provider_id):
        record = self.raw(provider_id)
        if record.get("key_ref"):
            self.vault.delete(record["key_ref"])
        with self.store.db.connect() as c, c:
            c.execute("DELETE FROM ai_providers WHERE id=?", (provider_id,))
        for model in self.store.models(backend="cloud"):
            if model.metadata.get("provider_id") == provider_id:
                self.store.delete_model(model.id)
        self.cleanup()

    def client(self, record):
        return httpx.AsyncClient(
            base_url=record["endpoint"] + "/",
            transport=self.transport,
            follow_redirects=False,
            timeout=httpx.Timeout(90, connect=10),
            trust_env=True,
        )

    async def request_headers(self, record):
        key = (
            await asyncio.to_thread(self.vault.get, record["key_ref"])
            if record.get("key_ref")
            else ""
        )
        if not key and record["kind"] != "custom":
            raise TextError("provider_key_missing", 409)
        return protocols.headers(record["kind"], key)

    async def models(self, provider_id):
        record = await asyncio.to_thread(self.raw, provider_id)
        headers = await self.request_headers(record)
        items = []
        cursor = None
        try:
            async with self.client(record) as client:
                for _ in range(5):
                    params = (
                        {"pageSize": 100}
                        if record["kind"] == "gemini"
                        else {"limit": 100}
                        if record["kind"] == "anthropic"
                        else {}
                    )
                    if cursor:
                        params["pageToken" if record["kind"] == "gemini" else "after_id"] = cursor
                    async with client.stream(
                        "GET", "models", headers=headers, params=params
                    ) as response:
                        if not response.is_success:
                            raise protocols.status_error(response.status_code)
                        data = await protocols.read_json(response)
                    key = "models" if record["kind"] == "gemini" else "data"
                    if key not in data or not isinstance(data[key], list):
                        raise TextError("provider_response_invalid", 502)
                    for model in data[key][:1000]:
                        if not isinstance(model, dict):
                            raise TextError("provider_response_invalid", 502)
                        if record["kind"] == "gemini" and "generateContent" not in model.get(
                            "supportedGenerationMethods", []
                        ):
                            continue
                        identity = model.get("name" if record["kind"] == "gemini" else "id")
                        if isinstance(identity, str):
                            try:
                                items.append(CloudModel(model_id=identity).model_id)
                            except ValueError:
                                continue
                    cursor = (
                        data.get("nextPageToken")
                        if record["kind"] == "gemini"
                        else data.get("last_id")
                        if data.get("has_more")
                        else None
                    )
                    if not cursor:
                        break
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise TextError("provider_connection_failed", 502) from None
        return list(dict.fromkeys(items))[:1000]

    def add_model(self, provider_id, model_id):
        provider = self.raw(provider_id)
        return self.store.add_model(
            backend="cloud",
            location=provider_id + ":" + model_id,
            name=(provider["label"] + " · " + model_id)[:256],
            size_bytes=0,
            format="API",
            capabilities=["text-generation"],
            metadata={
                "provider_id": provider_id,
                "provider": provider["kind"],
                "remote_model": model_id,
                "external": True,
            },
        )


class CloudEngine:
    id = "cloud"

    def __init__(self, providers):
        self.providers = providers
        self.clients = set()

    async def probe(self):
        records = await asyncio.to_thread(self.providers.list)
        return BackendInfo(
            id="cloud",
            version="provider APIs",
            available=bool(records),
            capabilities=[Capability.TEXT],
        )

    async def stream(self, model, messages, parameters):
        async for chunk in normalize_stream(self._stream(model, messages, parameters)):
            yield chunk

    async def _stream(self, model, messages, parameters):
        if not self.providers.authenticated:
            raise TextError("provider_requires_server_auth", 403)
        provider_id, _, model_id = model.partition(":")
        record = await asyncio.to_thread(self.providers.raw, provider_id)
        headers = await self.providers.request_headers(record)
        path, query, body = protocols.generation(
            record["kind"], model_id, messages, parameters, record["sampling"]
        )
        client = self.providers.client(record)
        self.clients.add(client)
        try:
            async with (
                client,
                client.stream("POST", path, params=query, headers=headers, json=body) as response,
            ):
                if not response.is_success:
                    raise protocols.status_error(response.status_code)
                if not response.headers.get("content-type", "").startswith("text/event-stream"):
                    raise TextError("provider_response_invalid", 502)
                from omnicore.text.types import TextChunk

                yield TextChunk(execution_provider=record["kind"], execution_model=model_id)
                async for event in protocols.events(response):
                    for chunk in protocols.chunks(record["kind"], event):
                        yield chunk
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise TextError("provider_connection_failed", 502) from None
        finally:
            self.clients.discard(client)

    async def unload(self, model=None):
        for client in list(self.clients):
            await client.aclose()

    async def stop(self):
        await self.unload()
