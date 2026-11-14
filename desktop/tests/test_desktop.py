import json
import os
import struct
from importlib.resources import files

import httpx
from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

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


def fixture_gguf(name: str = "GUI fixture"):
    def string(value):
        encoded = value.encode()
        return struct.pack("<Q", len(encoded)) + encoded

    data = b"GGUF" + struct.pack("<IQQ", 3, 1, 2)
    for key, value in (("general.architecture", "llama"), ("general.name", name)):
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
    assert w.new_button.text() == "New chat"
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


def test_native_markdown_code_model_identity_statistics_and_safe_resources(qtbot):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QTextDocument
    from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton

    from omnicore.desktop.i18n import Translator
    from omnicore.desktop.transcript import ChatTranscript, SafeMarkdown

    transcript = ChatTranscript()
    qtbot.addWidget(transcript)
    transcript.resize(650, 700)
    transcript.show()
    source = '# Heading\n\n**Strong**\n\n```python\nprint("hello")\n```\n\n<script>bad()</script>'
    messages = [
        {
            "role": "assistant",
            "content": source,
            "model_name": "Original Qwen",
            "statistics": {
                "output_tokens": 2,
                "ttft_seconds": 0.1,
                "context_used_tokens": 12,
                "context_limit_tokens": 128,
                "finish_reason": "length",
            },
        }
    ]
    transcript.set_messages(messages, Translator("en-US"))
    qtbot.wait(30)
    card = transcript.cards[0]
    assert any(label.text() == "Original Qwen" for label in card.findChildren(QLabel))
    browsers = card.findChildren(SafeMarkdown)
    assert any(
        "Strong" in b.toPlainText() and "**Strong**" not in b.toPlainText() for b in browsers
    )
    stat_labels = card.findChildren(QLabel)
    assert any(
        "2 tok." in label.text() and "token limit" in label.toolTip() for label in stat_labels
    )
    assert any(
        "0.10 s TTFT" in label.text() and "token limit" in label.toolTip() for label in stat_labels
    )
    assert card.findChild(QPlainTextEdit).toPlainText() == 'print("hello")'
    copy = next(button for button in card.findChildren(QPushButton) if button.text() == "Copy code")
    qtbot.mouseClick(copy, Qt.LeftButton)
    assert QApplication.clipboard().text() == 'print("hello")'
    for url in ["file:///etc/passwd", "https://example.com/image.png", "data:image/png;base64,AA"]:
        assert browsers[0].loadResource(QTextDocument.ImageResource, QUrl(url)) is None
    transcript.set_messages(messages, Translator("pl-PL"))
    assert any(
        label.text() == "Original Qwen" for label in transcript.cards[0].findChildren(QLabel)
    )
    transcript.set_messages([{"role": "assistant", "content": "Old history"}], Translator("en-US"))
    assert any(label.text() == "Assistant" for label in transcript.cards[0].findChildren(QLabel))


def test_history_search_uses_backend_message_content_without_losing_selection(desktop, qtbot):
    w = desktop
    first = request(w, "POST", "/api/v1/text/conversations", {"title": "First"})
    second = request(w, "POST", "/api/v1/text/conversations", {"title": "Second"})
    request(
        w,
        "POST",
        f"/api/v1/text/conversations/{first['id']}/messages",
        {"role": "user", "content": "Unique searchable phrase"},
    )
    w.refresh_conversations(select=second["id"])
    qtbot.waitUntil(lambda: w.current_id == second["id"])
    w.history_search.setText("searchable")
    qtbot.waitUntil(lambda: w.conversation_list.count() == 1)
    assert w.conversation_list.item(0).data(Qt.UserRole) == first["id"]
    assert w.current_id == second["id"]
    w.history_search.clear()
    qtbot.waitUntil(lambda: w.conversation_list.count() == 2)


def test_processing_selector_hides_technical_paths_and_preserves_manual_choice(desktop, qtbot):
    w = desktop
    assert not w.advanced_settings.isVisible()
    w.navigate(2)
    w.device.setCurrentIndex(w.device.findData("cpu"))
    w.save_settings()
    assert DesktopConfig.load().parameters["device"] == "cpu"
    assert DesktopConfig.load().parameters["gpu_layers"] == 0
    w.device.setCurrentIndex(w.device.findData("auto"))
    assert w.parameter_inputs["gpu_layers"].value() == 99
    w.save_settings()
    assert DesktopConfig.load().parameters["device"] == "auto"
    w.advanced_toggle.click()
    assert w.advanced_settings.isVisible()


def test_long_history_is_incremental_and_earlier_messages_remain_accessible(qtbot):
    from omnicore.desktop.i18n import Translator
    from omnicore.desktop.transcript import ChatTranscript

    widget = ChatTranscript()
    qtbot.addWidget(widget)
    messages = [{"id": str(i), "role": "user", "content": f"Message {i}"} for i in range(180)]
    widget.set_messages(messages, Translator("en-US"))
    assert len(widget.cards) == 60 and widget.cards[0].message["id"] == "120"
    assert "Message 0" in widget.toPlainText()
    widget.more.click()
    assert len(widget.cards) == 120
    widget.more.click()
    assert len(widget.cards) == 180


def test_model_tabs_separate_transfers(desktop):
    tabs = desktop.model_tabs
    assert tabs.count() == 3
    assert desktop.download_list.parentWidget() is tabs.widget(2)
    assert desktop.download_button.parentWidget() is not tabs.widget(2)


def test_desktop_theme_variants_survive_reload(desktop, tmp_path):
    config_file = tmp_path / "desktop.json"
    for name in ("system", "light", "midnight", "graphite", "oled", "ocean", "forest"):
        index = desktop.theme.findData(name)
        assert index >= 0
        desktop.theme.setCurrentIndex(index)
        assert desktop.config.theme == name
        desktop.config.save(config_file)
        assert DesktopConfig.load(config_file).theme == name


