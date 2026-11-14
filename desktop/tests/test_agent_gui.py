"""Real Qt -> HTTP -> orchestrator -> tool -> approval flow with a controlled model."""

import asyncio
import json
import os
import secrets
import socket
import threading
from pathlib import Path

import pytest
import uvicorn
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox, QFileDialog, QMessageBox
from test_desktop import fixture_gguf, request

from omnicore.app import create_app
from omnicore.config import RuntimeConfig
from omnicore.desktop.api import ApiClient
from omnicore.desktop.config import DesktopConfig
from omnicore.desktop.lifecycle import BackendSession
from omnicore.desktop.window import MainWindow
from omnicore.schemas import BackendInfo, ResourceUsage
from omnicore.text.types import TextChunk


class ToolEngine:
    """Deterministic model transport; no assertion of real model/hardware support."""

    async def probe(self):
        return BackendInfo(id="llama.cpp", available=True, version="test")

    async def resources(self):
        return ResourceUsage()

    async def load(self, path, parameters, file_descriptor=None):
        assert file_descriptor is not None

    async def stream(self, model, messages, parameters):
        if not any(m.role == "assistant" for m in messages):
            raw = json.dumps(
                {
                    "kind": "plan",
                    "steps": [
                        {"id": "read", "title": "Read input"},
                        {"id": "write", "title": "Propose output"},
                    ],
                }
            )
            yield TextChunk(content=raw, finish_reason="stop")
            return
        grants = json.loads(messages[2].content.split(": ", 1)[1])
        calls = sum('"kind": "tool"' in m.content for m in messages if m.role == "assistant")
        if calls == 0:
            response = {
                "kind": "tool",
                "name": "read_text",
                "arguments": {"grant_id": grants[0]["id"], "path": "input.txt"},
            }
        elif calls == 1:
            assert "sample text" in messages[-1].content
            response = {
                "kind": "tool",
                "name": "write_text",
                "arguments": {
                    "grant_id": grants[0]["id"],
                    "path": "output.txt",
                    "mode": "create",
                    "content": "Reviewed output\n",
                },
            }
        else:
            response = {"kind": "final", "text": "Saved approved output."}
        raw = json.dumps(response)
        yield TextChunk(content=raw[:8])
        await asyncio.sleep(0)
        yield TextChunk(content=raw[8:], finish_reason="stop")

    async def stop(self):
        pass

    async def unload(self, model=None):
        pass


