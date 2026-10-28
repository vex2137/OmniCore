import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from omnicore.adapters import AdapterRegistry
from omnicore.schemas import BackendInfo, ModelMetadata

ROOT = Path(__file__).resolve().parents[2]


def test_exported_contracts_match_code_and_are_valid_schemas():
    spec = importlib.util.spec_from_file_location(
        "export_contracts", ROOT / "scripts/export_contracts.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, expected in module.snapshots().items():
        assert json.loads((ROOT / "contracts" / name).read_text()) == expected, name
        if name.endswith(".schema.json"):
            Draft202012Validator.check_schema(expected)


def test_metadata_defaults_do_not_claim_model_compatibility():
    model = ModelMetadata(id="local-model", name="Example", format="GGUF", size_bytes=0)
    assert model.tested_backends == []
    assert model.license is None
    assert model.sha256 is None
    for extra in [{"size_bytes": -1}, {"sha256": "not-a-checksum"}, {"id": "../../file"}]:
        with pytest.raises(ValidationError):
            ModelMetadata.model_validate({**model.model_dump(), **extra})


def test_registry_identifies_duplicates_and_only_probes_registered_adapters():
    class ProbeOnlyTestAdapter:
        # Test double for the registry, not an inference integration or supported engine.
        id = "test-only"

        async def probe(self):
            return BackendInfo(id=self.id, available=False)

    registry = AdapterRegistry()
    assert asyncio.run(registry.discover()) == []
    registry.register(ProbeOnlyTestAdapter())
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(ProbeOnlyTestAdapter())
    result = asyncio.run(registry.discover())
    assert len(result) == 1
    assert not result[0].available
    assert result[0].resources.ram_bytes is None
    assert result[0].version is None