def test_sidebar_compact_preserves_history_and_setting(desktop, qtbot, tmp_path):
    w = desktop
    assert w.sidebar.width() == 232
    qtbot.mouseClick(w.sidebar_toggle, Qt.LeftButton)
    assert w.sidebar.width() == 60
    assert w.history_panel.isHidden()
    path = tmp_path / "desktop.json"
    w.config.save(path)
    assert DesktopConfig.load(path).sidebar_compact
    qtbot.mouseClick(w.sidebar_toggle, Qt.LeftButton)
    assert w.sidebar.width() == 232
    assert not w.history_panel.isHidden()


def test_sidebar_width_is_persistent_and_restored_after_compacting(desktop, tmp_path):
    window = desktop
    window.sidebar_width.setValue(280)
    assert window.sidebar.width() == 280
    window.toggle_sidebar()
    assert window.sidebar.width() == 60
    window.toggle_sidebar()
    assert window.sidebar.width() == 280
    path = tmp_path / "prefs.json"
    window.config.save(path)
    assert DesktopConfig.load(path).sidebar_width == 280


def test_regeneration_branches_without_deleting_original(desktop, qtbot, monkeypatch):
    w = desktop
    record = request(w, "POST", "/api/v1/text/conversations", {"title": "Original"})
    source = record["id"]
    url = f"/api/v1/text/conversations/{source}"
    for role, content in (
        ("user", "First"),
        ("assistant", "One"),
        ("user", "Second"),
        ("assistant", "Two"),
    ):
        request(w, "POST", url + "/messages", {"role": role, "content": content})
    w.current_id = source
    captured = []
    monkeypatch.setattr(w, "send_message", lambda: captured.append(w.composer.toPlainText()))
    w.regenerate_answer()
    qtbot.waitUntil(lambda: bool(captured))
    assert captured == ["Second"]
    assert w.current_id != source
    original = request(w, "GET", url + "/messages")
    assert [m["content"] for m in original] == ["First", "One", "Second", "Two"]
    branch = request(w, "GET", f"/api/v1/text/conversations/{w.current_id}/messages")
    assert [m["content"] for m in branch] == ["First", "One"]


def test_context_meter_uses_last_request_not_history(desktop):
    w = desktop
    w.messages = [
        {
            "role": "assistant",
            "content": "Answer",
            "statistics": {
                "context_used_tokens": 128,
                "context_limit_tokens": 512,
                "execution_device": "CUDA0",
                "gpu_offloaded_layers": 25,
            },
        }
    ]
    w.render_messages()
    assert w.context_meter.value() == 25
    assert "128/512" in w.context_usage.text()
    assert "GPU" in w.context_usage.text()
    w.messages = [{"role": "user", "content": "A long history" * 100}]
    w.render_messages()
    assert w.context_meter.isHidden()
    assert "128/512" not in w.context_usage.text()


def test_pin_updates_real_history_without_duplicates(desktop, qtbot):
    w = desktop
    record = request(w, "POST", "/api/v1/text/conversations", {"title": "Pin me"})
    w.refresh_conversations(record["id"])
    qtbot.waitUntil(lambda: len(w.conversations) == 1)
    w.pin_conversation(record)
    qtbot.waitUntil(lambda: bool(w.conversations[0].get("pinned")))
    assert w.conversation_list.count() == 1
    assert request(w, "GET", f"/api/v1/text/conversations/{record['id']}")["pinned"]


def test_capture_real_sidebar_chat_if_requested(desktop, qtbot):
    from pathlib import Path

    output = os.environ.get("OMNICORE_VISUAL_OUTPUT")
    if not output:
        return
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    w = desktop
    w.onboarding.hide()
    record = request(w, "POST", "/api/v1/text/conversations", {"title": "RC8 — UI review"})
    url = f"/api/v1/text/conversations/{record['id']}"
    for role, content in (
        ("user", "How do I connect a local GGUF model?"),
        (
            "assistant",
            "## Local models\n\n1. Import your GGUF.\n2. Select the engine.\n\n"
            "```python\nprint('OmniCore')\n```",
        ),
    ):
        request(w, "POST", url + "/messages", {"role": role, "content": content})
    request(w, "PATCH", url, {"pinned": True})
    w.refresh_conversations(record["id"])
    qtbot.waitUntil(lambda: len(w.messages) == 2)
    for width, height in ((1280, 720), (1366, 768), (1920, 1080), (2560, 1440)):
        w.resize(width, height)
        qtbot.wait(100)
        assert w.grab().save(str(destination / f"chat-{width}x{height}.png"))
    w.toggle_sidebar()
    qtbot.wait(100)
    assert w.grab().save(str(destination / "chat-compact.png"))


def test_composer_enter_shift_enter_and_growth(qtbot):
    from omnicore.desktop.composer import Composer

    composer = Composer()
    qtbot.addWidget(composer)
    composer.show()
    composer.setPlainText("Draft")
    with qtbot.waitSignal(composer.submitted):
        qtbot.keyClick(composer, Qt.Key_Return)
    assert composer.toPlainText() == "Draft"
    qtbot.keyClick(composer, Qt.Key_Return, Qt.ShiftModifier)
    assert "\n" in composer.toPlainText()
    composer.setPlainText("Line\n" * 50)
    assert 72 <= composer.height() <= 160