@pytest.fixture
def agent_window(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    token = secrets.token_hex(32)
    app = create_app(RuntimeConfig(data_dir=tmp_path / "backend", api_token=token))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    qtbot.waitUntil(lambda: server.started, timeout=5000)
    service = app.state.text
    model_dir = service.config.data_dir / "models"
    model_dir.mkdir(exist_ok=True)
    model_path = model_dir / "fixture.gguf"
    model_path.write_bytes(fixture_gguf())
    service.models.import_gguf(model_path)
    service.engines["llama.cpp"] = ToolEngine()
    monkeypatch.setenv("OMNICORE_DESKTOP_URL", url)
    monkeypatch.setenv("OMNICORE_DESKTOP_TOKEN", token)
    api = ApiClient()
    config = DesktopConfig(ollama_enabled=False, parameters={"device": "cpu", "gpu_layers": 0})
    session = BackendSession(api, config)
    window = MainWindow(api, session, config)
    qtbot.addWidget(window)
    window.show()
    session.start()
    qtbot.waitUntil(lambda: window.is_connected and not window._health_pending, timeout=10000)
    yield window, service
    window.close()
    qtbot.waitUntil(lambda: window._allow_close)
    server.should_exit = True
    thread.join(timeout=5)
    listener.close()
    assert not thread.is_alive()


def test_agent_gui_read_review_write_and_durable_mode(agent_window, qtbot, monkeypatch, tmp_path):
    w, service = agent_window
    folder = tmp_path / "shared"
    folder.mkdir()
    (folder / "input.txt").write_text("sample text")
    w.model_combo.setCurrentIndex(1)
    qtbot.mouseClick(w.new_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: bool(w.current_id))
    panel = w.agent_panel
    qtbot.waitUntil(lambda: not panel.settings_loading)
    panel.mode.setCurrentIndex(panel.mode.findData("agent"))
    qtbot.waitUntil(lambda: not panel.settings_saving)
    assert not panel.details.isVisible()
    assert not panel.settings_toggle.isVisible()
    qtbot.mouseClick(w.context_button, Qt.LeftButton)
    assert panel.details.isVisible()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: str(folder))
    answers = iter([QMessageBox.Yes, QMessageBox.No])
    monkeypatch.setattr(QMessageBox, "question", lambda *a: next(answers))
    qtbot.mouseClick(panel.folder, Qt.LeftButton)
    qtbot.waitUntil(lambda: panel.folders.count() == 1)
    w.composer.setPlainText("Read input.txt and create output.txt")
    qtbot.mouseClick(w.send_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: panel.dialog is not None, timeout=10000)
    assert not (folder / "output.txt").exists()
    assert panel.tree.topLevelItemCount() == 3
    assert panel.tree.topLevelItem(0).childCount() == 2
    assert not w.send_button.isEnabled()
    buttons = panel.dialog.findChild(QDialogButtonBox)
    qtbot.mouseClick(buttons.button(QDialogButtonBox.Yes), Qt.LeftButton)
    qtbot.waitUntil(lambda: panel.active is None, timeout=10000)
    qtbot.waitUntil(lambda: "Saved approved output." in w.transcript.toPlainText())
    assert (folder / "output.txt").read_text() == "Reviewed output\n"
    assert w.send_button.isEnabled()
    saved = request(w, "GET", f"/api/v1/agents/conversations/{w.current_id}/runs")[0]
    assert [step["state"] for step in saved["steps"]] == ["completed", "completed"]
    assert "sample text" not in json.dumps(saved)
    panel.load(w.current_id)
    qtbot.waitUntil(lambda: panel.tree.topLevelItemCount() == 3)
    assert service.agents.settings(w.current_id).mode == "agent"
    output = os.environ.get("OMNICORE_BETA3_SCREENSHOTS")
    if output:
        directory = Path(output)
        directory.mkdir(parents=True, exist_ok=True)
        w.resize(1280, 720)
        qtbot.wait(100)
        w.transcript.scroll_bottom()
        qtbot.wait(50)
        assert w.grab().save(str(directory / "agent-task-completed.png"))


def test_agent_controls_themes_scale_and_chat_default(desktop, qtbot):
    w = desktop
    w.new_conversation()
    qtbot.waitUntil(lambda: bool(w.current_id))
    panel = w.agent_panel
    qtbot.waitUntil(lambda: not panel.settings_loading)
    assert panel.mode.currentData() == "chat"
    assert not panel.details.isVisible()
    panel.mode.setCurrentIndex(panel.mode.findData("agent"))
    qtbot.waitUntil(lambda: not panel.settings_saving)
    for index in range(w.theme.count()):
        w.theme.setCurrentIndex(index)
        assert panel.isEnabled() and panel.mode.isEnabled()
    for scale in (80, 100, 150):
        w.ui_scale.setValue(scale)
        assert f"font: {round(14 * scale / 100)}px" in w.styleSheet()
    w.toggle_sidebar()
    assert w.config.sidebar_compact
    assert panel.mode.isEnabled()
    for locale in ("en-US", "pl-PL"):
        w.language.setCurrentIndex(w.language.findData(locale))
        assert panel.folder.text() == w.tr("agent_folder")
    panel.mode.setCurrentIndex(panel.mode.findData("chat"))
    qtbot.waitUntil(lambda: not panel.settings_saving)
    assert not panel.details.isVisible()
    assert (
        request(w, "GET", f"/api/v1/agents/conversations/{w.current_id}/settings")["mode"] == "chat"
    )


