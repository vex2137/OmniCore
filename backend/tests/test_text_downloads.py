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


def test_resume_after_integrity_failure_restarts_corrupt_partial(tmp_path):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        payload = synthetic_gguf()
        return httpx.Response(200, content=payload[:-1] + b"x" if attempts == 1 else payload)

    manager, source, payload = setup_downloads(tmp_path, handler)

    async def exercise():
        record = await manager.start(source, confirmed=True, expected_size=len(payload))
        await manager.tasks[record.id]
        assert manager.record(record.id).error_code == "download_integrity_error"
        await manager.resume(record.id)
        await manager.tasks[record.id]
        assert manager.record(record.id).state == "completed" and attempts == 2
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


def test_official_hf_cdn_is_allowed_without_forwarding_hf_token():
    def handler(request):
        if request.url.host == "huggingface.co":
            assert request.headers["authorization"] == "Bearer test-only-token"
            return httpx.Response(302, headers={"Location": "https://us.aws.cdn.hf.co/model.gguf"})
        assert request.url.host == "us.aws.cdn.hf.co"
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"controlled fixture")

    async def exercise():
        hub = HuggingFace(
            "test-only-token", client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        source = RemoteFile(
            repository="test/model", revision="a" * 40, filename="model.gguf", size_bytes=18
        )
        async with hub.stream(source, {}) as response:
            assert await response.aread() == b"controlled fixture"
        await hub.close()

    asyncio.run(exercise())


def test_hf_popular_search_uses_download_order():
    def handler(request):
        assert request.url.params["filter"] == "gguf"
        assert request.url.params["sort"] == "downloads"
        assert request.url.params["direction"] == "-1"
        assert "search" not in request.url.params
        return httpx.Response(200, json=[{"id": "test/popular"}])

    async def exercise():
        hub = HuggingFace(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        assert (await hub.search(""))[0]["repository"] == "test/popular"
        await hub.close()

    asyncio.run(exercise())


def test_duplicate_download_reuses_completed_file(tmp_path):
    manager, source, payload = setup_downloads(
        tmp_path,
        lambda request: httpx.Response(200, content=synthetic_gguf(), headers={"ETag": '"test"'}),
    )

    async def exercise():
        first = await manager.start(source, confirmed=True, expected_size=len(payload))
        await manager.tasks[first.id]
        second = await manager.start(source, confirmed=True, expected_size=len(payload))
        assert second.id == first.id
        assert len(manager.store.jobs("download")) == 1
        await manager.close()

    asyncio.run(exercise())


def test_hf_details_sort_and_readme_redirect_are_bounded():
    seen = []
    commit = "a" * 40

    def handler(request):
        seen.append(request)
        if request.url.path == "/api/models":
            assert request.url.params["sort"] == "likes"
            return httpx.Response(200, json=[{"id": "test/model"}])
        if request.url.path == "/api/models/test/model":
            return httpx.Response(
                200,
                json={
                    "sha": commit,
                    "downloads": 123,
                    "cardData": {"license": "mit"},
                    "gguf": {"total": 1000},
                    "config": {"architectures": ["TestArchitecture"]},
                    "tags": ["text-generation"],
                },
            )
        if request.url.path.endswith("/README.md"):
            return httpx.Response(302, headers={"location": "/safe-card"})
        if request.url.path == "/safe-card":
            return httpx.Response(200, text="# Model\n<script>bad()</script>")
        return httpx.Response(404)

    async def exercise():
        hub = HuggingFace(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        assert (await hub.search("model", "likes"))[0]["repository"] == "test/model"
        details = await hub.details("test/model")
        assert details["parameters"] == 1000 and details["architecture"] == "TestArchitecture"
        assert details["downloads"] == 123 and details["license"] == "mit"
        assert "# Model" in await hub.readme("test/model", commit)
        with pytest.raises(TextError, match="invalid_model_source"):
            await hub.readme("test/model", "main")
        await hub.close()

    asyncio.run(exercise())
    assert len(seen) == 4


def test_hf_readme_blocks_cross_origin_redirect():
    async def exercise():
        hub = HuggingFace(
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        302, headers={"location": "https://evil.example/card"}
                    )
                )
            )
        )
        with pytest.raises(TextError, match="download_redirect_denied"):
            await hub.readme("test/model", "a" * 40)
        await hub.close()

    asyncio.run(exercise())