def test_model_search_sort_favorites_and_selection(desktop, tmp_path):
    w = desktop
    w.models = [
        dict(
            id=str(i),
            backend="llama.cpp",
            name=name,
            size_bytes=size,
            compatibility="unverified",
            format="GGUF",
            quantization="Q4_K_M",
            location="/fixture",
            metadata={"architecture": "llama"},
        )
        for i, (name, size) in enumerate((("Zulu", 300), ("Alpha", 100), ("Beta", 200)))
    ]
    w.refresh_model_table()
    assert w.selected_model()["name"] == "Alpha"
    w.model_sort.setCurrentIndex(w.model_sort.findData("sort_size"))
    assert w.model_table.item(0, 0).data(Qt.UserRole) == "0"
    w.model_search.setText("beta")
    assert w.model_table.rowCount() == 1
    assert w.selected_model()["name"] == "Beta"
    w.toggle_favorite_model()
    w.model_search.clear()
    w.favorites_only.setChecked(True)
    assert w.model_table.rowCount() == 1
    path = tmp_path / "preferences.json"
    w.config.save(path)
    assert DesktopConfig.load(path).favorite_models == ["2"]
    w.toggle_favorite_model()
    assert w.model_table.rowCount() == 0
    assert not w.models_empty.isHidden()
    w.favorites_only.setChecked(False)
    w.models[0]["name"] = "<img src=file:///private>"
    w.model_search.setText("<img")
    assert "&lt;img" in w.model_table.item(0, 0).toolTip()


def test_history_groups_collapse_without_losing_records(desktop, qtbot, tmp_path):
    w = desktop
    for title in ("One", "Two"):
        request(w, "POST", "/api/v1/text/conversations", {"title": title})
    w.refresh_conversations()
    qtbot.waitUntil(lambda: w.conversation_list.count() == 2)
    w.toggle_history_group("today")
    assert not w.conversation_list.item(0).isHidden()
    assert w.conversation_list.item(1).isHidden()
    path = tmp_path / "prefs.json"
    w.config.save(path)
    assert "today" in DesktopConfig.load(path).collapsed_history
    w.toggle_history_group("today")
    assert not w.conversation_list.item(1).isHidden()
    assert len(request(w, "GET", "/api/v1/text/conversations")) == 2


def test_theme_previews_and_accent_persist(desktop, monkeypatch, tmp_path):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QColorDialog

    w = desktop
    assert w.theme.count() == 7
    assert all(not w.theme.itemIcon(i).isNull() for i in range(7))
    monkeypatch.setattr(QColorDialog, "getColor", lambda *args: QColor("#24aabb"))
    w.choose_accent()
    path = tmp_path / "prefs.json"
    w.config.save(path)
    assert DesktopConfig.load(path).accent == "#24aabb"
    assert "#24aabb" in w.styleSheet()
    w.reset_accent()
    assert w.config.accent == ""


def test_context_details_disclose_actual_data(desktop, qtbot):
    w = desktop
    w.messages = [
        {
            "role": "assistant",
            "content": "Answer",
            "statistics": {
                "input_tokens": 120,
                "output_tokens": 30,
                "context_used_tokens": 150,
                "context_limit_tokens": 2048,
                "finish_reason": "stop",
            },
        }
    ]
    w.render_messages()
    qtbot.mouseClick(w.context_toggle, Qt.LeftButton)
    assert not w.context_details.isHidden()
    assert "120" in w.context_details.text() and "150/2048" in w.context_details.text()
    qtbot.mouseClick(w.context_toggle, Qt.LeftButton)
    assert w.context_details.isHidden()


def test_assistant_footer_regenerates_specific_message(qtbot):
    from PySide6.QtWidgets import QToolButton

    from omnicore.desktop.i18n import Translator
    from omnicore.desktop.transcript import ChatTranscript

    transcript = ChatTranscript()
    qtbot.addWidget(transcript)
    transcript.can_regenerate = True
    message = {"id": "first", "role": "assistant", "content": "Original answer"}
    transcript.set_messages([message], Translator("en-US"))
    retry = next(
        b
        for b in transcript.cards[0].findChildren(QToolButton)
        if b.accessibleName() == "Regenerate"
    )
    with qtbot.waitSignal(transcript.regenerate_requested) as signal:
        qtbot.mouseClick(retry, Qt.LeftButton)
    assert signal.args == [message]


def test_regeneration_from_earlier_answer_uses_earlier_history(desktop, qtbot, monkeypatch):
    w = desktop
    record = request(w, "POST", "/api/v1/text/conversations", {"title": "Original"})
    source = record["id"]
    url = f"/api/v1/text/conversations/{source}"
    messages = [
        request(w, "POST", url + "/messages", {"role": role, "content": content})
        for role, content in (
            ("user", "First"),
            ("assistant", "One"),
            ("user", "Second"),
            ("assistant", "Two"),
        )
    ]
    w.current_id = source
    captured = []
    monkeypatch.setattr(w, "send_message", lambda: captured.append(w.composer.toPlainText()))
    w.regenerate_answer(messages[1])
    qtbot.waitUntil(lambda: bool(captured))
    assert captured == ["First"]
    assert request(w, "GET", f"/api/v1/text/conversations/{w.current_id}/messages") == []
    assert len(request(w, "GET", url + "/messages")) == 4


def test_capture_new_rc8_views_if_requested(desktop, qtbot):
    from pathlib import Path

    output = os.environ.get("OMNICORE_VISUAL_OUTPUT")
    if not output:
        return
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    w = desktop
    w.onboarding.hide()
    for name in ("Local GGUF UI fixture", "Second local UI fixture"):
        path = data_path() / "models" / (name + ".gguf")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fixture_gguf())
        request(w, "POST", "/api/v1/text/models/import", {"path": str(path)})
    w.refresh_models()
    qtbot.waitUntil(lambda: len(w.models) == 2)
    w.navigate(1)
    qtbot.wait(150)
    assert w.grab().save(str(destination / "my-models.png"))
    w.navigate(2)
    w.theme.setCurrentIndex(w.theme.findData("ocean"))
    qtbot.wait(150)
    assert w.grab().save(str(destination / "appearance-settings.png"))
    w.theme.showPopup()
    qtbot.wait(100)
    assert w.theme.view().grab().save(str(destination / "all-theme-previews.png"))
    w.theme.hidePopup()
    w.navigate(0)
    for title in ("First review", "Second review"):
        request(w, "POST", "/api/v1/text/conversations", {"title": title})
    w.refresh_conversations()
    qtbot.waitUntil(lambda: len(w.conversations) == 2)
    w.toggle_history_group("today")
    qtbot.wait(100)
    assert w.grab().save(str(destination / "collapsed-history.png"))
    w.context_toggle.setChecked(True)
    qtbot.wait(100)
    assert w.grab().save(str(destination / "context-details-unavailable.png"))


