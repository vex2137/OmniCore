import json
import os
import struct
from importlib.resources import files

import httpx
from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from omnicore.desktop.config import DesktopConfig, config_path, data_path


def request(window, method, path, payload=None):
    # Tests may block; production widgets exclusively use asynchronous Qt networking.
    with httpx.Client(
        base_url=window.api.base_url,
        trust_env=False,
        headers={"Authorization": f"Bearer {window.api._token}"},
    ) as client:
        response = client.request(method, path, json=payload)
        response.raise_for_status()
        return response.json()


def fixture_gguf():
    def string(value):
        encoded = value.encode()
        return struct.pack("<Q", len(encoded)) + encoded

    data = b"GGUF" + struct.pack("<IQQ", 3, 1, 2)
    for key, value in (("general.architecture", "llama"), ("general.name", "GUI fixture")):
        data += string(key) + struct.pack("<I", 8) + string(value)
    data += string("test.weight") + struct.pack("<IQIQ", 1, 4, 0, 0)
    return data + b"\0" * (-len(data) % 32) + struct.pack("<ffff", 0, 0, 0, 0)


def test_start_authenticated_backend_and_close(desktop, qtbot):
    w = desktop
    assert w.session.owned
    pid = w.session.process.processId()
    assert pid
    with httpx.Client(trust_env=False) as client:
        assert client.get(w.api.base_url + "/api/v1/health").status_code == 401
    assert request(w, "GET", "/api/v1/health")["status"] == "ok"
    assert w.api._token not in w.logs.toPlainText()
    w.close()
    qtbot.waitUntil(lambda: w._allow_close, timeout=12000)
    assert w.session.process.state() == QProcess.NotRunning
    assert not __import__("pathlib").Path(f"/proc/{pid}").exists()


def test_conversation_create_rename_delete_history(desktop, qtbot, monkeypatch):
    w = desktop
    qtbot.mouseClick(w.new_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: bool(w.current_id))
    assert w.conversation_list.count() == 1
    identifier = w.current_id
    monkeypatch.setattr(QInputDialog, "getText", lambda *a: ("Moja rozmowa", True))
    w.rename_conversation()
    qtbot.waitUntil(lambda: w.conversation_list.item(0).text() == "Moja rozmowa")
    request(
        w,
        "POST",
        f"/api/v1/text/conversations/{identifier}/messages",
        {"role": "user", "content": "Historia zażółć"},
    )
    w.refresh_messages()
    qtbot.waitUntil(lambda: "Historia zażółć" in w.transcript.toPlainText())
    w.last_job = {"id": "cached-job", "content": "Cached response to delete"}
    w.render_messages()
    assert "Cached response to delete" in w.transcript.toPlainText()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    w.delete_conversation()
    qtbot.waitUntil(lambda: w.conversation_list.count() == 0)
    assert not w.current_id
    assert "Cached response to delete" not in w.transcript.toPlainText()


def test_native_import_and_model_selection_no_ollama(desktop, qtbot, monkeypatch):
    w = desktop
    path = data_path() / "models" / "test.gguf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(fixture_gguf())
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(path), ""))
    w.choose_gguf()
    qtbot.waitUntil(lambda: len(w.models) == 1)
    assert w.models[0]["backend"] == "llama.cpp"
    assert w.models[0]["compatibility"] == "unverified"
    assert path.read_bytes() == fixture_gguf()
    w.model_table.selectRow(0)
    w.model_combo.setCurrentIndex(1)
    w.new_conversation()
    qtbot.waitUntil(lambda: bool(w.current_id))
    assert w.model_combo.currentData() == w.models[0]["id"]
    w.load_model()
    qtbot.waitUntil(lambda: w.load_button.isEnabled(), timeout=10000)
    assert "llama.cpp" in w.notice.text()
    assert w.session.config.ollama_enabled is False


