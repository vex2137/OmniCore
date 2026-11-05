"""Owner-only process credentials, never included in desktop preferences or reports."""

import os
import secrets
import stat

from omnicore.desktop.config import data_path


def server_token(*, create=False):
    directory = data_path()
    if create:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "server.token"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        if not create:
            return ""
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            return server_token()
        with os.fdopen(fd, "w") as stream:
            value = secrets.token_hex(32)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        return value
    with os.fdopen(fd, "r") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise OSError("Unsafe server credential permissions")
        value = stream.read(129)
    if len(value) != 64 or not value.isascii() or not value.isalnum():
        raise OSError("Invalid server credential")
    return value


def lan_addresses():
    from PySide6.QtNetwork import QNetworkInterface

    from omnicore.pairing import private_peer

    addresses = set()
    for interface in QNetworkInterface.allInterfaces():
        if not interface.flags() & QNetworkInterface.IsUp:
            continue
        for entry in interface.addressEntries():
            address = entry.ip()
            text = address.toString()
            if not address.isLoopback() and ":" not in text and private_peer(text):
                addresses.add(text)
    return sorted(addresses)