def test_progress_and_automatic_import_after_verified_download(tmp_path):
    from omnicore.text.files import FilePolicy
    from omnicore.text.models import ModelManager

    payload = synthetic_gguf() + b"x" * (256 * 1024)
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield payload[: 128 * 1024]
            started.set()
            await release.wait()
            yield payload[128 * 1024 :]

    manager, source, _ = setup_downloads(
        tmp_path, lambda request: httpx.Response(200, stream=SlowStream())
    )
    source = source.model_copy(
        update={"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    )
    manager.import_model = ModelManager(manager.store, FilePolicy((manager.directory,))).import_gguf

    async def exercise():
        job = await manager.start(source, confirmed=True, expected_size=len(payload))
        await asyncio.wait_for(started.wait(), 2)
        running = manager.record(job.id)
        assert running.received_bytes == 128 * 1024 and running.speed_bytes_per_second > 0
        assert running.eta_seconds is not None
        release.set()
        await manager.tasks[job.id]
        done = manager.record(job.id)
        assert done.state == "completed" and done.integrity_verified
        assert done.model_id and not done.import_pending and not done.import_error
        assert manager.store.model(done.model_id).location == done.path
        assert done.speed_bytes_per_second is None and done.eta_seconds is None
        await manager.close()

    asyncio.run(exercise())


def test_import_error_keeps_download_and_can_retry(tmp_path):
    from omnicore.text.files import FilePolicy
    from omnicore.text.models import ModelManager

    manager, source, payload = setup_downloads(
        tmp_path, lambda request: httpx.Response(200, content=synthetic_gguf())
    )

    def failed(_):
        raise OSError("private details")

    manager.import_model = failed

    async def exercise():
        job = await manager.start(source, confirmed=True, expected_size=len(payload))
        await manager.tasks[job.id]
        record = manager.record(job.id)
        assert record.state == "completed" and record.import_error == "model_import_failed"
        assert (manager.directory / f"{job.id}.gguf").exists()
        manager.import_model = ModelManager(
            manager.store, FilePolicy((manager.directory,))
        ).import_gguf
        result = await manager.import_completed(record)
        assert result.model_id and not result.import_error
        old_model = result.model_id
        manager.store.delete_model(old_model)
        again = await manager.import_completed(result)
        assert again.model_id and again.model_id != old_model
        await manager.close()

    asyncio.run(exercise())


def test_interrupted_import_is_recovered_at_startup(tmp_path):
    from omnicore.text.files import FilePolicy
    from omnicore.text.models import ModelManager

    manager, source, payload = setup_downloads(
        tmp_path, lambda request: httpx.Response(200, content=synthetic_gguf())
    )

    async def download():
        job = await manager.start(source, confirmed=True, expected_size=len(payload))
        await manager.tasks[job.id]
        return manager.record(job.id)

    record = asyncio.run(download())
    record.import_pending = True
    manager.save(record)
    manager.import_model = ModelManager(manager.store, FilePolicy((manager.directory,))).import_gguf
    manager.initialize()
    recovered = manager.record(record.id)
    assert recovered.model_id and not recovered.import_pending
    asyncio.run(manager.close())


def test_failed_verification_never_imports(tmp_path):
    manager, source, payload = setup_downloads(
        tmp_path, lambda request: httpx.Response(200, content=synthetic_gguf()), digest="0" * 64
    )
    imported = []
    manager.import_model = imported.append

    async def exercise():
        job = await manager.start(source, confirmed=True, expected_size=len(payload))
        await manager.tasks[job.id]
        assert manager.record(job.id).state == "failed" and not imported
        await manager.close()

    asyncio.run(exercise())


def test_multipart_download_cannot_start(tmp_path):
    manager, source, payload = setup_downloads(tmp_path, lambda _: httpx.Response(200))
    source = source.model_copy(update={"filename": "model-00001-of-00002.gguf"})

    async def exercise():
        with pytest.raises(TextError, match="multipart_gguf_unsupported"):
            await manager.start(source, confirmed=True, expected_size=len(payload))
        assert manager.store.jobs("download") == []
        await manager.close()

    asyncio.run(exercise())
