"""Named, one-time-visible credentials for manual API clients."""

import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class TokensWidget(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        layout = QVBoxLayout(self)
        layout.addWidget(window.label("api_tokens", title=True))
        hint = window.label("token_security_hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QTableWidget(0, 5)
        self.table.setMinimumHeight(170)
        self.table.setMaximumHeight(260)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        layout.addWidget(self.table)
        self.create_button = window.button("create_token", self.create)
        self.revoke_button = window.button("revoke_device", self.revoke)
        self.revoke_all_button = window.button("revoke_all_tokens", self.revoke_all)
        layout.addLayout(window.row(self.create_button, self.revoke_button, self.revoke_all_button))
        self.retranslate()
        window.session.ready.connect(self.refresh)

    def retranslate(self):
        self.table.setHorizontalHeaderLabels(
            [
                self.window.tr(k)
                for k in ("token_name", "token_scopes", "created_at", "last_used_at", "expires_at")
            ]
        )

    def refresh(self):
        if not self.window.session._ready:
            return

        def received(records):
            self.table.setRowCount(len(records))
            for row, record in enumerate(records):

                def timestamp(value):
                    return (
                        datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")
                        if value is not None
                        else "—"
                    )

                values = [
                    record["name"],
                    ", ".join(record["scopes"]),
                    timestamp(record["created_at"]),
                    timestamp(record["last_used_at"]),
                    timestamp(record["expires_at"]),
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.UserRole, record["id"])
                    self.table.setItem(row, column, item)

        self.window.api.request("GET", "/api/v1/access/tokens", success=received)

    def create(self):
        w = self.window
        dialog = QDialog(self)
        dialog.setWindowTitle(w.tr("create_token"))
        form = QFormLayout(dialog)
        name = QLineEdit()
        name.setMaxLength(80)
        days = QSpinBox()
        days.setRange(0, 366)
        days.setValue(30)
        permissions = QCheckBox(w.tr("provider_permission"))
        form.addRow(w.tr("token_name"), name)
        form.addRow(w.tr("token_expiry_days"), days)
        form.addRow(permissions)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(lambda: dialog.accept() if name.text().strip() else None)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        payload = {
            "name": name.text().strip(),
            "expires_at": time.time() + days.value() * 86400 if days.value() else None,
            "scopes": ["chat", "providers"] if permissions.isChecked() else ["chat"],
        }
        w.api.request("POST", "/api/v1/access/tokens", payload, success=self.show_token)

    def show_token(self, result):
        w = self.window
        dialog = QDialog(self)
        dialog.setWindowTitle(w.tr("create_token"))
        layout = QVBoxLayout(dialog)
        hint = QLabel(w.tr("token_once"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        value = QLineEdit(result["token"])
        value.setReadOnly(True)
        value.setMinimumWidth(520)
        layout.addWidget(value)

        def copy():
            token = value.text()
            QApplication.clipboard().setText(token)

            def clear():
                if QApplication.clipboard().text() == token:
                    QApplication.clipboard().clear()

            QTimer.singleShot(45000, QApplication.instance(), clear)

        layout.addWidget(w.button("copy_token", copy, primary=True))
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        value.clear()
        dialog.deleteLater()
        self.refresh()

    def revoke(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        if (
            item
            and QMessageBox.question(
                self, self.window.tr("revoke_device"), self.window.tr("revoke_confirm")
            )
            == QMessageBox.Yes
        ):
            self.window.api.request(
                "DELETE",
                "/api/v1/access/tokens/" + item.data(Qt.UserRole),
                success=lambda _: self.refresh(),
            )

    def revoke_all(self):
        w = self.window
        if (
            QMessageBox.warning(
                self,
                w.tr("revoke_all_tokens"),
                w.tr("revoke_all_confirm"),
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            == QMessageBox.Yes
        ):
            w.api.request(
                "DELETE",
                "/api/v1/access/tokens",
                {"confirmed": True},
                success=lambda _: self.refresh(),
            )