def test_chat_header_stays_aligned_across_modes_and_scales(desktop, qtbot):
    w = desktop
    w.resize(1100, 760)
    w.show()
    qtbot.waitExposed(w)
    for scale in (80, 100, 150):
        w.ui_scale.setValue(scale)
        qtbot.wait(50)
        w.agent_panel.mode.setCurrentIndex(w.agent_panel.mode.findData("chat"))
        qtbot.wait(30)
        chat_geometries = (
            w.model_combo.geometry(),
            w.agent_panel.mode.geometry(),
            w.context_button.geometry(),
            w.chat_refresh.geometry(),
        )
        w.agent_panel.mode.setCurrentIndex(w.agent_panel.mode.findData("agent"))
        qtbot.wait(30)
        agent_geometries = (
            w.model_combo.geometry(),
            w.agent_panel.mode.geometry(),
            w.context_button.geometry(),
            w.chat_refresh.geometry(),
        )
        assert chat_geometries == agent_geometries
        assert not w.agent_panel.settings_toggle.isVisible()

    w.agent_panel.mode.setCurrentIndex(w.agent_panel.mode.findData("chat"))
    w.context_button.setChecked(True)
    qtbot.wait(20)
    assert w.context_controls.isVisible()
    assert not w.agent_panel.details.isVisible()

    w.agent_panel.mode.setCurrentIndex(w.agent_panel.mode.findData("agent"))
    qtbot.wait(20)
    assert w.context_controls.isVisible()
    assert w.agent_panel.details.isVisible()


def test_history_header_search_toggles_focuses_and_filters(desktop, qtbot):
    w = desktop
    w.resize(1100, 760)
    w.show()
    qtbot.waitExposed(w)
    first = request(w, "POST", "/api/v1/text/conversations", {"title": "Alpha Topic"})
    second = request(w, "POST", "/api/v1/text/conversations", {"title": "Beta Topic"})
    request(
        w,
        "POST",
        f"/api/v1/text/conversations/{second['id']}/messages",
        {"role": "user", "content": "needle_in_message_body"},
    )
    w.refresh_conversations()
    qtbot.waitUntil(lambda: len(w.conversations) == 2)
    assert w.nav[0].isVisible()
    assert not w.history_search.isVisible()

    qtbot.mouseClick(w.history_search_toggle, Qt.LeftButton)
    qtbot.wait(20)
    assert not w.nav[0].isVisible()
    assert w.history_search.isVisible()
    assert w.history_search.hasFocus()

    w.history_search.setText("needle_in_message_body")
    qtbot.waitUntil(lambda: [c["id"] for c in w.conversations] == [second["id"]])

    qtbot.keyClick(w.history_search, Qt.Key_Escape)
    qtbot.waitUntil(lambda: len(w.conversations) == 2)
    assert w.nav[0].isVisible()
    assert not w.history_search.isVisible()
    assert w.history_search.text() == ""
    assert first["id"] in {c["id"] for c in w.conversations}


def test_history_toolbar_controls_fit_narrow_and_expanded_widths(desktop, qtbot):
    w = desktop
    w.resize(1100, 760)
    w.show()
    qtbot.waitExposed(w)
    for width, scale in ((200, 100), (200, 150), (260, 100), (340, 120)):
        w.ui_scale.setValue(scale)
        w.sidebar_width.setValue(width)
        w.resize_sidebar(width)
        qtbot.wait(25)
        for btn in (w.nav[0], w.history_search_toggle, w.history_refresh, w.history_menu_btn):
            assert btn.isVisible()
            assert btn.width() >= btn.minimumSizeHint().width()
        if width >= 260 and scale <= 120:
            assert w.history_search_toggle.text() != ""
        # Dedicated toolbar sits below the Conversations button without overlapping it.
        toolbar_top = w.history_panel.geometry().top() + w.history_search_toggle.geometry().top()
        assert w.nav[0].geometry().bottom() <= toolbar_top
        # No horizontal overlap between search trigger, refresh, and menu controls.
        assert w.history_search_toggle.geometry().right() < w.history_refresh.geometry().left()
        assert w.history_refresh.geometry().right() < w.history_menu_btn.geometry().left()
        assert w.history_menu_btn.geometry().right() <= w.sidebar.width()

        # Open compact search row and verify height, focus, and right-aligned utility buttons.
        w.open_history_search()
        qtbot.wait(25)
        assert w.history_search.isVisible()
        assert w.history_search_close.isVisible()
        assert not w.history_search_toggle.isVisible()
        assert not w.nav[0].isVisible()
        assert w.history_search.height() >= 26
        assert w.history_search.geometry().right() < w.history_search_close.geometry().left()
        assert w.history_search_close.geometry().right() <= w.sidebar.width()
        assert w.history_panel.geometry().top() >= w.history_search.geometry().bottom()
        assert w.history_refresh.geometry().right() < w.history_menu_btn.geometry().left()
        assert w.history_menu_btn.geometry().right() <= w.history_panel.width()
        assert w.history_refresh.geometry().left() >= w.history_toolbar_spacer.geometry().right()

        # Closing search restores the search trigger cleanly.
        w.close_history_search()
        qtbot.wait(25)
        assert not w.history_search.isVisible()
        assert w.history_search_toggle.isVisible()

    w.toggle_sidebar()
    qtbot.wait(20)
    assert w.config.sidebar_compact is True
    assert not w.history_panel.isVisible()
    assert w.nav[0].isVisible()
    w.toggle_sidebar()
    qtbot.wait(20)
    assert w.history_panel.isVisible()
    assert w.history_search_toggle.isVisible()