def test_settings_locale_theme_persist_and_restart(desktop, qtbot):
    w = desktop
    w.language.setCurrentIndex(w.language.findData("en-US"))
    assert w.new_button.text() == "＋ New conversation"
    w.theme.setCurrentIndex(w.theme.findData("dark"))
    dark_styles = w.styleSheet()
    assert "#10151f" in dark_styles
    w.theme.setCurrentIndex(w.theme.findData("light"))
    assert "#f5f6fa" in w.styleSheet()
    w.theme.setCurrentIndex(w.theme.findData("system"))
    w.parameter_inputs["max_tokens"].setValue(37)
    w.save_settings()
    saved = DesktopConfig.load()
    assert saved.locale == "en-US" and saved.theme == "system"
    assert saved.parameters["max_tokens"] == 37
    assert os.stat(config_path()).st_mode & 0o777 == 0o600
    w.new_conversation()
    qtbot.waitUntil(lambda: bool(w.current_id))
    identifier = w.current_id
    old_pid = w.session.process.processId()
    w.is_connected = False
    w.session.restart(w.config)
    qtbot.waitUntil(lambda: w.is_connected and not w._health_pending, timeout=20000)
    assert w.session.process.processId() != old_pid
    assert any(c["id"] == identifier for c in w.conversations)
    assert request(w, "GET", "/api/v1/settings")["locale"] == "en-US"


def test_missing_model_error_and_safe_logs(desktop, qtbot):
    w = desktop
    w.new_conversation()
    qtbot.waitUntil(lambda: bool(w.current_id))
    w.composer.setPlainText("secret prompt")
    w.send_message()
    assert w.notice.text() == w.tr("model_required")
    assert "secret prompt" not in w.logs.toPlainText()
    w.show_error("out_of_memory")
    assert w.notice.text() == w.tr("out_of_memory")
    w.log_event("Bearer secret token")
    assert "Bearer" not in w.logs.toPlainText()


def test_catalog_parity_and_format_fields():
    catalogs = [
        json.loads(files("omnicore.desktop").joinpath(f"locales/{locale}.json").read_text())
        for locale in ("en-US", "pl-PL")
    ]
    assert catalogs[0].keys() == catalogs[1].keys()
    from string import Formatter

    for key in catalogs[0]:
        assert catalogs[0][key] and catalogs[1][key]
        fields = [{f for _, f, _, _ in Formatter().parse(c[key]) if f} for c in catalogs]
        assert fields[0] == fields[1], key


def test_reuse_external_backend_never_stops_its_process(desktop, qtbot, monkeypatch):
    from omnicore.desktop.api import ApiClient
    from omnicore.desktop.lifecycle import BackendSession

    owner = desktop.session
    monkeypatch.setenv("OMNICORE_DESKTOP_URL", desktop.api.base_url)
    monkeypatch.setenv("OMNICORE_DESKTOP_TOKEN", desktop.api._token)
    client = ApiClient()
    external = BackendSession(client, DesktopConfig(ollama_enabled=False))
    with qtbot.waitSignal(external.ready, timeout=5000):
        external.start()
    assert not external.owned
    with qtbot.waitSignal(external.stopped, timeout=5000):
        external.stop()
    assert owner.process.state() == QProcess.Running
    assert request(desktop, "GET", "/api/v1/health")["status"] == "ok"
    client.close()


def test_async_transport_sse_handles_fragmented_frames_and_errors(qtbot):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from omnicore.desktop.api import ApiClient

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            # Controlled transport test only. These are not model responses.
            for fragment in (
                b"da",
                b'ta: {"state":"running","content":"a"}\n',
                b"\ndata: ",
                b'{"state":"completed","content":"ab"}\n\n',
            ):
                self.wfile.write(fragment)
                self.wfile.flush()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    api = ApiClient()
    api.configure(f"http://127.0.0.1:{server.server_port}")
    records = []
    api.snapshot.connect(records.append)
    try:
        with qtbot.waitSignal(api.stream_closed, timeout=5000):
            api.watch("controlled-job")
        assert [r["content"] for r in records] == ["a", "ab"]
    finally:
        api.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_second_generation_terminal_sequence_is_not_compared_to_previous_job(desktop):
    w = desktop
    w.last_job = {"id": "previous", "sequence": 1000, "content": "previous response"}
    w.active_job = "new-job"
    w.generation_snapshot({"id": "new-job", "sequence": 3, "state": "cancelled", "content": ""})
    assert w.active_job is None
    assert w.last_job["id"] == "new-job"
    assert w.send_button.isEnabled() and not w.stop_button.isEnabled()


