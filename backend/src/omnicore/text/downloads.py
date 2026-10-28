"""Confirmed, resumable GGUF downloads; no repository code is executed."""

import asyncio
import hashlib
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urljoin, urlsplit

import httpx
from pydantic import Field

from omnicore.schemas import WireModel
from omnicore.text.files import FilePolicy
from omnicore.text.gguf import read_gguf
from omnicore.text.store import TextStore, timestamp
from omnicore.text.types import TextError


class RemoteFile(WireModel):
    repository: str
    revision: str
    filename: str
    size_bytes: int = Field(gt=0)
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    license: str | None = None


class DownloadRecord(WireModel):
    id: str
    source: RemoteFile
    state: str = "queued"
    received_bytes: int = 0
    percent: float = 0
    path: str | None = None
    error_code: str | None = None
    etag: str | None = None
    integrity_verified: bool = False
    created_at: str


def validate_source(repository, filename=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository):
        raise TextError("invalid_model_source", 422)
    if filename is not None:
        path = PurePosixPath(filename)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in filename
            or not filename.lower().endswith(".gguf")
        ):
            raise TextError("invalid_model_source", 422)


class HuggingFace:
    def __init__(self, token: str | None = None, *, client=None, base_url="https://huggingface.co"):
        self.base_url = base_url
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=10), follow_redirects=False
        )
        self._token = token
        self.allowed_hosts = {
            urlsplit(base_url).hostname,
            "cdn-lfs.huggingface.co",
            "cdn-lfs-us-1.huggingface.co",
            "cas-bridge.xethub.hf.co",
        }

    def headers(self, url):
        if self._token and urlsplit(url).hostname == urlsplit(self.base_url).hostname:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    async def _json(self, path: str, params=None):
        url = self.base_url + path
        try:
            async with self.client.stream(
                "GET", url, params=params, headers=self.headers(url)
            ) as r:
                r.raise_for_status()
                data = bytearray()
                async for chunk in r.aiter_bytes():
                    if len(data) + len(chunk) > 8 * 1024 * 1024:
                        raise TextError("remote_metadata_too_large", 502)
                    data.extend(chunk)
                return json.loads(data)
        except (httpx.HTTPError, ValueError):
            raise TextError("download_network_error", 502) from None

    async def search(self, query: str):
        result = await self._json(
            "/api/models", {"search": query, "filter": "gguf", "limit": 20, "full": "true"}
        )
        return [
            {"repository": item.get("id"), "license": (item.get("cardData") or {}).get("license")}
            for item in result
            if isinstance(item, dict)
        ]

    async def files(self, repository: str, revision="main") -> list[RemoteFile]:
        validate_source(repository)
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", revision):
            raise TextError("invalid_model_source", 422)
        result = await self._json(
            f"/api/models/{repository}/revision/{quote(revision, safe='')}", {"blobs": "true"}
        )
        commit = result.get("sha", "")
        if not re.fullmatch(r"[a-fA-F0-9]{40}", commit):
            raise TextError("invalid_model_source", 502)
        license = (result.get("cardData") or {}).get("license")
        records = []
        for file in result.get("siblings", []):
            name = file.get("rfilename", "")
            if not name.lower().endswith(".gguf"):
                continue
            validate_source(repository, name)
            lfs = file.get("lfs") or {}
            size = lfs.get("size") or file.get("size")
            digest = lfs.get("sha256") or lfs.get("oid")
            if isinstance(digest, str):
                digest = digest.removeprefix("sha256:")
                if not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
                    digest = None
            if isinstance(size, int) and size > 0:
                records.append(
                    RemoteFile(
                        repository=repository,
                        revision=commit,
                        filename=name,
                        size_bytes=size,
                        sha256=digest,
                        license=license if isinstance(license, str) else None,
                    )
                )
        return records

    @asynccontextmanager
    async def stream(self, source: RemoteFile, headers):
        validate_source(source.repository, source.filename)
        prefix = f"{self.base_url}/{source.repository}/resolve/{source.revision}"
        url = f"{prefix}/{quote(source.filename, safe='/')}"
        for _ in range(6):
            parsed = urlsplit(url)
            if parsed.hostname not in self.allowed_hosts or parsed.username or parsed.password:
                raise TextError("download_redirect_denied", 502)
            if parsed.scheme != "https" and parsed.hostname != urlsplit(self.base_url).hostname:
                raise TextError("download_redirect_denied", 502)
            async with self.client.stream(
                "GET", url, headers={**headers, **self.headers(url)}
            ) as r:
                if r.is_redirect:
                    url = urljoin(url, r.headers.get("location", ""))
                    continue
                yield r
                return
        raise TextError("download_redirect_denied", 502)

    async def close(self):
        await self.client.aclose()


