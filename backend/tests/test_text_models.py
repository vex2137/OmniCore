import os
import struct

import pytest

from omnicore.database import Database
from omnicore.text.files import FilePolicy
from omnicore.text.models import ModelManager
from omnicore.text.store import TextStore
from omnicore.text.types import TextError


def synthetic_gguf():
    def string(value):
        data = value.encode()
        return struct.pack("<Q", len(data)) + data

    data = b"GGUF" + struct.pack("<IQQ", 3, 1, 3)
    for key, value in [
        ("general.architecture", "llama"),
        ("general.name", "Test fixture"),
        ("general.license", "test-only"),
    ]:
        data += string(key) + struct.pack("<I", 8) + string(value)
    data += string("test.weight") + struct.pack("<IQIQ", 1, 4, 0, 0)
    data += b"\0" * (-len(data) % 32) + struct.pack("<ffff", 0, 0, 0, 0)
    return data


@pytest.fixture
def catalog(tmp_path):
    db = Database(tmp_path / "data")
    db.initialize()
    store = TextStore(db)
    store.initialize()
    root = tmp_path / "models"
    root.mkdir()
    manager = ModelManager(store, FilePolicy((root,)))
    path = root / "test.gguf"
    path.write_bytes(synthetic_gguf())
    return manager, path


def test_import_reference_metadata_search_and_repeatability(catalog):
    manager, path = catalog
    record = manager.import_gguf(path)
    assert record.name == "Test fixture"
    assert record.metadata["architecture"] == "llama"
    assert record.compatibility == "unverified" and record.tested_backends == []
    assert record.license == "test-only" and record.location == str(path)
    assert manager.import_gguf(path).id == record.id
    assert manager.validated_reference(record.id) == path
    assert len(manager.store.models(query="fixture", backend="llama.cpp", format="GGUF")) == 1
    assert manager.store.models(backend="ollama") == []
    manager.store.initialize()
    assert manager.store.model(record.id) == record
    assert manager.store.db.version() == 1


@pytest.mark.parametrize(
    "bad",
    [
        b"",
        b"not GGUF",
        b"GGUF" + struct.pack("<I", 9),
        b"GGUF" + struct.pack("<IQQ", 3, 0, 0),
        synthetic_gguf()[:-1],
    ],
)
def test_invalid_gguf_is_not_registered(catalog, bad):
    manager, path = catalog
    path.write_bytes(bad)
    with pytest.raises(TextError):
        manager.import_gguf(path)
    assert manager.store.models() == []


def test_catalog_deletion_preserves_weights_and_file_deletion_requires_confirmation(catalog):
    manager, path = catalog
    record = manager.import_gguf(path)
    manager.remove(record.id)
    assert path.exists()
    record = manager.import_gguf(path)
    with pytest.raises(TextError, match="confirmation_required"):
        manager.remove(record.id, delete_file=True, confirm_name="wrong")
    assert path.exists()
    manager.remove(record.id, delete_file=True, confirm_name=record.name)
    assert not path.exists() and manager.store.models() == []


def test_changed_reference_is_rejected(catalog):
    manager, path = catalog
    record = manager.import_gguf(path)
    replacement = path.with_suffix(".replacement")
    replacement.write_bytes(path.read_bytes())
    replacement.replace(path)
    with pytest.raises(TextError, match="model_file_changed"):
        manager.validated_reference(record.id)
    with pytest.raises(TextError, match="model_file_changed"):
        manager.remove(record.id, delete_file=True, confirm_name=record.name)


def test_path_policy_denies_traversal_symlinks_and_nonregular_files(catalog, tmp_path):
    manager, path = catalog
    link = path.parent / "linked.gguf"
    link.symlink_to(path)
    parent_link = tmp_path / "linked_directory"
    parent_link.symlink_to(path.parent, target_is_directory=True)
    outside = tmp_path / "outside.gguf"
    outside.write_bytes(synthetic_gguf())
    for candidate in [
        link,
        path.parent / ".." / "models" / path.name,
        outside,
        parent_link / path.name,
        path.parent,
        path.relative_to(path.anchor),
    ]:
        with pytest.raises(TextError, match="invalid_path"):
            manager.import_gguf(candidate)
    fifo = path.parent / "fifo.gguf"
    os.mkfifo(fifo)
    with pytest.raises(TextError, match="invalid_path"):
        manager.import_gguf(fifo)


