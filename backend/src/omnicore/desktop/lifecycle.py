"""Own one authenticated backend; reuse an explicitly configured service safely."""

import os
import secrets
import socket
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from omnicore.backend_lock import discover_backend
from omnicore.desktop.config import data_path


class BackendSession(QObject):
    ready = Signal()
    failed = Signal(str)
    stopped = Signal()
    log = Signal(str)
    state_changed = Signal(str)

    def __init__(self, api, config, parent=None):
        super().__init__(parent)
        self.api, self.config = api, config
        self.process = None
        self.owned = False
        self.closing = False
        self._attempt = 0
        self._ready = False
        self._restart = False
        self._starting = False
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._probe)
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._kill)

    def start(self):
        if self.process and self.process.state() != QProcess.NotRunning:
            self.reconnect()
            return
        if self._starting:
            return
        self.closing = False
        self._ready = False
        self._starting = True
        self.state_changed.emit("connecting")
        url = os.environ.get("OMNICORE_DESKTOP_URL", "http://127.0.0.1:8000")
        if not os.environ.get("OMNICORE_DESKTOP_URL"):
            try:
                existing = discover_backend(data_path())
            except OSError:
                self._fail("backend_lock_error")
                return
            if existing is not None:
                if not existing.get("url"):
                    self._fail("backend_in_use")
                    return
                self.api.configure(existing["url"], os.environ.get("OMNICORE_DESKTOP_TOKEN", ""))
                self.owned, self._attempt = False, 0
                self.state_changed.emit("backend_starting")
                self._timer.start()
                self._probe()
                return
        # Remote configuration is explicit and tokens are supplied only in process environment.
        from urllib.parse import urlsplit

        try:
            parsed = urlsplit(url)
            valid_port = parsed.port is None or 1 <= parsed.port <= 65535
        except ValueError:
            self._fail("invalid_backend_url")
            return
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or not valid_port
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            self._fail("invalid_backend_url")
            return
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            self._fail("remote_requires_https")
            return
        self.api.configure(url, os.environ.get("OMNICORE_DESKTOP_TOKEN", ""))
        self.api.request(
            "GET", "/api/v1/health", success=self._reuse, failure=self._not_running, timeout=700
        )

    def reconnect(self):
        if self.closing and self.process and self.process.state() != QProcess.NotRunning:
            return
        self.closing = False
        if self._starting:
            return
        self._ready = False
        self.state_changed.emit("connecting")
        if self.owned and self.process and self.process.state() != QProcess.NotRunning:
            self.api.request("GET", "/api/v1/health", success=self._connected, failure=self._fail)
        else:
            self.start()

    def _reuse(self, health):
        if not isinstance(health, dict) or health.get("status") != "ok":
            self._fail("incompatible_backend")
            return
        self.owned = False
        self._ready = True
        self._starting = False
        self.state_changed.emit("connected")
        self.ready.emit()

    def _fail(self, code):
        self._timer.stop()
        self._starting = False
        self.state_changed.emit("error")
        self.failed.emit(code)

    def _not_running(self, error):
        if self.closing:
            return
        if os.environ.get("OMNICORE_DESKTOP_URL") or error == "unauthorized":
            self._fail(error)
            return
        self._spawn()

    def _spawn(self):
        try:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
        except OSError:
            self._fail("backend_port_error")
            return
        self._starting = True
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
        if self.config.llama_cuda_server:
            values["OMNICORE_LLAMA_CUDA_SERVER"] = self.config.llama_cuda_server
        else:
            environment.remove("OMNICORE_LLAMA_CUDA_SERVER")
        for key, value in values.items():
            environment.insert(key, value)
        if self.process and self.process.state() == QProcess.NotRunning:
            self.process.deleteLater()
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
        process.errorOccurred.connect(self._process_error)
        self.owned, self._attempt = True, 0
        process.start()
        self._timer.start()
        self.log.emit("backend_starting")
        self.state_changed.emit("backend_starting")

    def _process_error(self, error):
        if error == QProcess.FailedToStart:
            self.owned = False
            self._fail("backend_process_error")

    def _probe(self):
        if self.closing:
            return
        self._attempt += 1
        if self._attempt > 120:
            self._timer.stop()
            self._fail("backend_timeout")
            if self.owned and self.process:
                self.process.terminate()
                self._kill_timer.start(8000)
            return
        self.api.request(
            "GET",
            "/api/v1/health",
            success=self._connected,
            failure=self._probe_failed,
            timeout=600,
        )

    def _probe_failed(self, code):
        if code == "unauthorized":
            self._fail("backend_auth_required")

    def _connected(self, health):
        if self.closing or self._ready:
            return
        if not isinstance(health, dict) or health.get("status") != "ok":
            self._fail("incompatible_backend")
            return
        self._timer.stop()
        self._ready = True
        self._starting = False
        self.state_changed.emit("connected")
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
        self._starting = False
        self._timer.stop()
        self.api.close_stream()
        if self.owned and self.process and self.process.state() != QProcess.NotRunning:
            self.process.terminate()
            self._kill_timer.start(8000)
        else:
            self.state_changed.emit("disconnected")
            QTimer.singleShot(0, self, self.stopped.emit)

    def _kill(self):
        if self.process and self.process.state() != QProcess.NotRunning:
            self.process.kill()

    def _finished(self, code, _status):
        self._timer.stop()
        self._kill_timer.stop()
        was_ready, self._ready = self._ready, False
        self._starting = False
        if self._restart:
            self._restart = False
            self.closing = False
            self._spawn()
        elif self.closing:
            self.owned = False
            self.state_changed.emit("disconnected")
            self.stopped.emit()
        else:
            self.owned = False
            self._fail(
                "backend_in_use"
                if code == 73
                else "backend_exited"
                if was_ready
                else "backend_start_failed"
            )
