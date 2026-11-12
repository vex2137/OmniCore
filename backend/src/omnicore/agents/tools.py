"""Descriptor-scoped filesystem capabilities and bounded, non-evaluating arithmetic."""

import ast
import ctypes
import difflib
import hashlib
import math
import operator
import os
import stat
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import Field

from omnicore.schemas import WireModel
from omnicore.text.types import TextError

LIMIT = 65536


class FileArgs(WireModel):
    grant_id: str = Field(min_length=1, max_length=64)
    path: str = Field(default=".", min_length=1, max_length=2048)


class FindArgs(FileArgs):
    query: str = Field(min_length=1, max_length=128)


class WriteArgs(FileArgs):
    mode: Literal["create", "edit"]
    content: str = Field(max_length=LIMIT)


class CalculateArgs(WireModel):
    expression: str = Field(min_length=1, max_length=256)


TOOLS = {
    "list_files": (FileArgs, "List up to 200 entries in a granted directory."),
    "read_text": (FileArgs, "Read a UTF-8 regular file, at most 64 KiB."),
    "find_files": (FindArgs, "Search filenames below a granted directory, bounded traversal."),
    "file_info": (
        FileArgs,
        "Get name, extension, size and modification time without file contents.",
    ),
    "write_text": (
        WriteArgs,
        "Propose creation or replacement of a UTF-8 file; human approval required.",
    ),
    "calculate": (
        CalculateArgs,
        "Basic arithmetic: + - * / // % ** and parentheses; no code execution.",
    ),
}


def schemas():
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": model.model_json_schema(),
            },
        }
        for name, (model, description) in TOOLS.items()
    ]