def test_model_check_and_explicit_new_retry_in_gui(agent_window, qtbot, monkeypatch):
    class CompatibilityEngine(ToolEngine):
        attempt = 0

        async def stream(self, model, messages, parameters):
            if messages[0].content.startswith("Call calculate"):
                raw = json.dumps(
                    {"kind": "tool", "name": "calculate", "arguments": {"expression": "2+3"}}
                )
            else:
                self.attempt += 1
                raw = (
                    "{"
                    if self.attempt <= 2
                    else json.dumps({"kind": "final", "text": "Recovered safely"})
                )
            yield TextChunk(content=raw, finish_reason="stop")

    w, service = agent_window
    service.engines["llama.cpp"] = CompatibilityEngine()
    w.model_combo.setCurrentIndex(1)
    w.new_conversation()
    qtbot.waitUntil(lambda: bool(w.current_id))
    panel = w.agent_panel
    qtbot.waitUntil(lambda: not panel.settings_loading)
    panel.mode.setCurrentIndex(panel.mode.findData("agent"))
    qtbot.waitUntil(lambda: not panel.settings_saving)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    panel.scroll.ensureWidgetVisible(panel.compatibility_test)
    qtbot.mouseClick(panel.compatibility_test, Qt.LeftButton)
    qtbot.waitUntil(lambda: not panel.compatibility_busy)
    qtbot.waitUntil(lambda: w.tr("agent_cap_json") in panel.compatibility_label.text())
    w.composer.setPlainText("Try task")
    qtbot.mouseClick(w.send_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: bool(panel.retry_id), timeout=10000)
    assert panel.retry_button.isVisible()
    source = panel.retry_id
    qtbot.mouseClick(panel.retry_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: "Recovered safely" in w.transcript.toPlainText(), timeout=10000)
    qtbot.waitUntil(lambda: panel.active is None, timeout=5000)
    assert not panel.retry_button.isVisible()
    records = request(w, "GET", f"/api/v1/agents/conversations/{w.current_id}/runs")
    assert records[0]["id"] != source and records[0]["retry_of"] == source
    assert records[0]["state"] == "completed" and records[1]["state"] == "failed"


def test_agent_mode_remains_available_after_settings_request_failure(
    agent_window, qtbot, monkeypatch
):
    w, _ = agent_window
    w.new_conversation()
    qtbot.waitUntil(lambda: bool(w.current_id) and not w.agent_panel.settings_loading)
    panel = w.agent_panel
    assert [panel.mode.itemData(i) for i in range(panel.mode.count())] == ["chat", "agent"]
    original = w.api.request

    def failing_once(method, path, *args, **kwargs):
        if path.endswith("/settings"):
            kwargs["failure"]("engine_timeout")
        else:
            original(method, path, *args, **kwargs)

    monkeypatch.setattr(w.api, "request", failing_once)
    panel.load(w.current_id)
    assert not panel.settings_loading
    assert panel.mode.isEnabled()
    assert panel.steps.isEnabled()
    assert panel.mode.findData("agent") >= 0


def test_beta3_compact_chat_header_and_context_disclosure(desktop, qtbot):
    w = desktop
    assert w.agent_panel.mode.parentWidget() is w.model_combo.parentWidget()
    assert w.context_controls.isHidden()
    qtbot.mouseClick(w.context_button, Qt.LeftButton)
    assert not w.context_controls.isHidden()
    qtbot.mouseClick(w.context_button, Qt.LeftButton)
    assert w.context_controls.isHidden()
    assert [w.agent_panel.mode.itemData(i) for i in range(w.agent_panel.mode.count())] == [
        "chat",
        "agent",
    ]


