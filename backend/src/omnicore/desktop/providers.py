"""Configure external providers through the backend; provider keys never enter desktop.json."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from omnicore.providers.protocols import ENDPOINTS


class ProvidersWidget(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.records = []
        form = QFormLayout(self)
        form.addRow(window.label("providers_title", title=True))
        hint = window.label("providers_security_hint")
        hint.setWordWrap(True)
        form.addRow(hint)
        self.saved = QComboBox()
        form.addRow(window.label("provider_config"), self.saved)
        self.kind = QComboBox()
        for kind in ("openai", "anthropic", "gemini", "openrouter", "custom"):
            self.kind.addItem(
                {
                    "openai": "OpenAI",
                    "anthropic": "Anthropic",
                    "gemini": "Google Gemini",
                    "openrouter": "OpenRouter",
                    "custom": "OpenAI-compatible",
                }[kind],
                kind,
            )
        form.addRow(window.label("provider_kind"), self.kind)
        self.name = QLineEdit()
        self.name.setMaxLength(80)
        form.addRow(window.label("token_name"), self.name)
        self.endpoint = QLineEdit()
        self.endpoint.setMaxLength(2048)
        form.addRow(window.label("provider_endpoint"), self.endpoint)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setMaxLength(8192)
        form.addRow(window.label("provider_key"), self.key)
        self.key_state = QLabel()
        form.addRow(self.key_state)
        self.clear_key = QCheckBox(window.tr("provider_clear_key"))
        window._texts.append((self.clear_key, "provider_clear_key"))
        form.addRow(self.clear_key)
        self.sampling = QCheckBox(window.tr("provider_sampling"))
        window._texts.append((self.sampling, "provider_sampling"))
        form.addRow(self.sampling)
        form.addRow(
            window.row(
                window.button("save", self.save), window.button("provider_delete", self.delete)
            )
        )
        form.addRow(
            window.row(
                window.button("test_connection", self.test),
                window.button("provider_list_models", self.list_models),
            )
        )
        self.models = QComboBox()
        self.models.currentTextChanged.connect(lambda value: self.model_id.setText(value))
        form.addRow(window.label("models"), self.models)
        self.model_id = QLineEdit()
        self.model_id.setMaxLength(256)
        form.addRow(window.label("provider_model_id"), self.model_id)
        form.addRow(window.button("provider_add_model", self.add_model, primary=True))
        self.saved.currentIndexChanged.connect(self.selected)
        self.kind.currentIndexChanged.connect(self.kind_changed)
        self.saved.addItem(window.tr("provider_new"), None)
        self.kind_changed()

    def refresh(self, select=None):
        def received(records):
            current = select or self.saved.currentData()
            self.records = records
            self.saved.blockSignals(True)
            self.saved.clear()
            self.saved.addItem(self.window.tr("provider_new"), None)
            for record in records:
                self.saved.addItem(record["label"], record["id"])
            self.saved.setCurrentIndex(max(0, self.saved.findData(current)))
            self.saved.blockSignals(False)
            self.selected()

        self.window.api.request("GET", "/api/v1/providers/configs", success=received)

    def kind_changed(self):
        kind = self.kind.currentData()
        self.endpoint.setReadOnly(kind != "custom")
        if kind != "custom":
            self.endpoint.setText(ENDPOINTS[kind])
        elif self.endpoint.text() in ENDPOINTS.values():
            self.endpoint.clear()

    def selected(self):
        record = next((r for r in self.records if r["id"] == self.saved.currentData()), None)
        self.key.clear()
        self.clear_key.setChecked(False)
        self.models.clear()
        self.model_id.clear()
        self.name.setText(record["label"] if record else "")
        self.kind.setCurrentIndex(self.kind.findData(record["kind"] if record else "openai"))
        self.kind_changed()
        if record:
            self.endpoint.setText(record["endpoint"])
        self.sampling.setChecked(record["sampling"] if record else False)
        self.key_state.setText(
            self.window.tr(
                "provider_key_saved" if record and record["key_present"] else "provider_key_missing"
            )
        )

    def save(self):
        identity = self.saved.currentData()
        payload = {
            "kind": self.kind.currentData(),
            "label": self.name.text(),
            "endpoint": self.endpoint.text().strip(),
            "clear_key": self.clear_key.isChecked(),
            "sampling": self.sampling.isChecked(),
        }
        if self.key.text():
            payload["api_key"] = self.key.text()
        self.key.clear()
        self.window.api.request(
            "PUT" if identity else "POST",
            "/api/v1/providers/configs" + ("/" + identity if identity else ""),
            payload,
            success=lambda record: self.refresh(record["id"]),
        )

    def delete(self):
        identity = self.saved.currentData()
        if (
            identity
            and QMessageBox.question(
                self, self.window.tr("provider_delete"), self.window.tr("provider_delete_confirm")
            )
            == QMessageBox.Yes
        ):
            self.window.api.request(
                "DELETE",
                "/api/v1/providers/configs/" + identity,
                success=lambda _: (self.refresh(), self.window.refresh_models()),
            )

    def test(self):
        identity = self.saved.currentData()
        if identity:
            self.window.api.request(
                "POST",
                "/api/v1/providers/configs/" + identity + "/test",
                {},
                success=lambda _: self.window.notify(self.window.tr("provider_test_ok")),
                timeout=60000,
            )

    def list_models(self):
        identity = self.saved.currentData()
        if identity:

            def received(models):
                self.models.clear()
                self.models.addItems(models)

            self.window.api.request(
                "GET",
                "/api/v1/providers/configs/" + identity + "/models",
                success=received,
                timeout=60000,
            )

    def add_model(self):
        identity = self.saved.currentData()
        if (
            identity
            and self.model_id.text().strip()
            and QMessageBox.question(
                self, self.window.tr("provider_add_model"), self.window.tr("provider_cost_confirm")
            )
            == QMessageBox.Yes
        ):
            self.window.api.request(
                "POST",
                "/api/v1/providers/configs/" + identity + "/models",
                {"model_id": self.model_id.text().strip(), "confirmed_external": True},
                success=lambda _: self.window.refresh_models(),
            )