def test_huggingface_controls_require_confirmation_and_send_explicit_payload(desktop, monkeypatch):
    w = desktop
    calls = []
    remote = {
        "repository": "example/model-GGUF",
        "filename": "model.gguf",
        "revision": "abcdef",
        "size_bytes": 123456789,
        "license": "apache-2.0",
    }
    w.hf_files.addItem("model.gguf", remote)
    monkeypatch.setattr(w.api, "request", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
    w.download_file()
    assert not calls
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    w.download_file()
    args, _kwargs = calls[-1]
    assert args[:2] == ("POST", "/api/v1/text/downloads")
    assert args[2] == {
        "repository": remote["repository"],
        "filename": "model.gguf",
        "revision": "abcdef",
        "confirmed": True,
        "expected_size": 123456789,
    }
    w.downloads = [{"id": "download1", "state": "downloading"}]
    w.download_list.addItem("model.gguf", "download1")
    w.cancel_download()
    assert calls[-1][0][:2] == ("POST", "/api/v1/text/downloads/download1/cancel")
    w.resume_download()
    assert calls[-1][0][:2] == ("POST", "/api/v1/text/downloads/download1/resume")


def test_appimage_engine_path_is_rediscovered_after_remount(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    for name in ("mount1", "mount2"):
        directory = tmp_path / name
        (directory / "engines").mkdir(parents=True)
        (directory / "engines/llama-server").write_text("test fixture; not an engine")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "mount1/OmniCore"))
    config = DesktopConfig.load()
    assert Path(config.llama_server).parent.parent.name == "mount1"
    config.save()
    assert json.loads(config_path().read_text())["llama_server"] == ""
    monkeypatch.setattr(sys, "executable", str(tmp_path / "mount2/OmniCore"))
    assert Path(DesktopConfig.load().llama_server).parent.parent.name == "mount2"


def test_platform_selection_respects_session_and_user_override():
    from omnicore.desktop.platforms import configure_platform

    environment = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}
    assert configure_platform(environment) == "wayland;xcb"
    assert configure_platform({"DISPLAY": ":99"}) == "xcb"
    assert configure_platform({"WAYLAND_DISPLAY": "wayland-test"}) == "wayland"
    assert configure_platform({"QT_QPA_PLATFORM": "offscreen", "DISPLAY": ":99"}) == "offscreen"
    assert configure_platform({}) is None


def test_welcome_actions_and_dismissal_persist(desktop, qtbot):
    w = desktop
    assert w.onboarding.isVisible()
    assert w.welcome_import.isEnabled()
    w.dismiss_welcome()
    assert not w.onboarding.isVisible()
    assert DesktopConfig.load().onboarding_complete
    assert w.models == []


def test_reconnect_owned_backend_keeps_process_and_shared_history(desktop, qtbot):
    w = desktop
    w.new_conversation()
    qtbot.waitUntil(lambda: bool(w.current_id))
    identifier = w.current_id
    pid = w.session.process.processId()
    w.show_error("connection_error")
    assert not w.is_connected
    w.reconnect()
    qtbot.waitUntil(lambda: w.is_connected and not w._health_pending, timeout=15000)
    assert w.session.owned and w.session.process.processId() == pid
    assert any(c["id"] == identifier for c in w.conversations)


def test_diagnostic_export_uses_closed_schema_and_private_file(desktop, monkeypatch, tmp_path):
    from omnicore.desktop.report import diagnostic_report

    w = desktop
    marker = "token-and-private-content-should-not-export"
    w.engines = [
        {
            "info": {
                "id": "llama.cpp",
                "available": True,
                "version": marker,
                "resources": {"ram_bytes": 42, "vram_bytes": None, "extra": marker},
            },
            "executable": marker,
        }
    ]
    w.logs.appendPlainText(marker)
    w.composer.setPlainText(marker)
    report = diagnostic_report(w, QApplication.platformName())
    assert marker not in json.dumps(report)
    assert report["engines"][0]["ram_bytes"] == 42
    assert "base_url" not in report and "logs" not in report
    target = tmp_path / "report.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(target), ""))
    w.export_report()
    assert json.loads(target.read_text()) == report
    assert target.stat().st_mode & 0o777 == 0o600
    w.show_error("a" * 64)
    w.log_event("b" * 64)
    assert "a" * 64 not in w.notice.text()
    assert "b" * 64 not in w.logs.toPlainText()


def test_remote_conversation_deletion_clears_shared_cached_history(desktop, qtbot):
    w = desktop
    w.new_conversation()
    qtbot.waitUntil(lambda: bool(w.current_id))
    identifier = w.current_id
    request(
        w,
        "POST",
        f"/api/v1/text/conversations/{identifier}/messages",
        {"role": "user", "content": "shared history"},
    )
    w.refresh_messages()
    qtbot.waitUntil(lambda: "shared history" in w.transcript.toPlainText())
    request(w, "DELETE", f"/api/v1/text/conversations/{identifier}")
    w.refresh_shared_history()
    qtbot.waitUntil(lambda: w.current_id is None)
    assert "shared history" not in w.transcript.toPlainText()