def test_beta3_statistics_are_measured_compact_and_localized(qtbot):
    from PySide6.QtWidgets import QLabel

    from omnicore.desktop.i18n import Translator
    from omnicore.desktop.transcript import MessageCard

    card = MessageCard(
        {
            "role": "assistant",
            "content": "Answer",
            "statistics": {
                "ttft_seconds": 0.87,
                "tokens_per_second": 100.3,
                "output_tokens": 17,
                "generation_seconds": 1.04,
            },
        },
        Translator("pl-PL"),
    )
    qtbot.addWidget(card)
    labels = [label.text() for label in card.findChildren(QLabel)]
    joined = " ".join(labels)
    assert all(part in joined for part in ("0,87 s TTFT", "100,30 tok/s", "17 tok.", "1,04 s"))
    assert sum(1 for label in card.findChildren(QLabel) if not label.pixmap().isNull()) == 4


def test_context_log_slider_keeps_exact_manual_input(desktop):
    w = desktop
    w.context_mode.setCurrentIndex(w.context_mode.findData("manual"))
    w.context_tokens.setMaximum(32768)
    w.context_tokens.setValue(8193)
    assert w.context_tokens.value() == 8193
    w.context_slider.setValue(0)
    assert w.context_tokens.value() == 128
    w.context_slider.setValue(1000)
    assert w.context_tokens.value() == 32768


def test_diagnostics_beta3_redacts_models_and_excludes_prompts(desktop):
    import json

    from omnicore.desktop.report import diagnostic_report

    w = desktop
    token = w.api._token
    w.models = [
        {
            "id": "model",
            "name": "Model " + token,
            "location": "/home/private-person/secret-folder/model.gguf",
            "backend": "llama.cpp",
            "format": "GGUF",
            "size_bytes": 123,
        }
    ]
    w.last_job = {
        "state": "failed",
        "error_code": "engine_timeout",
        "content": "private conversation",
    }
    report = diagnostic_report(w, "offscreen")
    raw = json.dumps(report)
    assert token not in raw and "private-person" not in raw and "secret-folder" not in raw
    assert "private conversation" not in raw
    assert report["models"][0]["size_bytes"] == 123
    assert report["last_generation"]["error_code"] == "engine_timeout"
    assert report["build"]["channel"] == "beta"


