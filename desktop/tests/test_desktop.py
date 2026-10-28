import json
import os
import struct
from importlib.resources import files

import httpx
from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

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
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    w.delete_conversation()
    qtbot.waitUntil(lambda: w.conversation_list.count() == 0)
    assert not w.current_id


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
