"""Explicit per-user AppImage integration. Never edits Plasma pins or app data."""

import configparser
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from importlib.resources import files
from pathlib import Path

from omnicore.text.native import native_environment

APP_ID = "io.github.vex2137.OmniCore"


def _path(value):
    path = Path(value).expanduser()
    if not path.is_absolute() or any(c in str(path) for c in "\n\r\x00\t"):
        raise ValueError("An absolute path without control characters is required")
    return path


def _atomic(path, content, mode=0o644):
    if path.is_symlink():
        raise ValueError("Refusing to replace a symbolic-link launcher or icon")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".omnicore-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def desktop_exec(image):
    # Exec quoting followed by Desktop Entry string escaping (two distinct layers).
    argument = str(image).replace("\\", "\\\\").replace('"', '\\"')
    argument = argument.replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
    return ('"' + argument + '"').replace("\\", "\\\\")


def install(image, data_home, *, png=None):
    image = _path(_path(image).resolve(strict=True))
    data_home = _path(data_home)
    if not image.is_file() or image.suffix != ".AppImage":
        raise ValueError("Select an existing AppImage file")
    png = files("omnicore.desktop").joinpath("icon.png").read_bytes() if png is None else png
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("The original OmniCore PNG icon is required")
    checksum = hashlib.sha256(png).hexdigest()
    applications = data_home / "applications"
    icons = data_home / "icons/hicolor/256x256/apps"
    for directory in (applications, data_home / "icons", icons.parent.parent, icons.parent, icons):
        if directory.is_symlink():
            raise ValueError("Refusing symbolic-link integration directories")
    applications.mkdir(parents=True, exist_ok=True)
    icons.mkdir(parents=True, exist_ok=True)
    desktop = applications / (APP_ID + ".desktop")
    if desktop.is_symlink():
        raise ValueError("Refusing a symbolic-link desktop entry")
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.optionxform = str
    if desktop.exists():
        if desktop.stat().st_size > 256_000:
            raise ValueError("Desktop entry is unexpectedly large")
        config.read_string(desktop.read_text(encoding="utf-8"))
    if "Desktop Entry" not in config:
        config["Desktop Entry"] = {}
    entry = config["Desktop Entry"]
    entry.setdefault("Name", "OmniCore")
    entry.setdefault("Comment", "Local AI conversations and GGUF models")
    entry.setdefault("Comment[pl]", "Lokalny czat AI i modele GGUF")
    entry.setdefault("Categories", "Utility;Science;")
    icon = icons / (APP_ID + "-" + checksum + ".png")
    entry.update(
        Type="Application",
        Exec=desktop_exec(image),
        Icon=str(icon).replace("\\", "\\\\"),
        StartupWMClass="OmniCore",
        Terminal="false",
        DBusActivatable="false",
    )
    entry.pop("TryExec", None)
    entry.pop("Hidden", None)
    entry.pop("NoDisplay", None)
    output = io.StringIO()
    config.write(output, space_around_delimiters=False)
    content = output.getvalue().encode()
    backup = None
    if desktop.exists() and desktop.read_bytes() != content:
        backup = desktop.with_name(desktop.name + ".bak-" + str(time.time_ns()))
        _atomic(backup, desktop.read_bytes(), 0o600)
    for target in (icon, icons / (APP_ID + ".png")):
        if target.is_symlink() or not target.exists() or target.read_bytes() != png:
            _atomic(target, png)
    image.chmod(image.stat().st_mode | 0o100)
    if not desktop.exists() or desktop.read_bytes() != content:
        _atomic(desktop, content)
    return {
        "desktop": str(desktop),
        "icon": str(icon),
        "icon_sha256": checksum,
        "launcher": "applications:" + APP_ID + ".desktop",
        "backup": str(backup) if backup else None,
    }


def refresh_caches(data_home):
    result = {}
    environment = native_environment()
    if getattr(sys, "frozen", False):
        for key in (
            "QT_PLUGIN_PATH",
            "QT_QPA_PLATFORM_PLUGIN_PATH",
            "QML2_IMPORT_PATH",
            "QT_QPA_PLATFORMTHEME",
        ):
            environment.pop(key, None)
    for tool, args in (
        ("update-desktop-database", [str(data_home / "applications")]),
        ("kbuildsycoca6", ["--noincremental"]),
    ):
        executable = shutil.which(tool)
        if executable:
            try:
                code = subprocess.run(  # noqa: S603 — fixed desktop cache tools, no shell.
                    [executable, *args],
                    timeout=20,
                    capture_output=True,
                    check=False,
                    env=environment,
                ).returncode
                result[tool] = "ok" if code == 0 else "failed"
            except (OSError, subprocess.TimeoutExpired):
                result[tool] = "failed"
        else:
            result[tool] = "not installed"
    return result


def main(arguments):
    if len(arguments) > 1:
        raise SystemExit(
            "Usage: OmniCore.AppImage --install-desktop-entry [/absolute/OmniCore.AppImage]"
        )
    image = arguments[0] if arguments else os.environ.get("APPIMAGE", "")
    data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))
    try:
        result = install(image, data)
        result["cache_refresh"] = refresh_caches(_path(data))
    except (ValueError, OSError, configparser.Error) as error:
        raise SystemExit("Desktop integration failed: " + str(error)) from None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        "KDE: unpin only the old OmniCore shortcut, launch OmniCore from the menu and pin it again."
    )
    return 0