def calculate(expression):
    binary = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 64:
        raise TextError("agent_calculation_limit", 422)

    def number(node):
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            value = node.value
        elif isinstance(node, ast.UnaryOp) and type(node.op) in {ast.UAdd, ast.USub}:
            value = number(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in binary:
            left, right = number(node.left), number(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 12 or abs(left) > 10**12):
                raise TextError("agent_calculation_limit", 422)
            value = binary[type(node.op)](left, right)
        else:
            raise TextError("agent_invalid_calculation", 422)
        if type(value) not in {int, float} or not math.isfinite(value) or abs(value) > 10**100:
            raise TextError("agent_calculation_limit", 422)
        return value

    return {"value": number(tree.body)}


@dataclass
class Grant:
    id: str
    conversation_id: str
    path: str
    fd: int
    sensitive: bool = False
    active: bool = True
    lock: threading.RLock = field(default_factory=threading.RLock)


class FileTools:
    def __init__(self):
        self.grants = {}
        self.write_lock = threading.RLock()

    def grant(self, conversation_id, path, sensitive=False):
        if not os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW"):
            raise TextError("agent_filesystem_unsupported", 422)
        if sum(g.active for g in self.grants.values()) >= 32:
            raise TextError("agent_grant_limit", 422)
        root = Path(path).resolve(strict=True)
        if not root.is_dir() or str(root) == "/" or root.parts[1] in {"proc", "sys", "dev"}:
            raise TextError("agent_permission_denied", 403)
        if not sensitive and any(part.startswith(".") for part in root.parts):
            raise TextError("agent_sensitive_file", 403)
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        grant = Grant(uuid.uuid4().hex, conversation_id, str(root), fd, sensitive)
        self.grants[grant.id] = grant
        return self.describe(grant)

    @staticmethod
    def describe(grant):
        return {"id": grant.id, "path": grant.path, "sensitive": grant.sensitive}

    def revoke(self, grant_id, conversation_id):
        grant = self.get(grant_id, conversation_id)
        with grant.lock:
            grant.active = False
            os.close(grant.fd)

    def get(self, grant_id, conversation_id):
        grant = self.grants.get(grant_id)
        if not grant or not grant.active or grant.conversation_id != conversation_id:
            raise TextError("agent_permission_denied", 403)
        return grant

    @staticmethod
    def check(grant, cancelled):
        if cancelled.is_set() or not grant.active:
            raise TextError("agent_cancelled", 409)

    @staticmethod
    def sensitive(name):
        lower = name.casefold()
        return (
            lower.startswith(".")
            or any(
                word in lower
                for word in (
                    "secret",
                    "credential",
                    "password",
                    "signing",
                    "token",
                    "id_rsa",
                    "id_ed25519",
                )
            )
            or lower.endswith((".pem", ".key", ".p12", ".pfx", ".keystore"))
            or lower in {"shadow", "gshadow"}
        )

    def parts(self, grant, path):
        if "\\" in path or path.startswith("/") or "\x00" in path:
            raise TextError("agent_permission_denied", 403)
        parts = path.split("/")
        if ".." in parts or any(not part for part in parts):
            raise TextError("agent_permission_denied", 403)
        parts = [part for part in parts if part != "."]
        if not grant.sensitive and any(self.sensitive(part) for part in parts):
            raise TextError("agent_sensitive_file", 403)
        return parts

    @contextmanager
    def directory(self, grant, parts, cancelled):
        with grant.lock:
            self.check(grant, cancelled)
            fd = os.dup(grant.fd)
        try:
            for part in parts:
                self.check(grant, cancelled)
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd
        finally:
            os.close(fd)

    @staticmethod
    def read_at(parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > LIMIT:
                raise TextError("agent_file_limit", 422)
            data = bytearray()
            while len(data) <= LIMIT:
                block = os.read(fd, LIMIT + 1 - len(data))
                if not block:
                    break
                data.extend(block)
            after = os.fstat(fd)
            if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise TextError("agent_file_conflict", 409)
            data = bytes(data)
            if len(data) > LIMIT:
                raise TextError("agent_file_limit", 422)
            data.decode("utf-8")
            return data, (info.st_dev, info.st_ino, hashlib.sha256(data).hexdigest())
        finally:
            os.close(fd)

    def read(self, tool, args, conversation_id, cancelled):
        grant = self.get(args.grant_id, conversation_id)
        parts = self.parts(grant, args.path)
        self.check(grant, cancelled)
        if tool in {"read_text", "file_info"}:
            if not parts:
                if tool == "read_text":
                    raise TextError("agent_invalid_path", 422)
                with self.directory(grant, [], cancelled) as folder:
                    return {"name": ".", "type": "directory", "size": os.fstat(folder).st_size}
            with self.directory(grant, parts[:-1], cancelled) as parent:
                info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise TextError("agent_permission_denied", 403)
                if tool == "read_text":
                    result = {"text": self.read_at(parent, parts[-1])[0].decode("utf-8")}
                else:
                    result = {
                        "name": parts[-1],
                        "size": info.st_size,
                        "extension": Path(parts[-1]).suffix,
                        "modified_ns": info.st_mtime_ns,
                    }
        else:
            result = {"entries": []}
            queue = [(parts, 0)]
            visited, deadline = 0, time.monotonic() + 2
            while queue and len(result["entries"]) < 200:
                current, depth = queue.pop()
                with (
                    self.directory(grant, current, cancelled) as folder,
                    os.scandir(folder) as entries,
                ):
                    for entry in entries:
                        self.check(grant, cancelled)
                        visited += 1
                        if visited > 4000 or time.monotonic() > deadline:
                            result["limited"] = True
                            return result
                        if not grant.sensitive and self.sensitive(entry.name):
                            continue
                        info = entry.stat(follow_symlinks=False)
                        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                            continue
                        relative = "/".join([*current, entry.name])
                        if tool == "list_files" or args.query.casefold() in entry.name.casefold():
                            result["entries"].append(
                                {
                                    "path": relative,
                                    "directory": stat.S_ISDIR(info.st_mode),
                                    "size": info.st_size,
                                }
                            )
                            if len(result["entries"]) >= 200:
                                result["limited"] = True
                                break
                        if tool == "find_files" and stat.S_ISDIR(info.st_mode) and depth < 12:
                            queue.append(([*current, entry.name], depth + 1))
        self.check(grant, cancelled)
        return result

    def propose(self, args, conversation_id, cancelled):
        grant = self.get(args.grant_id, conversation_id)
        parts = self.parts(grant, args.path)
        if not parts or len(args.content.encode("utf-8")) > LIMIT:
            raise TextError("agent_file_limit", 422)
        with self.directory(grant, parts[:-1], cancelled) as parent:
            try:
                before, identity = self.read_at(parent, parts[-1])
            except FileNotFoundError:
                before, identity = b"", None
            if (args.mode == "create") != (identity is None):
                raise TextError("agent_file_conflict", 409)
        return {
            "grant": grant,
            "parts": parts,
            "before": before,
            "identity": identity,
            "content": args.content,
            "diff": "".join(
                difflib.unified_diff(
                    before.decode("utf-8").splitlines(True),
                    args.content.splitlines(True),
                    fromfile=args.path,
                    tofile=args.path,
                )
            ),
        }

    @staticmethod
    def exchange(parent, first, second):
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise TextError("agent_atomic_edit_unsupported", 422)
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        if rename(parent, os.fsencode(first), parent, os.fsencode(second), 2):
            number = ctypes.get_errno()
            raise OSError(number, os.strerror(number))

    def commit(self, proposal, cancelled):
        grant, parts = proposal["grant"], proposal["parts"]
        with self.write_lock, grant.lock, self.directory(grant, parts[:-1], cancelled) as parent:
            self.check(grant, cancelled)
            try:
                _, current = self.read_at(parent, parts[-1])
            except FileNotFoundError:
                current = None
            if current != proposal["identity"]:
                raise TextError("agent_file_conflict", 409)
            temp = ".omnicore-backup-" + uuid.uuid4().hex
            fd = os.open(
                temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
            )
            staged = os.fstat(fd)
            keep = False
            try:
                data = proposal["content"].encode("utf-8")
                while data:
                    self.check(grant, cancelled)
                    data = data[os.write(fd, data) :]
                os.fsync(fd)
                self.check(grant, cancelled)
                # Check that the parent still resolves through the granted root.
                with self.directory(grant, parts[:-1], cancelled) as fresh:
                    fresh_info, parent_info = os.fstat(fresh), os.fstat(parent)
                    if (fresh_info.st_dev, fresh_info.st_ino) != (
                        parent_info.st_dev,
                        parent_info.st_ino,
                    ):
                        raise TextError("agent_file_conflict", 409)
                staged_path = os.stat(temp, dir_fd=parent, follow_symlinks=False)
                if (staged_path.st_dev, staged_path.st_ino) != (staged.st_dev, staged.st_ino):
                    raise TextError("agent_file_conflict", 409)
                if current is None:
                    # Hard-link creation is atomic and cannot overwrite a concurrent new file.
                    os.link(
                        temp, parts[-1], src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False
                    )
                else:
                    # Preserve the exchanged original inode; a concurrent replacement is
                    # detected AFTER the atomic exchange and is never silently destroyed.
                    self.exchange(parent, temp, parts[-1])
                    keep = True
                    try:
                        _, exchanged = self.read_at(parent, temp)
                    except (OSError, TextError, UnicodeError):
                        exchanged = None
                    if exchanged != current:
                        self.exchange(parent, temp, parts[-1])
                        keep = False
                        raise TextError("agent_file_conflict", 409)
                proposal["committed_result"] = {
                    "written": True,
                    "bytes": len(proposal["content"].encode("utf-8")),
                    "backup": temp if keep else None,
                }
                os.fsync(parent)
                return proposal["committed_result"]
            except FileExistsError as exc:
                raise TextError("agent_file_conflict", 409) from exc
            finally:
                os.close(fd)
                if not keep:
                    try:
                        leftover = os.stat(temp, dir_fd=parent, follow_symlinks=False)
                        if (leftover.st_dev, leftover.st_ino) == (staged.st_dev, staged.st_ino):
                            os.unlink(temp, dir_fd=parent)
                    except FileNotFoundError:
                        pass

    def signal_cancel(self, cancelled):
        # Acknowledge cancellation only after any approved atomic commit has exited.
        with self.write_lock:
            cancelled.set()

    def close(self):
        for grant in list(self.grants.values()):
            if grant.active:
                self.revoke(grant.id, grant.conversation_id)
