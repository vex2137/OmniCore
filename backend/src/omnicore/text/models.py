import os
from pathlib import Path

from omnicore.text.downloads import is_multipart_gguf
from omnicore.text.files import FilePolicy
from omnicore.text.gguf import read_gguf
from omnicore.text.store import TextStore
from omnicore.text.types import TextError


class ModelManager:
    def __init__(self, store: TextStore, policy: FilePolicy):
        self.store, self.policy = store, policy

    def import_gguf(self, path: Path, refresh_existing=False):
        if is_multipart_gguf(path.name):
            raise TextError("multipart_gguf_unsupported", 422)
        with self.policy.open(path) as stream:
            metadata = read_gguf(stream)
            info = os.fstat(stream.fileno())
        metadata["file_mtime_ns"] = info.st_mtime_ns
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
            refresh_existing=refresh_existing,
        )

    def validated_reference(self, model_id):
        record = self.store.model(model_id)
        if record.backend != "llama.cpp":
            raise TextError("unsupported_backend", 422)
        expected_dev, expected_ino = self.store.model_identity(model_id)
        old_mtime = record.metadata.get("file_mtime_ns")
        old_digest = record.metadata.get("gguf_digest")
        with self.policy.open(Path(record.location)) as stream:
            info = os.fstat(stream.fileno())
            if info.st_ino != expected_ino or info.st_size != record.size_bytes:
                raise TextError("model_file_changed", 409)
            if old_mtime is None or info.st_mtime_ns == old_mtime:
                if info.st_dev != expected_dev:
                    self.store.heal_model_reference(
                        model_id,
                        device=info.st_dev,
                        inode=info.st_ino,
                        size_bytes=info.st_size,
                        mtime_ns=info.st_mtime_ns,
                        digest=old_digest,
                    )
                return Path(record.location)
            meta = read_gguf(stream)
            if old_digest is not None and meta["gguf_digest"] == old_digest:
                self.store.heal_model_reference(
                    model_id,
                    device=info.st_dev,
                    inode=info.st_ino,
                    size_bytes=info.st_size,
                    mtime_ns=info.st_mtime_ns,
                    digest=meta["gguf_digest"],
                )
                return Path(record.location)
            raise TextError("model_file_changed", 409)

    def _root_candidates(self, roots) -> list[Path]:
        candidates = []
        seen = set()
        for root in roots:
            if root.is_symlink() or not root.is_dir():
                continue
            try:
                entries = sorted(root.iterdir(), key=lambda p: p.name.casefold())
            except OSError:
                continue
            for entry in entries:
                if (
                    entry.suffix.lower() == ".gguf"
                    and not entry.is_symlink()
                    and entry.is_file()
                    and not is_multipart_gguf(entry.name)
                ):
                    resolved = entry.absolute()
                    if resolved not in seen:
                        seen.add(resolved)
                        candidates.append(resolved)
        return candidates

    def scan_and_recover(self, *, import_all_roots: bool = False):
        records = self.store.models()
        all_candidates = self._root_candidates(self.policy.roots)
        claimed = {
            Path(r.location).absolute() for r in records if r.backend == "llama.cpp"
        }
        for record in records:
            if record.backend != "llama.cpp":
                continue
            old_digest = record.metadata.get("gguf_digest")
            location = Path(record.location)
            try:
                with self.policy.open(location) as stream:
                    info = os.fstat(stream.fileno())
                    meta = read_gguf(stream)
                if (
                    info.st_size == record.size_bytes
                    and meta["name"] == record.name
                    and (old_digest is None or meta["gguf_digest"] == old_digest)
                ):
                    self.store.heal_model_reference(
                        record.id,
                        device=info.st_dev,
                        inode=info.st_ino,
                        size_bytes=info.st_size,
                        mtime_ns=info.st_mtime_ns,
                        digest=meta["gguf_digest"],
                        file_status="available",
                    )
                else:
                    record.metadata["file_status"] = "changed"
                    self.store.update_model(record)
                continue
            except TextError:
                pass
            unclaimed = [p for p in all_candidates if p not in claimed]
            matches = sorted(
                unclaimed,
                key=lambda p: (p.name != location.name, p.name.casefold()),
            )
            recovered = False
            for candidate in matches:
                try:
                    with self.policy.open(candidate) as stream:
                        info = os.fstat(stream.fileno())
                        if info.st_size != record.size_bytes:
                            continue
                        meta = read_gguf(stream)
                    if meta["name"] == record.name and (
                        old_digest is None or meta["gguf_digest"] == old_digest
                    ):
                        self.store.heal_model_reference(
                            record.id,
                            device=info.st_dev,
                            inode=info.st_ino,
                            size_bytes=info.st_size,
                            mtime_ns=info.st_mtime_ns,
                            digest=meta["gguf_digest"],
                            location=str(candidate),
                            file_status="available",
                        )
                        claimed.add(candidate)
                        recovered = True
                        break
                except TextError:
                    continue
            if not recovered:
                record.metadata["file_status"] = "missing"
                self.store.update_model(record)
        scan_roots = self.policy.roots if import_all_roots else self.policy.roots[:-1]
        for candidate in self._root_candidates(scan_roots):
            if candidate in claimed:
                continue
            try:
                self.import_gguf(candidate)
                claimed.add(candidate)
            except TextError:
                continue
        return self.store.models()

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
                    license=model.license[:256] if model.license else None,
                    metadata={"license_text": model.license} if model.license else {},
                    capabilities=model.capabilities or await engine.capabilities(model.name),
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
