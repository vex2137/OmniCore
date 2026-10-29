"""Choose native Qt platforms without overriding an explicit user selection."""

import os


def configure_platform(environ=None):
    environ = os.environ if environ is None else environ
    if environ.get("QT_QPA_PLATFORM"):
        return environ["QT_QPA_PLATFORM"]
    if environ.get("WAYLAND_DISPLAY"):
        selection = "wayland;xcb" if environ.get("DISPLAY") else "wayland"
    elif environ.get("DISPLAY"):
        selection = "xcb"
    else:
        return None
    environ["QT_QPA_PLATFORM"] = selection
    return selection