def test_newer_text_schema_is_rejected_without_core_changes(catalog):
    manager, path = catalog
    record = manager.import_gguf(path)
    with manager.store.db.connect() as connection, connection:
        connection.execute("UPDATE text_schema SET version=99")
    with pytest.raises(RuntimeError, match="newer"):
        manager.store.initialize()
    assert manager.store.model(record.id) == record
    assert manager.store.db.version() == 1


def test_multipart_gguf_is_not_imported_as_a_complete_model(catalog):
    manager, path = catalog
    shard = path.with_name("model-00001-of-00002.gguf")
    shard.write_bytes(path.read_bytes())
    with pytest.raises(TextError, match="multipart_gguf_unsupported"):
        manager.import_gguf(shard)
    assert manager.store.models() == []


def test_embedded_multipart_metadata_is_rejected_even_when_renamed(catalog):
    manager, path = catalog
    data = synthetic_gguf()
    key = b"split.count"
    header = bytearray(data[:24])
    struct.pack_into("<Q", header, 16, 4)
    entry = struct.pack("<Q", len(key)) + key + struct.pack("<II", 4, 2)
    path.write_bytes(bytes(header) + entry + data[24:])
    with pytest.raises(TextError, match="multipart_gguf_unsupported"):
        manager.import_gguf(path)


def test_explicit_reimport_revalidates_without_losing_catalog_identity(catalog):
    manager, path = catalog
    original = manager.import_gguf(path)
    original.parameters = {"temperature": 0.5}
    original.metadata["desktop_context"] = {"mode": "manual", "manual_tokens": 4096}
    manager.store.update_model(original)
    replacement = path.with_name("replacement.gguf")
    replacement.write_bytes(synthetic_gguf())
    os.replace(replacement, path)
    with pytest.raises(TextError, match="model_file_changed"):
        manager.validated_reference(original.id)
    with pytest.raises(TextError, match="model_file_changed"):
        manager.import_gguf(path)
    refreshed = manager.import_gguf(path, refresh_existing=True)
    assert refreshed.id == original.id
    assert refreshed.parameters == original.parameters
    assert refreshed.metadata["desktop_context"] == original.metadata["desktop_context"]
    assert refreshed.compatibility == "unverified"
    assert manager.validated_reference(original.id) == path
    assert len(manager.store.models()) == 1 and path.is_file()


def test_in_place_same_size_change_is_not_silently_accepted(catalog):
    manager, path = catalog
    record = manager.import_gguf(path)
    content = bytearray(path.read_bytes())
    content[-1] ^= 1
    path.write_bytes(content)
    original = record.metadata["file_mtime_ns"]
    os.utime(path, ns=(original, original + 1_000_000))
    with pytest.raises(TextError, match="model_file_changed"):
        manager.validated_reference(record.id)
    path.write_bytes(b"invalid GGUF")
    with pytest.raises(TextError):
        manager.import_gguf(path, refresh_existing=True)
    assert manager.store.model(record.id).metadata["file_mtime_ns"] == original


