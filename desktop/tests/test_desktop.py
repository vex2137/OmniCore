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
    assert w.new_button.text() == "+ New conversation"
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
    assert any(
        "2 Output tokens" in label.text()
        and "0.10 s TTFT" in label.text()
        and "token limit" in label.toolTip()
        for label in card.findChildren(QLabel)
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
    assert w.sidebar.width() == 52
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
    assert window.sidebar.width() == 52
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
    from PySide6.QtWidgets import QPushButton

    from omnicore.desktop.i18n import Translator
    from omnicore.desktop.transcript import ChatTranscript

    transcript = ChatTranscript()
    qtbot.addWidget(transcript)
    transcript.can_regenerate = True
    message = {"id": "first", "role": "assistant", "content": "Original answer"}
    transcript.set_messages([message], Translator("en-US"))
    retry = next(
        b for b in transcript.cards[0].findChildren(QPushButton) if b.text() == "Regenerate"
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
