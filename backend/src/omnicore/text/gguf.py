"""Bounded GGUF v2/v3 reader. Structural validation is not an inference test."""

import math
import os
import struct

from omnicore.text.types import TextError

MAX_METADATA_BYTES = 64 * 1024 * 1024
QUANTIZATION = {
    0: "F32",
    1: "F16",
    2: "Q4_0",
    3: "Q4_1",
    7: "Q8_0",
    8: "Q5_0",
    9: "Q5_1",
    10: "Q2_K",
    11: "Q3_K_S",
    12: "Q3_K_M",
    13: "Q3_K_L",
    14: "Q4_K_S",
    15: "Q4_K_M",
    16: "Q5_K_S",
    17: "Q5_K_M",
    18: "Q6_K",
}


def read_gguf(stream) -> dict:
    size = os.fstat(stream.fileno()).st_size
    endian = "<"

    def bounded(count):
        if count < 0 or stream.tell() + count > size or stream.tell() + count > MAX_METADATA_BYTES:
            raise TextError("invalid_gguf", 422)

    def read(count):
        bounded(count)
        result = stream.read(count)
        if len(result) != count:
            raise TextError("invalid_gguf", 422)
        return result

    def scalar(fmt):
        return struct.unpack(endian + fmt, read(struct.calcsize(fmt)))[0]

    def string(keep=True):
        length = scalar("Q")
        bounded(length)
        if keep:
            if length > 4 * 1024 * 1024:
                raise TextError("invalid_gguf", 422)
            try:
                return read(length).decode("utf-8")
            except UnicodeDecodeError:
                raise TextError("invalid_gguf", 422) from None
        stream.seek(length, 1)

    formats = {
        0: "B",
        1: "b",
        2: "H",
        3: "h",
        4: "I",
        5: "i",
        6: "f",
        7: "?",
        10: "Q",
        11: "q",
        12: "d",
    }

    def value(kind, keep=False, depth=0):
        if kind in formats:
            return scalar(formats[kind])
        if kind == 8:
            return string(keep)
        if kind != 9 or depth > 0:
            raise TextError("invalid_gguf", 422)
        subtype, count = scalar("I"), scalar("Q")
        if count > 1_000_000 or subtype not in {*formats, 8}:
            raise TextError("invalid_gguf", 422)
        if subtype in formats:
            length = count * struct.calcsize(formats[subtype])
            bounded(length)
            stream.seek(length, 1)
        else:
            for _ in range(count):
                string(False)
        return None

    try:
        if read(4) != b"GGUF":
            raise TextError("invalid_gguf", 422)
        version_raw = read(4)
        version = struct.unpack("<I", version_raw)[0]
        if version not in {2, 3}:
            endian = ">"
            version = struct.unpack(">I", version_raw)[0]
        if version not in {2, 3}:
            raise TextError("unsupported_gguf_version", 422)
        tensors, keys = scalar("Q"), scalar("Q")
        if not 0 < tensors <= 200_000 or not 0 < keys <= 4096:
            raise TextError("invalid_gguf", 422)
        metadata = {}
        seen_keys = set()
        for _ in range(keys):
            key = string()
            if len(key) > 256 or key in seen_keys:
                raise TextError("invalid_gguf", 422)
            seen_keys.add(key)
            keep = key in {
                "general.name",
                "general.architecture",
                "general.file_type",
                "general.license",
                "general.alignment",
                "general.quantization_version",
            }
            keep |= key.endswith(".context_length")
            item = value(scalar("I"), keep)
            if keep and isinstance(item, (str, int, float, bool)):
                if isinstance(item, float) and not math.isfinite(item):
                    raise TextError("invalid_gguf", 422)
                metadata[key] = item
        architecture = metadata.get("general.architecture")
        if not isinstance(architecture, str) or not architecture or len(architecture) > 128:
            raise TextError("invalid_gguf", 422)
        alignment = metadata.get("general.alignment", 32)
        if (
            not isinstance(alignment, int)
            or not 1 <= alignment <= 4096
            or alignment & (alignment - 1)
        ):
            raise TextError("invalid_gguf", 422)
        offsets = []
        for _ in range(tensors):
            string(False)
            dimensions = scalar("I")
            if not 1 <= dimensions <= 4:
                raise TextError("invalid_gguf", 422)
            elements = math.prod(scalar("Q") for _ in range(dimensions))
            kind, offset = scalar("I"), scalar("Q")
            if elements <= 0 or offset % alignment:
                raise TextError("invalid_gguf", 422)
            # Exact F32/F16 bounds; unknown quantization layouts are checked by the engine loader.
            minimum_size = elements * (4 if kind == 0 else 2 if kind == 1 else 0) or 1
            offsets.append((offset, minimum_size))
        data_start = (stream.tell() + alignment - 1) // alignment * alignment
        if any(data_start + offset + length > size for offset, length in offsets):
            raise TextError("invalid_gguf", 422)
        file_type = metadata.get("general.file_type")
        return {
            "version": version,
            "tensor_count": tensors,
            "architecture": architecture,
            "name": str(metadata.get("general.name", architecture))[:256],
            "quantization": QUANTIZATION.get(
                file_type, f"file_type_{file_type}" if file_type is not None else None
            ),
            "license": str(metadata["general.license"])[:256]
            if "general.license" in metadata
            else None,
            "metadata": metadata,
        }
    except (struct.error, OverflowError, OSError):
        raise TextError("invalid_gguf", 422) from None
