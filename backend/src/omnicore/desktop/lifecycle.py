"""Own one authenticated backend; reuse an explicitly configured service safely."""

import os
import secrets
import socket
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from omnicore.desktop.config import data_path


class BackendSession(QObject):
    ready = Signal()
    failed = Signal(str)
    stopped = Signal()
    log = Signal(str)

    def __init__(self, api, config, parent=None):
        super().__init__(parent)
        self.api, self.config = api, config
        self.process = None
        self.owned = False
        self.closing = False
        self._attempt = 0
        self._ready = False
        self._restart = False
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._probe)
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._kill)

    def start(self):
        self.closing = False
        self._ready = False
        url = os.environ.get("OMNICORE_DESKTOP_URL", "http://127.0.0.1:8000")
        # Remote configuration is explicit and tokens are supplied only in process environment.
        from urllib.parse import urlsplit

        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            self.failed.emit("invalid_backend_url")
            return
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            self.failed.emit("remote_requires_https")
            return
        self.api.configure(url, os.environ.get("OMNICORE_DESKTOP_TOKEN", ""))
        self.api.request(
            "GET", "/api/v1/health", success=self._reuse, failure=self._not_running, timeout=700
        )

    def reconnect(self):
        if self.closing:
            return
        self._ready = False
        if self.owned and self.process and self.process.state() != QProcess.NotRunning:
            self.api.request(
                "GET", "/api/v1/health", success=self._connected, failure=self.failed.emit
            )
        else:
            self.start()

    def _reuse(self, health):
        if not isinstance(health, dict) or health.get("status") != "ok":
            self.failed.emit("incompatible_backend")
            return
        self.owned = False
        self._ready = True
        self.ready.emit()

    def _not_running(self, error):
        if self.closing:
            return
        if os.environ.get("OMNICORE_DESKTOP_URL") or error == "unauthorized":
            self.failed.emit(error)
            return
        self._spawn()

    def _spawn(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        token = secrets.token_hex(32)
        self.api.configure(f"http://127.0.0.1:{port}", token)
        environment = QProcessEnvironment.systemEnvironment()
        for key in ("OMNICORE_ALLOW_REMOTE", "OMNICORE_ALLOWED_ORIGINS", "OMNICORE_ALLOWED_HOSTS"):
            environment.remove(key)
        values = {
            "OMNICORE_API_TOKEN": token,
            "OMNICORE_HOST": "127.0.0.1",
            "OMNICORE_PORT": str(port),
            "OMNICORE_DATA_DIR": str(data_path()),
            "OMNICORE_MODEL_ROOTS": os.pathsep.join(self.config.model_roots),
            "OMNICORE_OLLAMA_URL": self.config.ollama_url,
            "OMNICORE_OLLAMA_ENABLED": "1" if self.config.ollama_enabled else "0",
        }
        if self.config.llama_server:
            values["OMNICORE_LLAMA_SERVER"] = self.config.llama_server
        else:
            environment.remove("OMNICORE_LLAMA_SERVER")
        for key, value in values.items():
            environment.insert(key, value)
        process = QProcess(self)
        self.process = process
        process.setProcessEnvironment(environment)
        # Source and AppImage use the same dispatcher. Never pass a token in argv.
        args = ["--backend", str(os.getpid())]
        if not getattr(sys, "frozen", False):
            args = ["-m", "omnicore.desktop.launcher", *args]
        process.setProgram(sys.executable)
        process.setArguments(args)
        process.setWorkingDirectory(str(Path.home()))
        process.setProcessChannelMode(QProcess.MergedChannels)
        # Deliberately drain raw logs without displaying/persisting prompts, paths or secrets.
        process.readyReadStandardOutput.connect(lambda: process.readAllStandardOutput())
        process.finished.connect(self._finished)
        process.errorOccurred.connect(lambda _: self.failed.emit("backend_process_error"))
        self.owned, self._attempt = True, 0
        process.start()
        self._timer.start()
        self.log.emit("backend_starting")

    def _probe(self):
        if self.closing:
            return
        self._attempt += 1
        if self._attempt > 120:
            self._timer.stop()
            self.failed.emit("backend_timeout")
            self.stop()
            return
        self.api.request(
            "GET", "/api/v1/health", success=self._connected, failure=lambda _: None, timeout=600
        )

    def _connected(self, health):
        if self.closing or self._ready or health.get("status") != "ok":
            return
        self._timer.stop()
        self._ready = True
        self.ready.emit()

    def restart(self, config):
        self.config = config
        if not self.owned:
            self.failed.emit("external_backend_settings")
            return
        self._restart = True
        self.stop()

    def stop(self):
        self.closing = True
        self._timer.stop()
        self.api.close_stream()
        if self.owned and self.process and self.process.state() != QProcess.NotRunning:
            self.process.terminate()
            self._kill_timer.start(8000)
        else:
            QTimer.singleShot(0, self.stopped.emit)

    def _kill(self):
        if self.process and self.process.state() != QProcess.NotRunning:
            self.process.kill()

    def _finished(self, *_):
        self._timer.stop()
        self._kill_timer.stop()
        self._ready = False
        if self._restart:
            self._restart = False
            self.closing = False
            self._spawn()
        elif self.closing:
            self.stopped.emit()
        else:
            self.failed.emit("backend_exited")
