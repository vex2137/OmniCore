"""Server and device controls using the existing owned-process session."""

import json
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from omnicore.desktop.server_credentials import lan_addresses
from omnicore.desktop.tokens import TokensWidget


class ServerPage(QScrollArea):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self._pair_pending = False
        self._pair_dialog = None
        self.setWidgetResizable(True)
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(16, 24, 16, 24)
        form.setVerticalSpacing(16)
        self.state = window.label("disconnected")
        form.addRow(window.label("server_state"), self.state)
        self.start_button = window.button("start_backend", window.session.start, primary=True)
        self.stop_button = window.button("stop_server", self.stop)
        self.restart_button = window.button("restart_server", self.restart)
        form.addRow(window.row(self.start_button, self.stop_button, self.restart_button))
        self.external = window.label("server_ownership")
        self.external.setWordWrap(True)
        form.addRow(self.external)
        self.autostart = QCheckBox(window.tr("server_autostart"))
        window._texts.append((self.autostart, "server_autostart"))
        self.autostart.setChecked(window.config.auto_start_backend)
        self.lan = QCheckBox(window.tr("server_lan"))
        window._texts.append((self.lan, "server_lan"))
        self.lan.setChecked(window.config.lan_enabled)
        form.addRow(self.autostart)
        form.addRow(self.lan)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(window.config.lan_port)
        form.addRow(window.label("server_port"), self.port)
        form.addRow(window.button("save_server", self.save, primary=True))
        self.address = QComboBox()
        form.addRow(window.label("server_address"), self.address)
        form.addRow(window.button("refresh", self.refresh_addresses))
        hint = window.label("lan_security_hint")
        hint.setWordWrap(True)
        form.addRow(hint)
        self.pair_button = window.button("pair_phone", self.pair, primary=True)
        form.addRow(self.pair_button)
        self.devices = QListWidget()
        self.devices.setMaximumHeight(160)
        form.addRow(window.label("paired_devices"), self.devices)
        self.revoke_button = window.button("revoke_device", self.revoke)
        form.addRow(self.revoke_button)
        self.tokens = TokensWidget(window)
        form.addRow(self.tokens)
        self.setWidget(page)
        window.session.state_changed.connect(self.update_state)
        window.session.ready.connect(self.refresh_devices)
        self.refresh_addresses()
        self.update_state("disconnected")

    def refresh_addresses(self):
        current = self.address.currentText()
        self.address.clear()
        self.address.addItems(lan_addresses())
        if current in [self.address.itemText(i) for i in range(self.address.count())]:
            self.address.setCurrentText(current)

        if hasattr(self, "tokens") and self.window.session._ready:
            self.tokens.refresh()
            self.refresh_devices()

    def update_state(self, state):
        w = self.window
        self.state.setText(w.tr(state))
        owned = w.session.owned
        idle = state not in {"connecting", "backend_starting", "closing"}
        self.start_button.setEnabled(state in {"disconnected", "error"})
        self.stop_button.setEnabled(owned and idle and state == "connected")
        self.restart_button.setEnabled(owned and idle and state == "connected")
        self.pair_button.setEnabled(
            owned
            and state == "connected"
            and w.config.lan_enabled
            and not self._pair_pending
            and self._pair_dialog is None
        )
        self.tokens.setEnabled(state == "connected")
        self.revoke_button.setEnabled(owned and state == "connected" and w.config.lan_enabled)

    def stop(self):
        if not self.window.session.owned:
            return
        if (
            QMessageBox.question(
                self, self.window.tr("stop_server"), self.window.tr("stop_server_confirm")
            )
            == QMessageBox.Yes
        ):
            self.window.session.stop()

    def restart(self):
        if not self.window.active_job:
            self.window.session.restart(self.window.config)
        else:
            self.window.show_error("busy")

    def save(self):
        w = self.window
        changed = (
            self.lan.isChecked() != w.config.lan_enabled or self.port.value() != w.config.lan_port
        )
        if changed and (w.active_job or w.session._starting):
            w.show_error("busy")
            return
        if changed and w.is_connected and not w.session.owned:
            w.show_error("external_backend_settings")
            return
        if self.lan.isChecked() and not lan_addresses():
            w.show_error("lan_no_address")
            return
        if self.lan.isChecked() and not w.config.lan_enabled:
            if (
                QMessageBox.question(self, w.tr("server_lan"), w.tr("lan_security_hint"))
                != QMessageBox.Yes
            ):
                self.lan.setChecked(False)
                return
        w.config.lan_enabled, w.config.lan_port = self.lan.isChecked(), self.port.value()
        w.config.auto_start_backend = self.autostart.isChecked()
        try:
            w.config.save()
        except OSError:
            w.show_error("invalid_settings")
            return
        if changed:
            if w.session.owned:
                w.session.restart(w.config)
            else:
                w.session.start()
        self.refresh_addresses()

    def refresh_devices(self):
        if not self.window.config.lan_enabled:
            return

        def received(records):
            self.devices.clear()
            for record in records:
                item = QListWidgetItem(record["id"][:12])
                item.setData(Qt.UserRole, record["id"])
                self.devices.addItem(item)

        self.window.api.request("GET", "/api/v1/pairing/devices", success=received)

    def revoke(self):
        item = self.devices.currentItem()
        if (
            item
            and QMessageBox.question(
                self, self.window.tr("revoke_device"), self.window.tr("revoke_confirm")
            )
            == QMessageBox.Yes
        ):
            self.window.api.request(
                "DELETE",
                "/api/v1/pairing/devices/" + item.data(Qt.UserRole),
                success=lambda _: self.refresh_devices(),
            )

    def pair(self):
        address = self.address.currentText()
        if self._pair_pending or self._pair_dialog is not None:
            return
        if not address:
            self.window.show_error("lan_no_address")
            return
        if address not in self.window.session.lan_hosts:
            self.window.show_error("lan_restart_required")
            return
        self._pair_pending = True
        self.pair_button.setEnabled(False)

        def failure(code):
            self._pair_pending = False
            self.update_state(self.window._connection_key)
            self.window.show_error(code)

        self.window.api.request(
            "POST",
            "/api/v1/pairing/offers",
            {},
            success=lambda offer: self.show_pairing(offer, address),
            failure=failure,
        )

    def show_pairing(self, offer, address=None):
        import qrcode

        w = self.window
        self._pair_pending = False
        dialog = QDialog(self)
        self._pair_dialog = dialog
        dialog.setWindowTitle(w.tr("pair_phone"))
        layout = QVBoxLayout(dialog)
        text = QLabel(w.tr("pairing_hint"))
        text.setWordWrap(True)
        layout.addWidget(text)
        picture = QLabel()
        layout.addWidget(picture, alignment=Qt.AlignCenter)
        countdown = QLabel()
        countdown.setWordWrap(True)
        layout.addWidget(countdown)
        state = {"offer": offer, "polling": False, "closed": False, "status": "waiting"}
        address = address or self.address.currentText()

        def draw(value):
            if state["closed"]:
                return
            state["offer"], state["status"], state["polling"] = value, "waiting", False
            payload = json.dumps(
                {
                    "omnicore": 1,
                    "url": f"http://{address}:{w.config.lan_port}",
                    "code": value["code"],
                    "expires_at": int(value["expires_at"]),
                },
                separators=(",", ":"),
            )
            qr = qrcode.QRCode(border=4)
            qr.add_data(payload)
            qr.make(fit=True)
            matrix = qr.get_matrix()
            image = QImage(len(matrix), len(matrix), QImage.Format_RGB32)
            for y, row in enumerate(matrix):
                for x, black in enumerate(row):
                    image.setPixelColor(x, y, Qt.black if black else Qt.white)
            picture.setPixmap(
                QPixmap.fromImage(image).scaled(
                    len(matrix) * max(4, min(8, 420 // len(matrix))),
                    len(matrix) * max(4, min(8, 420 // len(matrix))),
                    Qt.KeepAspectRatio,
                    Qt.FastTransformation,
                )
            )
            regenerate.setEnabled(True)
            tick()

        def new_code():
            regenerate.setEnabled(False)
            w.api.request(
                "POST",
                "/api/v1/pairing/offers",
                {},
                success=draw,
                failure=lambda code: (regenerate.setEnabled(True), countdown.setText(w.tr(code))),
            )

        regenerate = w.button("pairing_new_code", new_code)
        layout.addWidget(regenerate)
        layout.addWidget(w.button("cancel", dialog.reject))

        def status(value, identity):
            if state["offer"]["id"] != identity:
                return
            state["polling"] = False
            if state["closed"]:
                return
            state["status"] = value["status"]
            if value["status"] == "used":
                regenerate.setEnabled(False)
                countdown.setText(w.tr("pairing_complete"))
                picture.clear()
                QTimer.singleShot(1200, dialog, dialog.accept)

        def poll_failed(_code, identity):
            if state["offer"]["id"] != identity:
                return
            state["polling"] = False
            if not state["closed"]:
                countdown.setText(w.tr("pairing_network_error"))

        def tick():
            if state["closed"] or state["status"] == "used":
                return
            remaining = max(0, int(state["offer"]["expires_at"] - time.time()))
            countdown.setText(
                w.tr("pairing_expires", seconds=remaining) if remaining else w.tr("pairing_expired")
            )
            if not remaining:
                picture.clear()
            if not state["polling"]:
                state["polling"] = True
                w.api.request(
                    "GET",
                    "/api/v1/pairing/offers/" + state["offer"]["id"],
                    success=lambda value, identity=state["offer"]["id"]: status(value, identity),
                    failure=lambda code, identity=state["offer"]["id"]: poll_failed(code, identity),
                )

        timer = QTimer(dialog)
        timer.timeout.connect(tick)
        timer.start(1000)
        draw(offer)
        dialog.exec()
        state["closed"] = True
        timer.stop()
        self._pair_dialog = None
        self.update_state(w._connection_key)
        w.api.request(
            "DELETE",
            "/api/v1/pairing/offers/" + state["offer"]["id"],
            success=lambda _: (self.refresh_devices(), self.tokens.refresh()),
        )
        dialog.deleteLater()
