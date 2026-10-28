"""Asynchronous Qt REST and SSE transport; all callbacks run on the Qt event loop."""

import json

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest


class ApiClient(QObject):
    error = Signal(str)
    snapshot = Signal(dict)
    stream_closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.base_url = ""
        self._token = ""
        self._requests = set()
        self._stream = None
        self._buffer = b""

    def configure(self, url: str, token: str = ""):
        self.base_url, self._token = url.rstrip("/"), token

    def request(self, method, path, payload=None, success=None, failure=None, timeout=15000):
        request = QNetworkRequest(QUrl(self.base_url + path))
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        request.setTransferTimeout(timeout)
        # Never forward authentication to a redirect supplied by an untrusted server.
        request.setAttribute(
            QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy
        )
        if self._token:
            request.setRawHeader(b"Authorization", f"Bearer {self._token}".encode())
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else b""
        reply = self.manager.sendCustomRequest(request, method.encode(), body)
        self._requests.add(reply)

        def finished():
            self._requests.discard(reply)
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            data = bytes(reply.readAll())
            try:
                parsed = json.loads(data) if data else None
            except (ValueError, UnicodeError):
                parsed = None
            if reply.error() != QNetworkReply.NoError or not status or not 200 <= status < 300:
                # Only bounded error codes. Never log response bodies, prompts, URLs or tokens.
                code = "connection_error"
                if isinstance(parsed, dict):
                    detail = parsed.get("error", {})
                    detail = detail.get("code", code) if isinstance(detail, dict) else code
                    if isinstance(detail, str) and detail.replace("_", "").isalnum():
                        code = detail[:80]
                if status in {401, 403}:
                    code = "unauthorized" if status == 401 else code
                (failure or self.error.emit)(code)
            elif success:
                success(parsed)
            reply.deleteLater()

        reply.finished.connect(finished)
        return reply

    def watch(self, job_id):
        self.close_stream()
        self._buffer = b""
        request = QNetworkRequest(QUrl(self.base_url + f"/api/v1/text/generations/{job_id}/stream"))
        if self._token:
            request.setRawHeader(b"Authorization", f"Bearer {self._token}".encode())
        request.setAttribute(
            QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy
        )
        reply = self.manager.get(request)
        self._stream = reply

        def ready():
            if not reply.isOpen():
                return
            self._buffer += bytes(reply.readAll()).replace(b"\r\n", b"\n")
            if len(self._buffer) > 2_000_000:
                self.error.emit("stream_too_large")
                self.close_stream()
                return
            while b"\n\n" in self._buffer:
                event, self._buffer = self._buffer.split(b"\n\n", 1)
                for line in event.splitlines():
                    if line.startswith(b"data: "):
                        try:
                            payload = json.loads(line[6:])
                            self.snapshot.emit(payload)
                        except (ValueError, UnicodeError):
                            self.error.emit("invalid_stream")

        def finished():
            ready()
            if self._stream is reply:
                self._stream = None
                if reply.error() not in {
                    QNetworkReply.NoError,
                    QNetworkReply.OperationCanceledError,
                }:
                    self.error.emit("stream_disconnected")
                self.stream_closed.emit()
            reply.deleteLater()

        reply.readyRead.connect(ready)
        reply.finished.connect(finished)

    def close_stream(self):
        reply, self._stream = self._stream, None
        if reply is not None:
            reply.abort()

    def close(self):
        self.close_stream()
        for reply in tuple(self._requests):
            reply.abort()
