"""Small agent controls using RC8's Qt transport, themes and existing composer."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

BASE = "/api/v1/agents"
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class AgentPanel(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main, self.api = main, main.api
        self.conversation = None
        self.active = None
        self.dialog = None
        self.seen = set()
        self.retry_id = None
        self.compatibility_busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.setObjectName("agentMode")
        self.mode.addItem(main.tr("agent_chat"), "chat")
        self.mode.addItem(main.tr("agent_mode"), "agent")
        self.mode.setAccessibleName(main.tr("agent_work_mode"))
        self.mode.setToolTip(main.tr("agent_work_mode"))
        self.steps = QSpinBox()
        self.steps.setRange(1, 32)
        self.steps.setValue(8)
        self.steps.setToolTip(main.tr("agent_step_count"))
        self.protocol = QComboBox()
        self.protocol.addItem("Auto", "auto")
        self.protocol.addItem("JSON", "structured")
        self.web_access = QCheckBox(main.tr("agent_web_access"))
        self.web_access.setToolTip(main.tr("agent_web_tooltip"))
        self.folder = QPushButton(main.tr("agent_folder"))
        row.addWidget(self.mode)
        row.addWidget(self.steps)
        row.addWidget(self.protocol)
        row.addWidget(self.web_access)
        row.addWidget(self.folder)
        layout.addLayout(row)
        self.details = QWidget()
        inner = QVBoxLayout(self.details)
        inner.setContentsMargins(0, 0, 0, 0)
        self.hint = QLabel(main.tr("agent_hint"))
        self.hint.setWordWrap(True)
        self.compatibility_label = QLabel()
        self.compatibility_label.setTextFormat(Qt.PlainText)
        self.compatibility_label.setWordWrap(True)
        self.compatibility_test = QPushButton(main.tr("agent_test_model"))
        self.compatibility_test.clicked.connect(self.test_model)
        inner.addWidget(self.compatibility_label)
        inner.addWidget(self.compatibility_test)
        inner.addWidget(self.hint)
        self.folders = QListWidget()
        self.folders.setMaximumHeight(58)
        inner.addWidget(self.folders)
        self.revoke = QPushButton(main.tr("agent_revoke"))
        inner.addWidget(self.revoke)
        self.activity_label = QLabel(main.tr("agent_activity"))
        self.activity_label.setObjectName("agentActivityTitle")
        self.inspect_hint = QLabel(main.tr("agent_inspect_hint"))
        self.inspect_hint.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([main.tr("agent_tool"), main.tr("agent_state"), "ms"])
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.setMaximumHeight(110)
        self.tree.setMinimumHeight(70)
        inner.insertWidget(0, self.activity_label)
        inner.insertWidget(1, self.tree)
        inner.insertWidget(2, self.inspect_hint)
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(self.details)
        self.scroll.setMaximumHeight(150)
        self.scroll.setMinimumHeight(90)
        layout.addWidget(self.scroll)
        layout.addWidget(self.status)
        self.retry_button = QPushButton(main.tr("agent_retry"))
        self.retry_button.clicked.connect(self.retry)
        self.retry_button.hide()
        layout.addWidget(self.retry_button)
        self.scroll.hide()
        self.status.hide()
        self.details.hide()
        self.steps.hide()
        self.protocol.hide()
        self.web_access.hide()
        self.folder.hide()
        self.mode.currentIndexChanged.connect(self.save_settings)
        self.steps.valueChanged.connect(self.save_settings)
        self.protocol.currentIndexChanged.connect(self.save_settings)
        self.web_access.clicked.connect(self.toggle_web_access)
        self.folder.clicked.connect(self.grant_folder)
        self.revoke.clicked.connect(self.revoke_folder)
        self.tree.itemDoubleClicked.connect(self.inspect)
        self.timer = QTimer(self)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.poll)
        main.model_combo.currentIndexChanged.connect(self.refresh_compatibility)
        self.pending_poll = False
        self.settings_saving = False
        self.settings_loading = False

    def retranslate(self):
        tr = self.main.tr
        self.mode.setItemText(0, tr("agent_chat"))
        self.mode.setItemText(1, tr("agent_mode"))
        self.mode.setAccessibleName(tr("agent_work_mode"))
        self.mode.setToolTip(tr("agent_work_mode"))
        self.steps.setToolTip(tr("agent_step_count"))
        self.web_access.setText(tr("agent_web_access"))
        self.web_access.setToolTip(tr("agent_web_tooltip"))
        self.activity_label.setText(tr("agent_activity"))
        self.inspect_hint.setText(tr("agent_inspect_hint"))
        self.folder.setText(tr("agent_folder"))
        self.compatibility_test.setText(tr("agent_test_model"))
        self.retry_button.setText(tr("agent_retry"))
        self.revoke.setText(tr("agent_revoke"))
        self.hint.setText(tr("agent_hint"))
        self.tree.setHeaderLabels([tr("agent_tool"), tr("agent_state"), "ms"])
        self.refresh_compatibility()

    def visibility(self):
        enabled = self.mode.currentData() == "agent"
        for widget in (
            self.details,
            self.scroll,
            self.status,
            self.steps,
            self.protocol,
            self.web_access,
            self.folder,
        ):
            widget.setVisible(enabled)
        self.retry_button.setVisible(enabled and bool(self.retry_id) and not self.active)

    def load(self, conversation):
        self.conversation = conversation
        self.timer.stop()
        self.active = None
        self.retry_id = None
        self.retry_button.hide()
        self.tree.clear()
        self.folders.clear()
        self.pending_poll = False
        self.settings_loading = bool(conversation)
        self.mode.setEnabled(not self.settings_loading)
        if not conversation:
            for widget in (self.mode, self.web_access):
                widget.blockSignals(True)
            self.mode.setCurrentIndex(self.mode.findData("chat"))
            self.web_access.setChecked(False)
            for widget in (self.mode, self.web_access):
                widget.blockSignals(False)
            self.visibility()
            return

        def loaded(record):
            if self.conversation != conversation:
                return
            for widget in (self.mode, self.steps, self.protocol, self.web_access):
                widget.blockSignals(True)
            self.mode.setCurrentIndex(self.mode.findData(record["mode"]))
            self.steps.setValue(record["max_steps"])
            self.protocol.setCurrentIndex(self.protocol.findData(record["protocol"]))
            self.web_access.setChecked(bool(record.get("web_access", False)))
            for widget in (self.mode, self.steps, self.protocol, self.web_access):
                widget.blockSignals(False)
            self.settings_loading = False
            for widget in (self.mode, self.steps, self.protocol, self.web_access):
                widget.setEnabled(not self.active)
            self.visibility()

        def load_failed(code):
            if self.conversation == conversation:
                self.settings_loading = False
                for widget in (self.mode, self.steps, self.protocol, self.web_access):
                    widget.setEnabled(not self.active)
                self.main.show_error(code)

        self.api.request(
            "GET",
            BASE + f"/conversations/{conversation}/settings",
            success=loaded,
            failure=load_failed,
        )
        self.refresh_folders()
        self.refresh_compatibility()

        def history(records):
            if self.conversation != conversation:
                return
            for record in records:
                if record["state"] not in TERMINAL:
                    self.active = record["id"]
                    self.timer.start()
                    break
            self.render(records)
            if records and records[0]["state"] in {"failed", "cancelled", "interrupted"}:
                self.retry_id = records[0]["id"]
                self.visibility()

        self.api.request("GET", BASE + f"/conversations/{conversation}/runs", success=history)

    def toggle_web_access(self, checked):
        if checked and (
            QMessageBox.question(
                self,
                self.main.tr("agent_web_access"),
                self.main.tr("agent_web_warning"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            self.web_access.blockSignals(True)
            self.web_access.setChecked(False)
            self.web_access.blockSignals(False)
            return
        self.save_settings()

    def save_settings(self):
        self.visibility()
        if not self.conversation or self.settings_loading:
            return
        conversation = self.conversation
        body = {
            "mode": self.mode.currentData(),
            "max_steps": self.steps.value(),
            "protocol": self.protocol.currentData(),
            "web_access": self.web_access.isChecked(),
        }
        self.settings_saving = True
        for widget in (self.mode, self.steps, self.protocol, self.web_access):
            widget.setEnabled(False)

        def saved(_):
            self.settings_saving = False
            if self.conversation == conversation:
                for widget in (self.mode, self.steps, self.protocol, self.web_access):
                    widget.setEnabled(not self.active)

        def failed(code):
            saved(None)
            self.main.show_error(code)
            if self.conversation == conversation:
                self.load(conversation)

        self.api.request(
            "PUT",
            BASE + f"/conversations/{conversation}/settings",
            body,
            success=saved,
            failure=failed,
        )

    def refresh_compatibility(self, *_):
        model = self.main.model_combo.currentData()
        if not model:
            self.compatibility_label.setText(self.main.tr("model_required"))
            return

        def received(info):
            if self.main.model_combo.currentData() != model:
                return
            evidence = self.main.tr("agent_tested" if info["tested"] else "agent_declared")
            self.compatibility_label.setText(
                self.main.tr("agent_cap_" + info["status"]) + " · " + evidence
            )
            self.compatibility_label.setToolTip(
                self.main.tr(info.get("error_code") or "agent_hint")
            )

        self.api.request("GET", BASE + f"/models/{model}/compatibility", success=received)

    def test_model(self):
        model = self.main.model_combo.currentData()
        if not model or self.active or self.compatibility_busy or self.main.active_job:
            return
        if (
            QMessageBox.question(
                self,
                self.main.tr("agent_test_model"),
                self.main.tr("agent_test_warning"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        self.compatibility_busy = True
        self.compatibility_test.setEnabled(False)
        self.main.send_button.setEnabled(False)
        self.compatibility_label.setText(self.main.tr("agent_running"))

        def finished(_):
            self.compatibility_busy = False
            self.compatibility_test.setEnabled(True)
            self.main.send_button.setEnabled(True)
            self.refresh_compatibility()

        def failed(code):
            finished(None)
            self.main.show_error(code)

        self.api.request(
            "POST",
            BASE + f"/models/{model}/compatibility-test",
            {
                "confirmed": True,
                "parameters": self.main.request_parameters(),
                "protocol": self.protocol.currentData(),
            },
            success=finished,
            failure=failed,
            timeout=45000,
        )

    def retry(self):
        if not self.retry_id or self.active or self.settings_saving:
            return
        if (
            QMessageBox.question(
                self,
                self.main.tr("agent_retry"),
                self.main.tr("agent_retry_warning"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        self.busy(True)

        def received(record):
            self.active = record["id"]
            self.render([record])
            self.timer.start()
            self.main.refresh_messages()

        def failed(code):
            self.busy(False)
            self.main.show_error(code)

        self.api.request(
            "POST",
            BASE + f"/runs/{self.retry_id}/retry",
            {"parameters": self.main.request_parameters()},
            success=received,
            failure=failed,
        )

    def refresh_folders(self):
        conversation = self.conversation

        def received(records):
            if self.conversation != conversation:
                return
            self.folders.clear()
            for record in records:
                self.folders.addItem(record["path"])
                self.folders.item(self.folders.count() - 1).setData(Qt.UserRole, record["id"])

        self.api.request("GET", BASE + f"/conversations/{conversation}/folders", success=received)

    def grant_folder(self):
        path = QFileDialog.getExistingDirectory(self, self.main.tr("agent_folder"))
        if not path:
            return
        if (
            QMessageBox.question(
                self,
                self.main.tr("agent_folder"),
                self.main.tr("agent_folder_warning") + "\n" + path,
            )
            != QMessageBox.Yes
        ):
            return
        sensitive = (
            QMessageBox.question(
                self,
                self.main.tr("agent_sensitive_title"),
                self.main.tr("agent_sensitive_warning"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            == QMessageBox.Yes
        )
        self.api.request(
            "POST",
            BASE + f"/conversations/{self.conversation}/folders",
            {"path": path, "confirmed": True, "include_sensitive": sensitive},
            success=lambda _: self.refresh_folders(),
        )

    def revoke_folder(self):
        item = self.folders.currentItem()
        if item:
            self.api.request(
                "DELETE",
                BASE + f"/conversations/{self.conversation}/folders/" + item.data(Qt.UserRole),
                success=lambda _: self.refresh_folders(),
            )

    def busy(self, enabled):
        for widget in (
            self.mode,
            self.steps,
            self.protocol,
            self.web_access,
            self.folder,
            self.compatibility_test,
            self.retry_button,
            self.main.send_button,
            self.main.model_combo,
            self.main.conversation_list,
            self.main.new_button,
            self.main.context_mode,
            self.main.context_tokens,
            self.main.context_save,
        ):
            widget.setEnabled(not enabled)
        self.main.stop_button.setEnabled(enabled)
        if enabled:
            self.retry_button.hide()

    def send(self, content, model, parameters):
        if self.active or self.settings_saving or not self.conversation:
            return
        self.main._submitting = True
        self.busy(True)

        def submitted(record):
            self.main._submitting = False
            self.main.composer.clear()
            self.active = record["id"]
            self.main.refresh_messages()
            self.render([record])
            self.timer.start()

        def failure(code):
            self.main._submitting = False
            self.busy(False)
            self.main.show_error(code)

        self.api.request(
            "POST",
            BASE + f"/conversations/{self.conversation}/runs",
            {"content": content, "model_id": model, "parameters": parameters},
            success=submitted,
            failure=failure,
        )

    def poll(self):
        if not self.active or self.pending_poll:
            return
        run_id = self.active
        self.pending_poll = True

        def received(record):
            self.pending_poll = False
            if self.active != run_id:
                return
            self.render([record])
            if record["state"] in TERMINAL:
                self.active = None
                self.timer.stop()
                self.busy(False)
                if self.dialog:
                    self.dialog.reject()
                self.retry_id = (
                    record["id"]
                    if record["state"] in {"failed", "cancelled", "interrupted"}
                    else None
                )
                self.visibility()
                self.main.refresh_messages()

        def failed(code):
            self.pending_poll = False
            self.status.setText(self.main.tr(code))

        self.api.request("GET", BASE + f"/runs/{run_id}", success=received, failure=failed)

    def stop(self):
        if self.active:
            self.api.request(
                "POST", BASE + f"/runs/{self.active}/cancel", success=lambda _: self.poll()
            )

    def render(self, records):
        self.tree.clear()
        for record in records:
            plan = record.get("plan", [])
            if plan:
                parent = QTreeWidgetItem([self.main.tr("agent_plan"), "", ""])
                for item in plan:
                    parent.addChild(
                        QTreeWidgetItem([item["title"], self.main.tr("agent_" + item["state"]), ""])
                    )
                self.tree.addTopLevelItem(parent)
                parent.setExpanded(True)
            for step in record["steps"]:
                item = QTreeWidgetItem(
                    [step["tool"], self.main.tr("agent_" + step["state"]), str(step["duration_ms"])]
                )
                item.setData(0, Qt.UserRole, step)
                item.addChild(QTreeWidgetItem([step["summary"], step.get("error_code") or "", ""]))
                self.tree.addTopLevelItem(item)
                if step.get("proposal_id") and step["proposal_id"] not in self.seen:
                    self.approval(record["id"], step)
            count = sum(step["state"] == "completed" for step in record["steps"])
            attempts = len(record["steps"])
            limit = record.get("step_limit", self.steps.value())
            context = record.get("context", {})
            extra = self.main.tr("agent_progress", done=count, remaining=max(0, limit - attempts))
            if context:
                extra += self.main.tr(
                    "agent_context_usage", used=context["approx_tokens"], limit=context["limit"]
                )
            if record["steps"]:
                current = record["steps"][-1]
                extra += " · " + current["tool"] + ": " + self.main.tr("agent_" + current["state"])
            if record.get("tool_mode"):
                extra += " · " + self.main.tr("agent_cap_" + record["tool_mode"])
            self.status.setText(
                self.main.tr(record.get("error_code") or "agent_" + record["state"]) + " · " + extra
            )
        if self.active:
            self.busy(True)

    def approval(self, run_id, step):
        self.seen.add(step["proposal_id"])
        dialog = self.dialog = QDialog(self)
        dialog.setWindowTitle(self.main.tr("agent_review"))
        dialog.resize(650, 450)
        layout = QVBoxLayout(dialog)
        label = QLabel(step["path"])
        label.setTextFormat(Qt.PlainText)
        layout.addWidget(label)
        diff = QPlainTextEdit()
        diff.setReadOnly(True)
        diff.setPlainText(step["diff"] or self.main.tr("agent_no_diff"))
        layout.addWidget(diff)
        buttons = QDialogButtonBox(QDialogButtonBox.Yes | QDialogButtonBox.No)
        buttons.button(QDialogButtonBox.Yes).setText(self.main.tr("agent_approve"))
        buttons.button(QDialogButtonBox.No).setText(self.main.tr("agent_reject"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def finished(result):
            self.dialog = None
            self.api.request(
                "POST",
                BASE + f"/runs/{run_id}/steps/{step['id']}/approval",
                {"proposal_id": step["proposal_id"], "approved": result == QDialog.Accepted},
                failure=lambda _: None,
            )
            dialog.deleteLater()

        dialog.finished.connect(finished)
        dialog.show()

    def inspect(self, item, _column=0):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        result = data.get("result") or data.get("result_summary") or {}
        dialog = QDialog(self)
        dialog.setWindowTitle(data["tool"])
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(
            result.get("text")
            or "\n".join(f"{k}: {v}" for k, v in result.items())
            or (
                self.main.tr(data["error_code"])
                + "\n"
                + "\n".join(f"{e['field']}: {e['type']}" for e in data.get("error_details", []))
                if data.get("error_code")
                else ""
            )
            or data["summary"]
        )
        layout.addWidget(text)
        dialog.resize(600, 380)
        dialog.exec()