def test_history_group_rows_do_not_overlap_headings_or_titles(desktop, qtbot):
    w = desktop
    w.resize(1100, 760)
    w.show()
    qtbot.waitExposed(w)
    request(w, "POST", "/api/v1/text/conversations", {"title": "Very Long Conversation Title"})
    w.refresh_conversations()
    qtbot.waitUntil(lambda: w.conversation_list.count() == 1)
    for scale in (100, 150):
        w.ui_scale.setValue(scale)
        qtbot.wait(50)
        item = w.conversation_list.item(0)
        row = w.conversation_list.itemWidget(item)
        assert row is not None
        row.adjustSize()
        row.layout().activate()
        heading = row.findChild(QPushButton, "historyHeading")
        title_row = row.findChild(QWidget, "historyTitleRow")
        title = row.findChild(QLabel, "historyItemTitle")
        assert heading is not None and title_row is not None and title is not None
        assert heading.geometry().bottom() < title_row.geometry().top()
        assert item.sizeHint().height() >= title_row.geometry().bottom()


def test_history_multigroup_real_rendered_geometry_across_scales(desktop, qtbot):
    from datetime import UTC, datetime, timedelta

    w = desktop
    w.resize(1280, 760)
    w.show()
    qtbot.waitExposed(w)
    now = datetime.now(UTC)
    offsets = (
        ("today", "Dzisiaj rozmowa pierwsza", timedelta(hours=1)),
        ("yesterday", "Wczoraj rozmowa druga", timedelta(days=1, hours=2)),
        ("week", "Ostatnie 7 dni rozmowa", timedelta(days=4)),
        ("month", "Ostatnie 30 dni rozmowa", timedelta(days=15)),
        ("older", "Starsza rozmowa archiwalna", timedelta(days=45)),
    )
    for _group, title, _delta in offsets:
        request(w, "POST", "/api/v1/text/conversations", {"title": title})
    w.refresh_conversations()
    qtbot.waitUntil(lambda: len(w.conversations) == 5)
    for idx, (_group, _title, delta) in enumerate(offsets):
        w.conversations[idx]["updated_at"] = (now - delta).isoformat()
    w._fill_conversations()
    QApplication.processEvents()

    for scale in (80, 90, 100, 125, 150):
        w.ui_scale.setValue(scale)
        qtbot.wait(50)
        QApplication.processEvents()
        if scale in (100, 125) and (cap := os.environ.get("OMNICORE_CAPTURE_DIR")):
            w.grab().save(f"{cap}/verify_multigroup_{scale}.png")
        headings = []
        for i in range(w.conversation_list.count()):
            item = w.conversation_list.item(i)
            row = w.conversation_list.itemWidget(item)
            assert row is not None
            rect = w.conversation_list.visualItemRect(item)
            assert rect.height() >= row.height()
            heading = row.findChild(QPushButton, "historyHeading")
            title_lbl = row.findChild(QLabel, "historyItemTitle")
            assert heading is not None and title_lbl is not None
            headings.append(heading)
            assert heading.isVisible()
            assert heading.height() >= heading.fontMetrics().height() + 4
            assert title_lbl.height() >= title_lbl.fontMetrics().height() + 4
            title_row = row.findChild(QWidget, "historyTitleRow")
            assert title_row is not None
            assert heading.geometry().bottom() < title_row.geometry().top()
            assert row.height() >= title_row.geometry().bottom()
        assert len({h.height() for h in headings}) == 1


def test_model_selector_popup_tooltip_and_responsive_header(desktop, qtbot):
    w = desktop
    w.show()
    qtbot.waitExposed(w)
    names = [
        "LFM3-1.7B-Q8_0.gguf",
        "DeepSeek-V4-Pro-Qwen3.5-9B-UNCENSORED-heretic.i1-Q4_K_M.gguf",
    ]
    models_dir = data_path() / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        path = models_dir / name
        path.write_bytes(fixture_gguf(name[:-5]))
        request(w, "POST", "/api/v1/text/models/import", {"path": str(path)})
    w.refresh_models()
    qtbot.waitUntil(lambda: w.model_combo.count() >= 3)

    idx = next(
        i
        for i in range(w.model_combo.count())
        if "DeepSeek-V4-Pro-Qwen3.5-9B-UNCENSORED-heretic" in w.model_combo.itemText(i)
    )
    w.model_combo.setCurrentIndex(idx)
    full_label = w.model_combo.itemText(idx)
    assert w.model_combo.toolTip() == full_label
    assert w.model_combo.itemData(idx, Qt.ToolTipRole) == full_label

    w.model_combo.showPopup()
    QApplication.processEvents()
    needed = w.model_combo.view().fontMetrics().horizontalAdvance(full_label)
    assert w.model_combo.view().minimumWidth() >= min(needed, w.width() - 48)
    w.model_combo.hidePopup()

    for width, height in ((1024, 720), (1440, 900), (1920, 1080)):
        w.resize(width, height)
        QApplication.processEvents()
        w.agent_panel.mode.setCurrentIndex(0)
        QApplication.processEvents()
        chat_geos = (
            w.model_combo.geometry(),
            w.agent_panel.mode.geometry(),
            w.context_button.geometry(),
            w.chat_refresh.geometry(),
        )
        assert chat_geos[0].width() >= 140
        assert chat_geos[0].right() <= chat_geos[1].left()
        assert chat_geos[1].right() <= chat_geos[2].left()
        assert chat_geos[2].right() <= chat_geos[3].left()
        w.agent_panel.mode.setCurrentIndex(1)
        QApplication.processEvents()
        agent_geos = (
            w.model_combo.geometry(),
            w.agent_panel.mode.geometry(),
            w.context_button.geometry(),
            w.chat_refresh.geometry(),
        )
        assert chat_geos == agent_geos