class DownloadManager:
    def __init__(self, store: TextStore, hub: HuggingFace, directory: Path):
        self.store, self.hub, self.directory = store, hub, directory
        self.tasks: dict[str, asyncio.Task] = {}
        self.semaphore = asyncio.Semaphore(1)

    def initialize(self):
        if self.directory.is_symlink():
            raise TextError("invalid_path", 403)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        for item in self.store.jobs("download"):
            if item["state"] in {"queued", "running"}:
                item.update(state="interrupted", error_code="backend_restarted")
                self.store.save_job("download", item["id"], item)

    def record(self, job_id):
        return DownloadRecord.model_validate(self.store.job("download", job_id))

    def save(self, record):
        self.store.save_job("download", record.id, record.model_dump(mode="json"))

    async def start(self, source: RemoteFile, *, confirmed: bool, expected_size: int):
        if not confirmed or expected_size != source.size_bytes:
            raise TextError("confirmation_required", 409)
        if len(self.tasks) >= 32:
            raise TextError("queue_full", 429)
        record = DownloadRecord(id=uuid.uuid4().hex, source=source, created_at=timestamp())
        self.save(record)
        self.tasks[record.id] = asyncio.create_task(self._run(record.id))
        return record

    async def resume(self, job_id):
        record = self.record(job_id)
        if record.state not in {"cancelled", "failed", "interrupted"}:
            raise TextError("invalid_task_state", 409)
        record.state, record.error_code = "queued", None
        self.save(record)
        self.tasks[job_id] = asyncio.create_task(self._run(job_id))
        return record

    async def _run(self, job_id):
        record = self.record(job_id)
        part = self.directory / f"{job_id}.part"
        final = self.directory / f"{job_id}.gguf"
        try:
            async with self.semaphore:
                record.state = "running"
                self.save(record)
                descriptor = os.open(part, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                with os.fdopen(descriptor, "r+b") as output:
                    offset = output.seek(0, 2)
                    if offset > record.source.size_bytes:
                        raise TextError("download_integrity_error", 422)
                    if offset < record.source.size_bytes:
                        headers = {"Accept-Encoding": "identity"}
                        if offset:
                            headers["Range"] = f"bytes={offset}-"
                            if record.etag:
                                headers["If-Range"] = record.etag
                        async with self.hub.stream(record.source, headers) as response:
                            response.raise_for_status()
                            if response.status_code == 206:
                                match = re.fullmatch(
                                    r"bytes (\d+)-(\d+)/(\d+)",
                                    response.headers.get("Content-Range", ""),
                                )
                                if (
                                    not match
                                    or int(match[1]) != offset
                                    or int(match[2]) != record.source.size_bytes - 1
                                    or int(match[3]) != record.source.size_bytes
                                ):
                                    raise TextError("download_integrity_error", 502)
                            elif response.status_code == 200:
                                output.seek(0)
                                output.truncate()
                                offset = 0
                            else:
                                raise TextError("download_network_error", 502)
                            record.etag = response.headers.get("ETag")
                            async for chunk in response.aiter_bytes(128 * 1024):
                                if offset + len(chunk) > record.source.size_bytes:
                                    raise TextError("download_integrity_error", 422)
                                await asyncio.to_thread(output.write, chunk)
                                offset += len(chunk)
                                record.received_bytes = offset
                                record.percent = 100 * offset / record.source.size_bytes
                                self.save(record)
                    await asyncio.to_thread(output.flush)
                    await asyncio.to_thread(os.fsync, output.fileno())
                if part.stat().st_size != record.source.size_bytes:
                    raise TextError("download_integrity_error", 422)

                def verify():
                    with FilePolicy((self.directory,)).open(part) as stream:
                        digest = hashlib.file_digest(stream, "sha256").hexdigest()
                        if record.source.sha256 and digest.lower() != record.source.sha256.lower():
                            raise TextError("download_integrity_error", 422)
                        stream.seek(0)
                        read_gguf(stream)

                await asyncio.to_thread(verify)
                os.replace(part, final)
                record.state = "completed"
                record.path = str(final)
                record.integrity_verified = bool(record.source.sha256)
                record.received_bytes, record.percent = record.source.size_bytes, 100
                self.save(record)
        except asyncio.CancelledError:
            record.state, record.error_code = "cancelled", None
            self.save(record)
            raise
        except TextError as exc:
            record.state, record.error_code = "failed", exc.code
            self.save(record)
        except (OSError, httpx.HTTPError, ValueError):
            record.state, record.error_code = "failed", "download_network_error"
            self.save(record)
        finally:
            self.tasks.pop(job_id, None)

    async def cancel(self, job_id):
        record = self.record(job_id)
        if record.state in {"completed", "cancelled", "failed", "interrupted"}:
            return record
        record.state = "cancelled"
        self.save(record)
        task = self.tasks.get(job_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return self.record(job_id)

    async def close(self):
        for job_id in list(self.tasks):
            await self.cancel(job_id)
        await self.hub.close()
