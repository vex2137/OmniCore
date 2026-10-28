import os
from pathlib import Path

from omnicore.text.files import FilePolicy
from omnicore.text.gguf import read_gguf
from omnicore.text.store import TextStore
from omnicore.text.types import TextError


class ModelManager:
    def __init__(self, store: TextStore, policy: FilePolicy):
        self.store, self.policy = store, policy

    def import_gguf(self, path: Path):
        with self.policy.open(path) as stream:
            metadata = read_gguf(stream)
            info = os.fstat(stream.fileno())
        return self.store.add_model(
            backend="llama.cpp",
            location=str(path),
            name=metadata["name"],
            size_bytes=info.st_size,
            format="GGUF",
            quantization=metadata["quantization"],
            license=metadata["license"],
            metadata=metadata,
            device=info.st_dev,
            inode=info.st_ino,
        )

    def validated_reference(self, model_id):
        record = self.store.model(model_id)
        if record.backend != "llama.cpp":
            raise TextError("unsupported_backend", 422)
        with self.policy.open(Path(record.location)) as stream:
            info = os.fstat(stream.fileno())
            if (info.st_dev, info.st_ino) != self.store.model_identity(
                model_id
            ) or info.st_size != record.size_bytes:
                raise TextError("model_file_changed", 409)
        return Path(record.location)

    async def register_ollama(self, engine):
        records = []
        for model in await engine.models():
            records.append(
                self.store.add_model(
                    backend="ollama",
                    location=model.name,
                    name=model.name,
                    size_bytes=model.size_bytes,
                    format="Ollama",
                    quantization=model.quantization,
                    license=model.license,
                    capabilities=await engine.capabilities(model.name),
                )
            )
        return records

    def remove(self, model_id, *, delete_file=False, confirm_name=None):
        record = self.store.model(model_id)
        if delete_file:
            if record.backend != "llama.cpp" or confirm_name != record.name:
                raise TextError("confirmation_required", 409)
            device, inode = self.store.model_identity(model_id)
            self.policy.remove(Path(record.location), device, inode)
        self.store.delete_model(model_id)
