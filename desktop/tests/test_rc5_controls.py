from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox, QPushButton

from omnicore.desktop.config import DesktopConfig


def test_history_splitter_persists_width_collapses_and_keeps_full_title(desktop, qtbot):
    desktop.navigate(0)
    desktop.history_splitter.moveSplitter(390, 1)
    qtbot.waitUntil(lambda: DesktopConfig.load().history_width >= 380)
    width = DesktopConfig.load().history_width
    assert 200 <= width <= 520
    desktop.toggle_history()
    assert desktop.history_panel.isHidden() and DesktopConfig.load().history_collapsed
    desktop.toggle_history()
    assert not desktop.history_panel.isHidden()
    assert abs(desktop.history_splitter.sizes()[0] - width) <= 10
    title = "Full technical conversation title " * 7
    desktop.conversations = [{"id": "preview", "title": title}]
    desktop._fill_conversations()
    item = desktop.conversation_list.item(0)
    assert item.text() == title and item.toolTip() == title
    assert desktop.conversation_list.textElideMode() == Qt.ElideRight
    assert desktop.conversation_list.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_manual_token_one_time_copy_list_and_revoke_all_confirmation(desktop, qtbot, monkeypatch):
    tokens = desktop.server_page.tokens
    disclosed = []

    def dialog(dialog):
        fields = dialog.findChildren(QLineEdit)
        if fields[0].isReadOnly():
            disclosed.append(fields[0].text())
            copy = next(
                button
                for button in dialog.findChildren(QPushButton)
                if button.text() == desktop.tr("copy_token")
            )
            copy.click()
            assert QApplication.clipboard().text() == disclosed[0]
            return QDialog.Rejected
        fields[0].setText("POCO manual")
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", dialog)
    tokens.create()
    qtbot.waitUntil(lambda: tokens.table.rowCount() == 1, timeout=5000)
    assert len(disclosed) == 1 and len(disclosed[0]) == 64
    assert tokens.table.item(0, 0).text() == "POCO manual"
    assert all(disclosed[0] not in tokens.table.item(0, column).text() for column in range(5))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Cancel)
    tokens.revoke_all()
    qtbot.wait(100)
    assert tokens.table.rowCount() == 1
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Yes)
    tokens.revoke_all()
    qtbot.waitUntil(lambda: tokens.table.rowCount() == 0)
    assert desktop.is_connected


def test_qr_parallel_open_is_ignored_and_regeneration_changes_offer(desktop, qtbot, monkeypatch):
    panel = desktop.server_page
    panel.address.clear()
    panel.address.addItem("192.168.1.12")
    desktop.session.lan_hosts = ["192.168.1.12"]
    calls = []

    def request(method, path, *args, **kwargs):
        calls.append((method, path))

    monkeypatch.setattr(desktop.api, "request", request)
    panel.pair()
    panel.pair()
    assert calls == [("POST", "/api/v1/pairing/offers")]
    assert not panel.pair_button.isEnabled()


def test_provider_key_field_is_private_and_save_never_changes_desktop_json(desktop, monkeypatch):
    widget = desktop.providers_widget
    before = DesktopConfig.load()
    calls = []
    monkeypatch.setattr(
        desktop.api,
        "request",
        lambda method, path, payload, **kwargs: calls.append((method, path, payload)),
    )
    widget.key.setText("synthetic-provider-secret")
    widget.save()
    assert widget.key.echoMode() == QLineEdit.Password and not widget.key.text()
    assert calls[0][2]["api_key"] == "synthetic-provider-secret"
    assert "synthetic-provider-secret" not in str(DesktopConfig.load())
    assert DesktopConfig.load().parameters == before.parameters
