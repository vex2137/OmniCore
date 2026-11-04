import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from omnicore import __version__
from omnicore.desktop.lifecycle import BackendSession


def test_reused_backend_requires_matching_version():
    app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])
    session = BackendSession(None, None)
    ready, failures = [], []
    session.ready.connect(lambda: ready.append(True))
    session.failed.connect(failures.append)
    session._reuse({"status": "ok", "version": "other"})
    assert failures == ["incompatible_backend"] and not ready
    session._reuse({"status": "ok", "version": __version__})
    assert ready == [True]
    assert app


def test_startup_output_is_classified_without_exposing_log():
    app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])
    session = BackendSession(None, None)

    class Process:
        def readAllStandardOutput(self):
            return b"private detail: Unsupported v5 schema"

    session.process = Process()
    session._read_output()
    assert session._startup_error == "database_incompatible"
    assert app
