import json
import os
import socket

import pytest
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QDialog, QMessageBox

from omnicore.desktop.api import ApiClient
from omnicore.desktop.config import DesktopConfig, data_path
from omnicore.desktop.lifecycle import BackendSession
from omnicore.desktop.server_credentials import server_token


def test_saved_owner_credential_reattaches_without_starting_or_stopping_process(desktop, qtbot):
    assert (data_path() / "server.token").stat().st_mode & 0o777 == 0o600
    api = ApiClient()
    session = BackendSession(api, DesktopConfig())
    try:
        with qtbot.waitSignal(session.ready, timeout=5000):
            session.start()
        assert session.process is None and not session.owned
        assert api._token == desktop.api._token
        session.stop()
        assert desktop.session.process.state() == QProcess.Running
    finally:
        api.close()


def test_lan_transition_restart_pairing_and_stop_start_without_duplicate(
    desktop, qtbot, monkeypatch
):
    import qrcode

    monkeypatch.setattr("omnicore.desktop.lifecycle.lan_addresses", lambda: ["192.168.1.12"])
    monkeypatch.setattr("omnicore.desktop.server.lan_addresses", lambda: ["192.168.1.12"])
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.Yes)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    panel = desktop.server_page
    old_pid = desktop.session.process.processId()
    panel.lan.setChecked(True)
    panel.port.setValue(port)
    panel.save()
    qtbot.waitUntil(
        lambda: desktop.is_connected and desktop.session.process.processId() != old_pid,
        timeout=20000,
    )
    assert desktop.api.base_url == f"http://127.0.0.1:{port}"
    assert DesktopConfig.load().lan_enabled
    assert panel.pair_button.isEnabled()
    payloads = []
    original = qrcode.QRCode.add_data

    def capture(qr, value, *args, **kwargs):
        payloads.append(json.loads(value))
        return original(qr, value, *args, **kwargs)

    monkeypatch.setattr(qrcode.QRCode, "add_data", capture)
    monkeypatch.setattr(QDialog, "exec", lambda dialog: QDialog.Rejected)
    panel.refresh_addresses()
    panel.pair()
    qtbot.waitUntil(lambda: bool(payloads), timeout=5000)
    assert payloads[0]["url"] == f"http://192.168.1.12:{port}"
    assert payloads[0]["code"] != desktop.api._token
    with qtbot.waitSignal(desktop.session.stopped, timeout=12000):
        panel.stop()
    assert desktop.session.process.state() == QProcess.NotRunning
    assert panel.start_button.isEnabled()
    with qtbot.waitSignal(desktop.session.ready, timeout=15000):
        panel.start_button.click()
    assert desktop.session.owned


def test_history_delete_cancel_then_confirm_preserves_model_files(desktop, qtbot, monkeypatch):
    desktop.new_conversation()
    qtbot.waitUntil(lambda: desktop.current_id is not None)
    chat = desktop.current_id
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.Cancel)
    desktop.confirm_delete_all()
    qtbot.wait(200)
    assert desktop.current_id == chat
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.Yes)
    desktop.confirm_delete_all()
    qtbot.waitUntil(lambda: desktop.current_id is None and not desktop.conversations)
    assert desktop.messages == []


def test_credentials_reject_world_readable_files_and_symlinks(tmp_path, monkeypatch):
    monkeypatch.setenv("OMNICORE_DATA_DIR", str(tmp_path))
    original = server_token(create=True)
    assert server_token() == original
    path = tmp_path / "server.token"
    path.chmod(0o644)
    with pytest.raises(OSError):
        server_token()
    path.unlink()
    target = tmp_path / "private-token"
    target.write_text(original)
    target.chmod(0o600)
    os.symlink(target, path)
    with pytest.raises(OSError):
        server_token()
