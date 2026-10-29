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
