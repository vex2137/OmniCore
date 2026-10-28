"""Open model references by descriptor, without following symlinks."""

import os
import stat
from contextlib import contextmanager
from pathlib import Path

from omnicore.text.types import TextError


class FilePolicy:
    def __init__(self, roots: tuple[Path, ...]):
        self.roots = tuple(path.absolute() for path in roots)

    def validate(self, path: Path) -> Path:
        if not path.is_absolute() or ".." in path.parts:
            raise TextError("invalid_path", 403)
        path = path.absolute()
        if not any(path.is_relative_to(root) and path != root for root in self.roots):
            raise TextError("invalid_path", 403)
        return path

    @contextmanager
    def open(self, path: Path):
        path = self.validate(path)
        descriptor = None
        try:
            descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
            for component in path.parts[1:-1]:
                child = os.open(
                    component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                os.close(descriptor)
                descriptor = child
            file_descriptor = os.open(
                path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
            )
            with os.fdopen(file_descriptor, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise TextError("invalid_path", 403)
                yield stream
        except OSError:
            raise TextError("invalid_path", 403) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def remove(self, path: Path, expected_device: int, expected_inode: int):
        # Check the exact reference and keep the parent descriptor for the unlink.
        path = self.validate(path)
        with self.open(path) as stream:
            info = os.fstat(stream.fileno())
            if (info.st_dev, info.st_ino) != (expected_device, expected_inode):
                raise TextError("model_file_changed", 409)
            descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
            try:
                for component in path.parts[1:-1]:
                    child = os.open(
                        component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                    )
                    os.close(descriptor)
                    descriptor = child
                current = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                    raise TextError("model_file_changed", 409)
                os.unlink(path.name, dir_fd=descriptor)
            finally:
                os.close(descriptor)