def test_expandable_error_card_in_notice_and_transcript(desktop, qtbot):
    from PySide6.QtWidgets import QFrame, QToolButton

    w = desktop
    w.show()
    qtbot.waitExposed(w)

    w.show_error("out_of_memory", component="llama.cpp", target="DeepSeek-V4")
    assert w.notice_card.isVisible()
    assert w.notice.text() == w.tr("out_of_memory")
    assert w.notice_details_toggle.isVisible()
    assert not w.notice_details_frame.isVisible()

    qtbot.mouseClick(w.notice_details_toggle, Qt.LeftButton)
    QApplication.processEvents()
    assert w.notice_details_frame.isVisible()
    details = w.notice_details_label.text()
    assert "out_of_memory" in details
    assert "llama.cpp (DeepSeek-V4)" in details

    w.show_error("Traceback (most recent call last) token=SECRET_123")
    assert "SECRET_123" not in w.notice.text()
    assert "SECRET_123" not in w.notice_details_label.text()
    assert "unknown_error" in w.notice_details_label.text()

    qtbot.mouseClick(w.notice_close, Qt.LeftButton)
    assert not w.notice_card.isVisible()

    w.messages = [
        {"role": "user", "content": "test"},
        {
            "role": "assistant",
            "content": "",
            "status": "failed",
            "error_code": "agent_context_limit",
            "model_name": "DeepSeek-V4",
        },
    ]
    w.render_messages()
    QApplication.processEvents()
    cards = w.transcript.findChildren(QFrame, "errorCard")
    assert len(cards) == 1
    toggle = cards[0].findChild(QPushButton, "compactToggle")
    box = cards[0].findChild(QFrame, "errorDetailsBox")
    assert toggle is not None and box is not None
    assert not box.isVisible()
    qtbot.mouseClick(toggle, Qt.LeftButton)
    assert box.isVisible()
    labels = "\n".join(lbl.text() for lbl in box.findChildren(QLabel))
    assert "agent_context_limit" in labels
    assert isinstance(w.notice_close, QToolButton)


def test_message_statistics_summary_details_and_missing_dash(desktop, qtbot):
    from PySide6.QtWidgets import QFrame

    w = desktop
    w.show()
    qtbot.waitExposed(w)
    w.messages = [
        {
            "role": "assistant",
            "content": "Complete stats reply",
            "model_name": "DeepSeek-V4",
            "statistics": {
                "ttft_seconds": 0.25,
                "tokens_per_second": 31.5,
                "input_tokens": 40,
                "output_tokens": 120,
                "total_tokens": 160,
                "generation_seconds": 3.81,
                "total_task_seconds": 4.9,
                "model_load_seconds": 1.05,
                "execution_model": "DeepSeek-V4",
                "execution_device": "gpu",
                "gpu_offloaded_layers": 24,
                "gpu_total_layers": 40,
                "gpu_offload_mode": "auto",
                "context_used_tokens": 160,
                "context_limit_tokens": 8192,
                "finish_reason": "stop",
            },
        },
        {
            "role": "assistant",
            "content": "Partial stats reply",
            "model_name": "Tiny",
            "statistics": {
                "output_tokens": 12,
                "execution_device": "cpu",
            },
        },
    ]
    w.render_messages()
    QApplication.processEvents()

    detail_boxes = w.transcript.findChildren(QFrame, "messageStatsDetails")
    assert len(detail_boxes) == 2
    first_text = "\n".join(lbl.text() for lbl in detail_boxes[0].findChildren(QLabel))
    assert "160" in first_text
    assert "24/40" in first_text
    assert "auto" in first_text
    assert w.tr("finish_stop") in first_text

    second_text = "\n".join(lbl.text() for lbl in detail_boxes[1].findChildren(QLabel))
    assert "—" in second_text
    assert "0.00 s" not in second_text


def test_resource_monitor_widgets_and_proc_helpers(desktop, qtbot, tmp_path):
    from omnicore.desktop.resources import (
        ResourceSnapshot,
        compute_cpu_percent,
        find_related_pids,
        read_meminfo,
    )

    assert compute_cpu_percent((100, 1000), (150, 1200)) == 75.0
    mem_file = tmp_path / "meminfo"
    mem_file.write_text("MemTotal:       16777216 kB\nMemAvailable:    8388608 kB\n")
    used, total = read_meminfo(mem_file)
    assert total == 16777216 * 1024 and used == 8388608 * 1024

    proc = tmp_path / "proc"
    for pid, name, ppid in (
        (100, "omnicore", 1),
        (101, "uvicorn", 100),
        (102, "llama-server", 101),
        (999, "unrelated", 1),
    ):
        d = proc / str(pid)
        d.mkdir(parents=True)
        (d / "stat").write_text(f"{pid} ({name}) S {ppid} 1 1 0")
    app_pids, engine_pids = find_related_pids([100], proc_root=proc)
    assert app_pids == {100, 101}
    assert engine_pids == {102}

    w = desktop
    w.show()
    qtbot.waitExposed(w)

    snap = ResourceSnapshot(
        cpu_percent=42.0,
        cpu_temp_c=61.0,
        ram_used_bytes=8 * 1024**3,
        ram_total_bytes=32 * 1024**3,
        gpu_name="RTX 4060",
        gpu_util_percent=None,
        vram_used_bytes=None,
        vram_total_bytes=None,
        app_ram_bytes=250 * 1024**2,
        engine_ram_bytes=900 * 1024**2,
        engine_vram_bytes=None,
    )
    w._apply_resource_snapshot(snap)
    summary = w.resource_monitor_btn.text()
    assert "42%" in summary
    assert "61°C" in summary
    assert "GPU: —" in summary and "VRAM: —" in summary

    assert not w.resource_details_frame.isVisible()
    qtbot.mouseClick(w.resource_monitor_btn, Qt.LeftButton)
    assert w.resource_details_frame.isVisible()
    assert "llama-server" in w.resource_details_label.text()

    w.close()
    assert w.resource_monitor._thread is None


