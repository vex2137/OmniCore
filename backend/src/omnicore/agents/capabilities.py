"""Backend-aware declarations and opt-in compatibility evidence, no startup inference."""

import hashlib
import json
from pathlib import Path

from omnicore.text.types import TextError


def native_declared(model, engine):
    # The existing Ollama adapter exposes native tools. llama.cpp remains strict JSON.
    return model.backend == "ollama" and engine is not None and "tool-calling" in model.capabilities


def template_for(service, model):
    metadata = model.metadata if isinstance(model.metadata, dict) else {}
    nested = metadata.get("metadata")
    nested = nested if isinstance(nested, dict) else {}
    value = (
        getattr(service.config, "llama_chat_template", None)
        or metadata.get("chat_template")
        or nested.get("tokenizer.chat_template")
    )
    return value if isinstance(value, str) else None


def cache_key(service, model):
    engine = service.engines.get(model.backend)
    files = []
    for name in ("llama_server", "llama_cuda_server"):
        value = getattr(service.config, name, None)
        try:
            info = Path(value).stat() if value else None
            files.append((str(value), info.st_size, info.st_mtime_ns) if info else None)
        except OSError:
            files.append((str(value), "missing"))
    metadata = model.metadata if isinstance(model.metadata, dict) else {}
    signature = [
        model.id,
        model.backend,
        model.location,
        model.created_at,
        model.capabilities,
        type(engine).__name__,
        files,
        getattr(service.config, "ollama_url", None),
        getattr(service.config, "llama_chat_template", None),
        template_for(service, model),
        metadata.get("sha256"),
        metadata.get("architecture"),
    ]
    if model.backend == "llama.cpp":
        try:
            info = Path(model.location).stat()
            signature.append((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns))
        except OSError:
            signature.append("missing-model")
    return hashlib.sha256(json.dumps(signature, sort_keys=True, default=str).encode()).hexdigest()


def capability(service, model):
    engine = service.engines.get(model.backend)
    declared = "native" if native_declared(model, engine) else "unverified"
    template = template_for(service, model)
    if declared != "native" and "structured-output" in model.capabilities:
        declared = "json"
    result = {
        "model_id": model.id,
        "backend": model.backend,
        "declared": declared,
        "status": declared,
        "tested": False,
        "template_available": bool(isinstance(template, str) and template),
        "protocol": "native" if declared == "native" else "json",
    }
    try:
        saved = service.store.job("agent-compatibility", cache_key(service, model))
        result.update(saved)
    except TextError as exc:
        if exc.code != "not_found":
            raise
    return result