def test_automatic_recovery_on_device_drift_mtime_touch_and_relocation(catalog):
    manager, path = catalog
    record = manager.import_gguf(path)
    with manager.store.db.connect() as connection, connection:
        connection.execute("UPDATE text_models SET device=? WHERE id=?", (-99, record.id))
    assert manager.store.model_identity(record.id)[0] == -99
    assert manager.validated_reference(record.id) == path
    stat_info = os.stat(path)
    assert manager.store.model_identity(record.id) == (stat_info.st_dev, stat_info.st_ino)

    original_mtime = os.stat(path).st_mtime_ns
    os.utime(path, ns=(original_mtime, original_mtime + 2_000_000))
    assert manager.validated_reference(record.id) == path
    assert manager.store.model(record.id).metadata["file_mtime_ns"] == os.stat(path).st_mtime_ns

    second_root = path.parent.parent / "moved"
    second_root.mkdir()
    moved = second_root / "relocated.gguf"
    path.rename(moved)
    extra = second_root / "extra.gguf"
    extra.write_bytes(synthetic_gguf().replace(b"Test fixture", b"Extra model!"))
    manager.policy = FilePolicy((path.parent, second_root, path.parent.parent / "default"))

    records = manager.scan_and_recover(import_all_roots=True)
    assert len(records) == 2
    refreshed = manager.store.model(record.id)
    assert refreshed.location == str(moved.absolute())
    assert refreshed.metadata["file_status"] == "available"
    assert any(item.name == "Extra model!" for item in records)


def test_file_policy_distinguishes_unauthorized_missing_and_symlink(catalog, tmp_path):
    from omnicore.text.files import FilePolicy
    from omnicore.text.types import TextError

    manager, path = catalog

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_model = outside_dir / "external.gguf"
    outside_model.write_bytes(synthetic_gguf())

    assert not manager.policy.is_authorized(outside_model)
    with pytest.raises(TextError) as exc_validate:
        manager.policy.validate(outside_model, registered=True)
    assert exc_validate.value.code == "model_directory_unauthorized"
    assert exc_validate.value.status == 403

    missing_inside = path.parent / "removed.gguf"
    with pytest.raises(TextError) as exc_missing:
        with manager.policy.open(missing_inside, registered=True):
            pass
    assert exc_missing.value.code == "model_file_missing"
    assert exc_missing.value.status == 404

    symlink_inside = path.parent / "link.gguf"
    symlink_inside.symlink_to(outside_model)
    broken_symlink = path.parent / "broken.gguf"
    broken_symlink.symlink_to(path.parent / "nonexistent.gguf")
    outside_link = outside_dir / "outside-link.gguf"
    outside_link.symlink_to(outside_model)
    for bad in (symlink_inside, broken_symlink):
        with pytest.raises(TextError) as exc_sym_o:
            with manager.policy.open(bad, registered=True):
                pass
        assert exc_sym_o.value.code == "invalid_path"
        assert exc_sym_o.value.status == 403

    with pytest.raises(TextError) as exc_out_link:
        with manager.policy.open(outside_link, registered=True):
            pass
    assert exc_out_link.value.code == "model_directory_unauthorized"
    assert exc_out_link.value.status == 403

    assert isinstance(manager.policy, FilePolicy)


def test_scan_and_recover_marks_unauthorized_missing_and_symlink(catalog, tmp_path):
    from omnicore.text.files import FilePolicy

    manager, path = catalog
    model_id = manager.scan_and_recover(import_all_roots=True)[0].id

    empty_root = tmp_path / "empty_root"
    empty_root.mkdir()
    manager.policy = FilePolicy((empty_root,))
    unauthorized = manager.scan_and_recover()
    assert len(unauthorized) == 1
    assert unauthorized[0].id == model_id
    assert unauthorized[0].metadata["file_status"] == "unauthorized"

    manager.policy = FilePolicy((path.parent,))
    path.unlink()
    missing = manager.scan_and_recover()
    assert missing[0].metadata["file_status"] == "missing"

    real_outside = tmp_path / "real-outside.gguf"
    real_outside.write_bytes(synthetic_gguf())
    path.symlink_to(real_outside)
    invalid = manager.scan_and_recover()
    assert invalid[0].metadata["file_status"] == "invalid_path"