def test_history_menu_delete_all_conversations_with_confirmation(desktop, qtbot, monkeypatch):
    w = desktop
    w.show()
    qtbot.waitExposed(w)

    models_dir = data_path() / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    gguf_path = models_dir / "kept-for-history-test.gguf"
    gguf_path.write_bytes(fixture_gguf("Kept Model"))
    imported = request(w, "POST", "/api/v1/text/models/import", {"path": str(gguf_path)})
    w.refresh_models()
    qtbot.waitUntil(lambda: any(m["id"] == imported["id"] for m in w.models))

    for title in ("First chat", "Second chat"):
        created = request(
            w, "POST", "/api/v1/text/conversations", {"title": title, "model_id": imported["id"]}
        )
        request(
            w,
            "POST",
            f"/api/v1/text/conversations/{created['id']}/messages",
            {"role": "user", "content": f"Message in {title}"},
        )
    w.refresh_conversations()
    qtbot.waitUntil(lambda: len(w.conversations) == 2 and bool(w.current_id))

    assert w.history_menu_btn.isVisible()
    menu = w._build_history_menu()
    texts = [action.text() for action in menu.actions() if not action.isSeparator()]
    assert w.tr("delete_selected_conversation") in texts
    assert w.tr("delete_all_conversations") in texts
    assert all(action.isEnabled() for action in menu.actions() if not action.isSeparator())

    # Cancelling confirmation preserves all conversations.
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Cancel)
    w.delete_all_conversations()
    QApplication.processEvents()
    assert len(w.conversations) == 2

    # Active generation prevents destructive deletion cleanly.
    w.active_job = "busy-job"
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    w.delete_all_conversations()
    assert w.notice_card.isVisible()
    assert w.notice.text() == w.tr("conversation_busy")
    assert len(w.conversations) == 2
    w.active_job = None

    # Confirmed deletion clears conversations, messages, and sidebar while preserving models.
    w.delete_all_conversations()
    qtbot.waitUntil(lambda: len(w.conversations) == 0 and w.conversation_list.count() == 0)
    assert w.current_id is None
    assert w.messages == []
    assert w.notice.text() == w.tr("all_conversations_deleted")
    assert gguf_path.exists()
    assert any(m["id"] == imported["id"] for m in w.models)


def test_gpu_offload_mode_controls_and_preserves_context(desktop, qtbot):
    w = desktop
    w.navigate(2)

    modes = [w.gpu_offload_mode.itemData(i) for i in range(w.gpu_offload_mode.count())]
    assert modes == ["auto", "max", "manual", "cpu"]

    # Default auto disables manual gpu_layers spinbox.
    assert w.gpu_offload_mode.currentData() == "auto"
    assert not w.parameter_inputs["gpu_layers"].isEnabled()

    # Manual enables spinbox and persists explicit layer count.
    w.gpu_offload_mode.setCurrentIndex(w.gpu_offload_mode.findData("manual"))
    assert w.parameter_inputs["gpu_layers"].isEnabled()
    w.parameter_inputs["gpu_layers"].setValue(24)
    w.save_settings()
    saved = DesktopConfig.load().parameters
    assert saved["gpu_offload_mode"] == "manual"
    assert saved["gpu_layers"] == 24

    # Manual model context is preserved regardless of gpu_offload_mode.
    fake_gguf = {"id": "gguf-1", "backend": "llama.cpp", "metadata": {"context_length": 32768}}
    w.model_contexts["gguf-1"] = {
        "mode": "manual",
        "effective_tokens": 16384,
        "automatic_tokens": 8192,
    }
    params_manual = w._parameters_for_model(fake_gguf)
    assert params_manual["context_size"] == 16384
    assert params_manual["gpu_offload_mode"] == "manual"

    # Max GPU mode disables spinbox and saves max mode while preserving context.
    w.gpu_offload_mode.setCurrentIndex(w.gpu_offload_mode.findData("max"))
    assert not w.parameter_inputs["gpu_layers"].isEnabled()
    w.save_settings()
    saved = DesktopConfig.load().parameters
    assert saved["gpu_offload_mode"] == "max"
    assert w._parameters_for_model(fake_gguf)["context_size"] == 16384

    # CPU mode syncs processing device and sets gpu_layers to 0.
    w.gpu_offload_mode.setCurrentIndex(w.gpu_offload_mode.findData("cpu"))
    assert w.device.currentData() == "cpu"
    assert w.parameter_inputs["gpu_layers"].value() == 0
    w.save_settings()
    saved = DesktopConfig.load().parameters
    assert saved["device"] == "cpu"
    assert saved["gpu_offload_mode"] == "cpu"
    assert saved["gpu_layers"] == 0

    # Context usage header displays GPU offloaded/total layers when present.
    w.messages = [
        {"role": "user", "content": "Hi"},
        {
            "role": "assistant",
            "content": "Hello",
            "statistics": {
                "context_used_tokens": 128,
                "context_limit_tokens": 8192,
                "execution_device": "CUDA0",
                "gpu_offloaded_layers": 27,
                "gpu_total_layers": 32,
                "gpu_offload_mode": "auto",
            },
        },
    ]
    w.render_messages()
    assert "GPU 27/32" in w.context_usage.text()
    assert "auto (27/32)" in w.context_details.text()


