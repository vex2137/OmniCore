import asyncio
import hashlib

import httpx
import pytest
from test_text_models import synthetic_gguf

from omnicore.database import Database
from omnicore.text.downloads import DownloadManager, HuggingFace, RemoteFile
from omnicore.text.store import TextStore
from omnicore.text.types import TextError


def setup_downloads(tmp_path, handler, digest=None):
    payload = synthetic_gguf()
    db = Database(tmp_path / "data")
    db.initialize()
    store = TextStore(db)
    store.initialize()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    hub = HuggingFace(client=client)
    manager = DownloadManager(store, hub, tmp_path / "downloads")
    manager.initialize()
    source = RemoteFile(
        repository="test/model",
        revision="a" * 40,
        filename="test.gguf",
        size_bytes=len(payload),
        sha256=digest or hashlib.sha256(payload).hexdigest(),
    )
    return manager, source, payload


def test_hf_search_and_immutable_file_metadata():
    def handler(request):
        assert request.headers["authorization"] == "Bearer test-only-not-a-real-token"
        if request.url.path == "/api/models":
            return httpx.Response(200, json=[{"id": "test/model", "cardData": {"license": "mit"}}])
        return httpx.Response(
            200,
            json={
                "sha": "a" * 40,
                "cardData": {"license": "mit"},
                "siblings": [
                    {"rfilename": "test.gguf", "size": 10, "lfs": {"sha256": "b" * 64}},
                    {"rfilename": "code.py"},
                ],
            },
        )

    async def exercise():
        hub = HuggingFace(
            "test-only-not-a-real-token",
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        assert (await hub.search("test"))[0]["repository"] == "test/model"
        files = await hub.files("test/model")
        assert len(files) == 1 and files[0].revision == "a" * 40
        assert files[0].license == "mit"
        await hub.close()

    asyncio.run(exercise())


def test_confirmed_download_checksum_atomic_finish_and_no_code_execution(tmp_path):
    manager, source, payload = setup_downloads(
        tmp_path,
        lambda request: httpx.Response(200, content=synthetic_gguf(), headers={"ETag": '"test"'}),
    )

    async def exercise():
        with pytest.raises(TextError, match="confirmation_required"):
            await manager.start(source, confirmed=False, expected_size=len(payload))
        record = await manager.start(source, confirmed=True, expected_size=len(payload))
        await manager.tasks[record.id]
        result = manager.record(record.id)
        assert result.state == "completed" and result.percent == 100
        assert result.integrity_verified
        assert (manager.directory / f"{record.id}.gguf").read_bytes() == payload
        assert not (manager.directory / f"{record.id}.part").exists()
        await manager.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("range_supported", [True, False])
def test_resume_partial_bytes_and_restart_when_range_ignored(tmp_path, range_supported):
    def handler(request):
        assert request.headers["range"] == "bytes=32-"
        payload = synthetic_gguf()
        return httpx.Response(
            206 if range_supported else 200,
            headers={"Content-Range": f"bytes 32-{len(payload) - 1}/{len(payload)}"},
            content=payload[32:] if range_supported else payload,
        )

    manager, source, payload = setup_downloads(tmp_path, handler)

    async def exercise():
        # Persist a failed transfer exactly as a previous interrupted process would.
        record = await manager.start(source, confirmed=True, expected_size=len(payload))
        await manager.cancel(record.id)
        (manager.directory / f"{record.id}.part").write_bytes(payload[:32])
        await manager.resume(record.id)
        await manager.tasks[record.id]
        assert manager.record(record.id).state == "completed"
        assert (manager.directory / f"{record.id}.gguf").read_bytes() == payload
        await manager.close()

    asyncio.run(exercise())


def test_cancellation_keeps_private_partial_and_does_not_publish_final(tmp_path):
    started = None

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            yield synthetic_gguf()[:32]
            await asyncio.Event().wait()

    manager, source, payload = setup_downloads(
        tmp_path, lambda request: httpx.Response(200, stream=SlowStream())
    )

    async def exercise():
        nonlocal started
        started = asyncio.Event()
        record = await manager.start(source, confirmed=True, expected_size=len(payload))
        await asyncio.wait_for(started.wait(), 2)
        await manager.cancel(record.id)
        assert manager.record(record.id).state == "cancelled"
        assert not (manager.directory / f"{record.id}.gguf").exists()
        assert (manager.directory / f"{record.id}.part").exists()
        await manager.close()

    asyncio.run(exercise())


def test_bad_checksum_fails_without_final_file(tmp_path):
    manager, source, payload = setup_downloads(
        tmp_path, lambda request: httpx.Response(200, content=synthetic_gguf()), digest="0" * 64
    )

    async def exercise():
        record = await manager.start(source, confirmed=True, expected_size=len(payload))
        await manager.tasks[record.id]
        assert manager.record(record.id).error_code == "download_integrity_error"
        assert not (manager.directory / f"{record.id}.gguf").exists()
        await manager.close()

    asyncio.run(exercise())


def test_redirect_cannot_exfiltrate_token_or_access_local_network():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    async def exercise():
        hub = HuggingFace(
            "test-token", client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        source = RemoteFile(
            repository="test/model", revision="a" * 40, filename="test.gguf", size_bytes=10
        )
        with pytest.raises(TextError, match="download_redirect_denied"):
            async with hub.stream(source, {}) as response:
                await response.aread()
        assert len(urls) == 1
        await hub.close()

    asyncio.run(exercise())