def test_gguf_parses_lfm3_kv_array_and_avoids_kv_cache_overestimate(tmp_path):
    import struct

    from omnicore.text.gguf import read_gguf
    from omnicore.text.offload import (
        estimate_auto_gpu_layers,
        estimate_kv_bytes_per_token,
        inspect_gguf_layout,
    )

    def pack_str(val: str) -> bytes:
        raw = val.encode("utf-8")
        return struct.pack("<Q", len(raw)) + raw

    kv_heads = [8 if i in {2, 6, 10, 14, 18, 22} else 0 for i in range(24)]
    entries = [
        ("general.architecture", 8, pack_str("lfm3")),
        ("general.alignment", 4, struct.pack("<I", 32)),
        ("lfm3.block_count", 4, struct.pack("<I", 24)),
        ("lfm3.embedding_length", 4, struct.pack("<I", 2048)),
        ("lfm3.attention.head_count", 4, struct.pack("<I", 32)),
        (
            "lfm3.attention.head_count_kv",
            9,
            struct.pack("<IQ", 4, len(kv_heads)) + b"".join(struct.pack("<I", v) for v in kv_heads),
        ),
        ("lfm3.attention.key_length", 4, struct.pack("<I", 64)),
        ("lfm3.attention.value_length", 4, struct.pack("<I", 64)),
        ("lfm3.attention.sliding_window", 4, struct.pack("<I", 512)),
        ("lfm3.shortconv.l_cache", 4, struct.pack("<I", 3)),
        ("lfm3.context_length", 4, struct.pack("<I", 32768)),
    ]
    buf = bytearray(b"GGUF")
    buf += struct.pack("<IQQ", 3, 1, len(entries))
    for key, kind, payload in entries:
        buf += pack_str(key)
        buf += struct.pack("<I", kind)
        buf += payload
    buf += pack_str("w")
    buf += struct.pack("<IQ", 1, 1)
    buf += struct.pack("<IQ", 0, 0)
    buf += b"\x00" * ((-len(buf)) % 32) + b"\x00" * 32

    model_path = tmp_path / "lfm3.gguf"
    model_path.write_bytes(bytes(buf))
    with model_path.open("rb") as handle:
        parsed = read_gguf(handle)

    meta = parsed["metadata"]
    assert meta["lfm3.attention.head_count_kv"] == kv_heads
    assert meta["lfm3.attention.sliding_window"] == 512
    assert meta["lfm3.shortconv.l_cache"] == 3

    layout = inspect_gguf_layout(model_path)
    assert layout is not None
    layout["file_size_bytes"] = int(1.2 * 1024**3)
    assert layout["kv_attention_layers"] == 6
    assert layout["sliding_window"] == 512
    assert layout["shortconv_l_cache"] == 3

    hybrid_kv = estimate_kv_bytes_per_token(layout)
    uniform_kv = estimate_kv_bytes_per_token(
        {
            "file_size_bytes": int(1.2 * 1024**3),
            "architecture": "lfm3",
            "block_count": 24,
            "head_count_kv": 8,
            "key_length": 64,
            "value_length": 64,
        }
    )
    assert hybrid_kv < uniform_kv // 3

    layers, total, reason = estimate_auto_gpu_layers(
        model_path,
        context_size=8192,
        fallback_layers=99,
        free_vram_bytes=3 * 1024**3,
        layout=layout,
    )
    assert total == 25
    assert layers == 25
    assert reason == "fits_in_vram"

    tight_layers, _total, _reason = estimate_auto_gpu_layers(
        model_path,
        context_size=8192,
        fallback_layers=99,
        free_vram_bytes=2 * 1024**3,
        layout=layout,
    )
    naive_layers, _naive_total, _naive_reason = estimate_auto_gpu_layers(
        model_path,
        context_size=8192,
        fallback_layers=99,
        free_vram_bytes=2 * 1024**3,
        layout={
            "file_size_bytes": int(1.2 * 1024**3),
            "architecture": "lfm3",
            "block_count": 24,
            "head_count_kv": 8,
            "key_length": 64,
            "value_length": 64,
        },
    )
    assert tight_layers > naive_layers