def test_no_duplicate_folder_permission_cards_in_transcript_render(desktop, qtbot):
    from omnicore.desktop.transcript import MessageCard

    w = desktop
    w.resize(1100, 760)
    w.show()
    qtbot.waitExposed(w)
    w.current_id = "conv-dedup"
    run = {
        "id": "run-folder-1",
        "conversation_id": "conv-dedup",
        "request_message_id": "msg-user-1",
        "response_message_id": "msg-ast-1",
        "state": "failed",
        "error_code": "agent_folder_not_granted",
        "needs_folder_grant": True,
        "steps": [],
    }
    w.agent_panel.runs = [run]
    w.messages = [
        {"id": "msg-user-1", "role": "user", "content": "wyświetl pliki w folderze Pobrane"},
        {"id": "msg-ast-1", "role": "assistant", "content": "", "status": "completed"},
    ]
    w.render_messages()
    grant_cards = [
        card
        for card in w.transcript.findChildren(MessageCard)
        if card.agent_grant_button is not None
    ]
    assert len(grant_cards) == 1

    # Casual message without a grant-requiring run renders zero folder permission buttons.
    w.agent_panel.runs = [
        {
            "id": "run-chat-1",
            "conversation_id": "conv-dedup",
            "request_message_id": "msg-user-2",
            "response_message_id": "msg-ast-2",
            "state": "completed",
            "needs_folder_grant": False,
            "steps": [],
        }
    ]
    w.messages = [
        {"id": "msg-user-2", "role": "user", "content": "co tam"},
        {
            "id": "msg-ast-2",
            "role": "assistant",
            "content": "Wszystko dobrze!",
            "status": "completed",
        },
    ]
    w.render_messages()
    grant_cards_chat = [
        card
        for card in w.transcript.findChildren(MessageCard)
        if card.agent_grant_button is not None
    ]
    assert len(grant_cards_chat) == 0


def test_expanded_chat_panel_exposes_per_model_gpu_settings_and_reload_indicator(desktop, qtbot):
    from omnicore.desktop.resources import ResourceSnapshot

    w = desktop
    w.resize(1280, 720)
    w.show()
    qtbot.waitExposed(w)

    models_dir = data_path() / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    gguf_path = models_dir / "gpu-ui-test.gguf"
    gguf_path.write_bytes(fixture_gguf("GPU UI Model"))
    imported = request(w, "POST", "/api/v1/text/models/import", {"path": str(gguf_path)})
    w.refresh_models()
    qtbot.waitUntil(lambda: any(m["id"] == imported["id"] for m in w.models))
    idx = next(
        i for i in range(w.model_combo.count()) if w.model_combo.itemData(i) == imported["id"]
    )
    w.model_combo.setCurrentIndex(idx)

    qtbot.mouseClick(w.context_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: w.context_controls.isVisible())

    for scale in (100, 150):
        w.ui_scale.setValue(scale)
        qtbot.wait(25)
        assert w.context_controls.isVisible()
        assert w.chat_gpu_label.isVisible()
        assert w.chat_gpu_mode.isVisible()
        assert w.chat_gpu_layers.isVisible()
        assert w.chat_gpu_save.isVisible()
        assert w.chat_gpu_status.isVisible()
        assert w.chat_gpu_mode.geometry().top() >= w.context_status.geometry().bottom()
        assert w.chat_gpu_mode.geometry().right() < w.chat_gpu_layers.geometry().left()
        assert w.chat_gpu_layers.geometry().right() < w.chat_gpu_save.geometry().left()
        assert w.chat_gpu_save.geometry().right() <= w.context_controls.width()

    w.ui_scale.setValue(100)
    qtbot.wait(25)
    assert [w.chat_gpu_mode.itemData(i) for i in range(w.chat_gpu_mode.count())] == [
        "auto",
        "max",
        "manual",
        "cpu",
    ]
    assert not w.chat_gpu_layers.isEnabled()

    w.chat_gpu_mode.setCurrentIndex(w.chat_gpu_mode.findData("manual"))
    assert w.chat_gpu_layers.isEnabled()
    w.chat_gpu_layers.setValue(21)
    qtbot.mouseClick(w.chat_gpu_save, Qt.LeftButton)
    qtbot.waitUntil(
        lambda: (
            not w._gpu_saving
            and w.model_contexts.get(imported["id"], {}).get("gpu", {}).get("gpu_layers") == 21
        )
    )
    assert (
        request(w, "GET", f"/api/v1/text/models/{imported['id']}/context")["gpu"]["gpu_layers"]
        == 21
    )

    params = w._parameters_for_model(w.selected_model())
    assert params["gpu_offload_mode"] == "manual"
    assert params["gpu_layers"] == 21
    assert params["device"] == "auto"

    # Resource monitor VRAM telemetry and applied-vs-configured reload indicator show in status.
    w._apply_resource_snapshot(
        ResourceSnapshot(
            cpu_percent=12.0,
            cpu_temp_c=None,
            ram_used_bytes=4 * 1024**3,
            ram_total_bytes=16 * 1024**3,
            gpu_name="RTX 4060",
            gpu_util_percent=30.0,
            vram_used_bytes=2048 * 1024**2,
            vram_total_bytes=8188 * 1024**2,
            app_ram_bytes=100 * 1024**2,
            engine_ram_bytes=200 * 1024**2,
            engine_vram_bytes=1024 * 1024**2,
        )
    )
    ctx_snapshot = dict(w.model_contexts[imported["id"]])
    ctx_snapshot["gpu"] = {
        **ctx_snapshot["gpu"],
        "vram_total_bytes": None,
        "vram_free_bytes": None,
        "applied_mode": "auto",
        "applied_requested_layers": 15,
        "applied_offloaded_layers": 15,
        "applied_total_layers": 32,
        "applied_device": "cuda",
    }
    w.model_contexts[imported["id"]] = ctx_snapshot
    w._render_model_gpu()
    status_text = w.chat_gpu_status.text()
    assert "15/32" in status_text
    assert "VRAM" in status_text
    assert w.tr("context_reload") in status_text