def test_agent_gui_plain_text_no_banner_and_persisted_step_cards(
    agent_window, qtbot, monkeypatch, tmp_path
):
    from omnicore.desktop.transcript import MessageCard

    w, service = agent_window
    folder = tmp_path / "shared_persisted"
    folder.mkdir()
    (folder / "input.txt").write_text("sample text")
    w.model_combo.setCurrentIndex(1)
    qtbot.mouseClick(w.new_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: bool(w.current_id))
    first_conv = w.current_id
    panel = w.agent_panel
    qtbot.waitUntil(lambda: not panel.settings_loading)
    header_pos_before = panel.mode.geometry()
    panel.mode.setCurrentIndex(panel.mode.findData("agent"))
    qtbot.waitUntil(lambda: not panel.settings_saving)
    assert panel.mode.geometry() == header_pos_before
    assert not panel.isVisible()

    # 1. Plain text response in Agent mode: 0 steps, no error banner, no retry button
    orig_engine = service.engines["llama.cpp"]

    class PlainTextEngine(ToolEngine):
        async def stream(self, model, messages, parameters):
            yield TextChunk(
                content="Tak, mogę działać jako agent i odpowiadać bezpośrednio.",
                finish_reason="stop",
            )

    service.engines["llama.cpp"] = PlainTextEngine()
    w.composer.setPlainText("czy możesz działać jako agent?")
    qtbot.mouseClick(w.send_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: "odpowiadać bezpośrednio" in w.transcript.toPlainText(), timeout=10000)
    qtbot.waitUntil(lambda: panel.active is None, timeout=5000)
    assert not panel.retry_button.isVisible()
    assert panel.status.text() == ""
    assert not panel.isVisible()
    cards = w.transcript.findChildren(MessageCard)
    assert cards and cards[-1].agent_step_buttons == []

    # 2. Tool run creates expandable step pills on MessageCard and persists across reload
    service.engines["llama.cpp"] = orig_engine
    qtbot.mouseClick(w.new_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: bool(w.current_id) and w.current_id != first_conv)
    tool_conv = w.current_id
    qtbot.waitUntil(lambda: not panel.settings_loading)
    panel.mode.setCurrentIndex(panel.mode.findData("agent"))
    qtbot.waitUntil(lambda: not panel.settings_saving)
    qtbot.mouseClick(w.context_button, Qt.LeftButton)
    assert panel.details.isVisible()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: str(folder))
    answers = iter([QMessageBox.Yes, QMessageBox.No])
    monkeypatch.setattr(QMessageBox, "question", lambda *a: next(answers))
    qtbot.mouseClick(panel.folder, Qt.LeftButton)
    qtbot.waitUntil(lambda: panel.folders.count() == 1)
    qtbot.mouseClick(w.context_button, Qt.LeftButton)
    assert not panel.details.isVisible()

    w.composer.setPlainText("Read input.txt and create output.txt")
    qtbot.mouseClick(w.send_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: panel.dialog is not None, timeout=10000)
    buttons = panel.dialog.findChild(QDialogButtonBox)
    qtbot.mouseClick(buttons.button(QDialogButtonBox.Yes), Qt.LeftButton)
    qtbot.waitUntil(lambda: panel.active is None, timeout=10000)
    qtbot.waitUntil(lambda: "Saved approved output." in w.transcript.toPlainText(), timeout=10000)

    cards = [c for c in w.transcript.findChildren(MessageCard) if c.agent_step_buttons]
    assert len(cards) == 1
    step_btns = cards[0].agent_step_buttons
    step_details = cards[0].agent_step_details
    assert len(step_btns) == 2
    assert "read_text" in step_btns[0].text()
    assert "write_text" in step_btns[1].text()
    assert not step_details[0].isVisible()
    qtbot.mouseClick(step_btns[0], Qt.LeftButton)
    assert step_details[0].isVisible()

    # Switch to first_conv and then reopen tool_conv from history
    w.open_conversation(first_conv)
    qtbot.waitUntil(lambda: w.current_id == first_conv)
    w.open_conversation(tool_conv)
    qtbot.waitUntil(lambda: w.current_id == tool_conv)
    qtbot.waitUntil(
        lambda: any(c.agent_step_buttons for c in w.transcript.findChildren(MessageCard)),
        timeout=5000,
    )
    restored_cards = [c for c in w.transcript.findChildren(MessageCard) if c.agent_step_buttons]
    assert len(restored_cards) == 1
    assert len(restored_cards[0].agent_step_buttons) == 2


def test_hotfix2_context_presets_inline_folder_continue_and_stop_button(
    agent_window, qtbot, monkeypatch, tmp_path
):
    from omnicore.desktop.transcript import MessageCard

    w, service = agent_window
    downloads = tmp_path / "Pobrane"
    downloads.mkdir()
    (downloads / "lista.txt").write_text("element 1")

    w.model_combo.setCurrentIndex(1)
    qtbot.mouseClick(w.new_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: bool(w.current_id))
    panel = w.agent_panel
    qtbot.waitUntil(lambda: not panel.settings_loading)

    # 1. Idle state: stop_button is hidden and disabled, status is Gotowy
    assert not w.stop_button.isVisible()
    assert not w.stop_button.isEnabled()
    assert w.send_button.isEnabled()
    assert w.generation_status.text() == w.tr("ready")

    # 2. Switch to Agent mode and verify context_controls + presets are available via gear button
    panel.mode.setCurrentIndex(panel.mode.findData("agent"))
    qtbot.waitUntil(lambda: not panel.settings_saving)
    qtbot.mouseClick(w.context_button, Qt.LeftButton)
    assert w.context_controls.isVisible()
    assert panel.details.isVisible()
    preset_values = [w.context_preset.itemData(i) for i in range(w.context_preset.count())]
    assert "auto" in preset_values
    assert 4096 in preset_values or 2048 in preset_values
    assert "custom" in preset_values
    qtbot.mouseClick(w.context_button, Qt.LeftButton)

    # 3. Ask about files in Pobrane without folder grant -> inline Udostępnij folder appears
    class MissingFolderThenListEngine(ToolEngine):
        def __init__(self):
            self.calls = 0

        async def stream(self, model, messages, parameters):
            self.calls += 1
            if self.calls == 1:
                yield TextChunk(
                    content=(
                        "Nie mam dostępu do folderu Pobrane. Udostępnij folder, aby kontynuować."
                    ),
                    finish_reason="stop",
                )
            elif self.calls == 2:
                grants_msg = messages[-1].content
                grant_id = json.loads(grants_msg.split(": ", 1)[1])[0]["id"]
                yield TextChunk(
                    content=json.dumps(
                        {
                            "kind": "tool",
                            "name": "list_files",
                            "arguments": {"grant_id": grant_id, "path": "."},
                        }
                    ),
                    finish_reason="stop",
                )
            else:
                yield TextChunk(
                    content=json.dumps(
                        {
                            "kind": "final",
                            "text": "W folderze Pobrane znajduje się plik lista.txt.",
                        }
                    ),
                    finish_reason="stop",
                )

    service.engines["llama.cpp"] = MissingFolderThenListEngine()
    w.composer.setPlainText("weź sprawdź jakie pliki mam na komputerze w folderze Pobrane")
    qtbot.mouseClick(w.send_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: panel.active is None and len(panel.runs) == 1, timeout=10000)
    qtbot.waitUntil(
        lambda: any(
            c.agent_grant_button is not None for c in w.transcript.findChildren(MessageCard)
        ),
        timeout=5000,
    )
    prompt_card = next(
        c for c in w.transcript.findChildren(MessageCard) if c.agent_grant_button is not None
    )
    assert prompt_card.agent_grant_button.isVisible()
    assert not prompt_card.agent_continue_button.isVisible()

    # 4. Cancelling folder dialog updates notice without error loop
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: "")
    qtbot.mouseClick(prompt_card.agent_grant_button, Qt.LeftButton)
    cancelled_card = next(
        c for c in w.transcript.findChildren(MessageCard) if c.agent_grant_button is not None
    )
    assert w.tr("agent_folder_cancelled") in cancelled_card.agent_folder_label.text()

    # 5. Granting folder via FolderGrantDialog enables Kontynuuj zadanie without duplicating message
    dialog_check = panel.create_folder_grant_dialog(str(downloads))
    assert dialog_check.scope_combo.currentData() is False  # Read-only by default
    assert dialog_check.subfolders_check.isChecked() is True
    assert dialog_check.persistence_combo.currentData() is False
    dialog_check.deleteLater()

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: str(downloads))
    monkeypatch.setattr(
        panel,
        "confirm_folder_grant",
        lambda _p: (True, False, False, True, True),
    )
    qtbot.mouseClick(cancelled_card.agent_grant_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: len(panel.granted_folders) == 1, timeout=5000)
    assert w.tr("agent_scope_read_only") in panel.folders.item(0).text()
    assert w.tr("agent_persistence_durable") in panel.folders.item(0).text()

    ready_card = next(
        c for c in w.transcript.findChildren(MessageCard) if c.agent_continue_button is not None
    )
    assert ready_card.agent_continue_button.isVisible()
    assert ready_card.agent_continue_button.isEnabled()

    qtbot.mouseClick(ready_card.agent_continue_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: "lista.txt" in w.transcript.toPlainText(), timeout=10000)
    qtbot.waitUntil(lambda: panel.active is None, timeout=5000)
    assert not w.stop_button.isVisible()
    assert w.generation_status.text() == w.tr("ready")
    assert [m["role"] for m in w.messages] == ["user", "assistant"]
