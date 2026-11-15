"""Small agent controls using RC8's Qt transport, themes and existing composer."""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
        self.folder_dialog = None
        self.seen = set()
        self.retry_id = None
        self.runs = []
        self.granted_folders = []
        self.folder_grant_cancelled_runs = set()
        self.compatibility_busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.settings_toggle = QPushButton(main.tr("agent_settings"))
        self.settings_toggle.setObjectName("compactToggle")
        self.settings_toggle.setCheckable(True)
        self.settings_toggle.setChecked(False)
        self.settings_toggle.hide()
        self.settings_toggle.toggled.connect(lambda _: self.visibility())
        self.settings_box = QWidget()
        settings_layout = QVBoxLayout(self.settings_box)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(8)
        self.mode = QComboBox()
        self.mode.setObjectName("agentMode")
        self.mode.addItem(main.tr("agent_chat"), "chat")
        self.mode.addItem(main.tr("agent_mode"), "agent")
        self.mode.setAccessibleName(main.tr("agent_work_mode"))
        self.mode.setToolTip(main.tr("agent_work_mode"))
        self.steps_label = QLabel(main.tr("agent_steps_label"))
        self.steps = QSpinBox()
        self.steps.setRange(1, 32)
        self.steps.setValue(8)
        self.steps.setToolTip(main.tr("agent_step_count"))
        self.protocol_label = QLabel(main.tr("agent_protocol_label"))
        self.protocol = QComboBox()
        self.protocol.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.protocol.setMinimumContentsLength(5)
        self.protocol.addItem("Auto", "auto")
        self.protocol.addItem("JSON", "structured")
        self.protocol.setToolTip(main.tr("agent_protocol_tooltip"))
        self.web_access = QCheckBox(main.tr("agent_web_access"))
        self.web_access.setToolTip(main.tr("agent_web_tooltip"))
        self.folder = QPushButton(main.tr("agent_folder"))
        self.folder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        steps_row = QHBoxLayout()
        steps_row.setContentsMargins(0, 0, 0, 0)
        steps_row.setSpacing(8)
        steps_row.addWidget(self.steps_label, 1)
        steps_row.addWidget(self.steps)
        settings_layout.addLayout(steps_row)

        proto_row = QHBoxLayout()
        proto_row.setContentsMargins(0, 0, 0, 0)
        proto_row.setSpacing(8)
        proto_row.addWidget(self.protocol_label, 1)
        proto_row.addWidget(self.protocol)
        settings_layout.addLayout(proto_row)

        settings_layout.addWidget(self.web_access)
        settings_layout.addWidget(self.folder)
        self.details = QFrame()
        self.details.setObjectName("drawerSection")
        inner = QVBoxLayout(self.details)
        inner.setContentsMargins(10, 10, 10, 10)
        inner.setSpacing(8)
        self.hint = QLabel(main.tr("agent_hint"))
        self.hint.setObjectName("mutedMeta")
        self.hint.setWordWrap(True)
        self.hint.hide()
        self.details.setToolTip(main.tr("agent_hint"))
        self.compatibility_label = QLabel()
        self.compatibility_label.setObjectName("mutedMeta")
        self.compatibility_label.setTextFormat(Qt.PlainText)
        self.compatibility_label.setWordWrap(True)
        self.compatibility_test = QPushButton(main.tr("agent_test_model"))
        self.compatibility_test.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.compatibility_test.clicked.connect(self.test_model)
        settings_layout.addWidget(self.compatibility_label)
        settings_layout.addWidget(self.compatibility_test)
        self.folders = QListWidget()
        self.folders.setMaximumHeight(52)
        self.folders.hide()
        settings_layout.addWidget(self.folders)
        self.revoke = QPushButton(main.tr("agent_revoke"))
        self.revoke.hide()
        settings_layout.addWidget(self.revoke, alignment=Qt.AlignLeft)
        self.activity_label = QLabel(main.tr("agent_activity"))
        self.activity_label.setObjectName("drawerHeading")
        self.inspect_hint = QLabel(main.tr("agent_inspect_hint"))
        self.inspect_hint.setObjectName("mutedMeta")
        self.inspect_hint.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([main.tr("agent_tool"), main.tr("agent_state"), "ms"])
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.setMaximumHeight(110)
        self.tree.setMinimumHeight(64)
        self.activity_label.hide()
        self.tree.hide()
        self.inspect_hint.hide()
        inner.addWidget(self.activity_label)
        inner.addWidget(self.tree)
        inner.addWidget(self.inspect_hint)
        inner.addWidget(self.settings_box)
        inner.addWidget(self.hint)
        self.status = QLabel()
        self.status.setObjectName("mutedMeta")
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.details)
        self.scroll.setMinimumHeight(44)
        layout.addWidget(self.scroll)
        layout.addWidget(self.status)
        self.retry_button = QPushButton(main.tr("agent_retry"))
        self.retry_button.setObjectName("primary")
        self.retry_button.clicked.connect(self.retry)
        self.retry_button.hide()
        retry_row = QHBoxLayout()
        retry_row.setContentsMargins(0, 0, 0, 0)
        retry_row.addWidget(self.retry_button)
        retry_row.addStretch()
        layout.addLayout(retry_row)
        self.scroll.hide()
        self.status.hide()
        self.details.hide()
        self.steps_label.hide()
        self.steps.hide()
        self.protocol_label.hide()
        self.protocol.hide()
        self.web_access.hide()
        self.folder.hide()
        self.mode.currentIndexChanged.connect(self.save_settings)
        self.steps.valueChanged.connect(self.save_settings)
        self.protocol.currentIndexChanged.connect(self.save_settings)
        self.web_access.clicked.connect(self.toggle_web_access)
        self.folder.clicked.connect(lambda: self.grant_folder())
        self.revoke.clicked.connect(self.revoke_folder)
        self.tree.itemDoubleClicked.connect(self.inspect)
        if hasattr(main, "transcript"):
            main.transcript.grant_folder_requested.connect(self.grant_folder)
            main.transcript.continue_run_requested.connect(self.continue_run)
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
        self.steps_label.setText(tr("agent_steps_label"))
        self.steps.setToolTip(tr("agent_step_count"))
        self.protocol_label.setText(tr("agent_protocol_label"))
        self.protocol.setToolTip(tr("agent_protocol_tooltip"))
        self.web_access.setText(tr("agent_web_access"))
        self.web_access.setToolTip(tr("agent_web_tooltip"))
        self.activity_label.setText(tr("agent_activity"))
        self.inspect_hint.setText(tr("agent_inspect_hint"))
        self.folder.setText(tr("agent_folder"))
        self.compatibility_test.setText(tr("agent_test_model"))
        self.settings_toggle.setText(tr("agent_settings"))
        self.retry_button.setText(tr("agent_retry"))
        self.revoke.setText(tr("agent_revoke"))
        self.hint.setText(tr("agent_hint"))
        self.details.setToolTip(tr("agent_hint"))
        self.tree.setHeaderLabels([tr("agent_tool"), tr("agent_state"), "ms"])
        self.refresh_compatibility()

    @staticmethod
    def grant_satisfies_run(run: dict | None, granted_folders: list[dict]) -> bool:
        if not isinstance(run, dict) or not granted_folders:
            return False
        requested = (run.get("requested_folder_path") or "").strip()
        suggested = (run.get("suggested_folder_name") or "").strip().casefold()
        alias_groups = {
            "pobrane": {"pobrane", "pobranych", "pobranym", "downloads"},
            "downloads": {"pobrane", "pobranych", "pobranym", "downloads"},
            "dokumenty": {"dokumenty", "dokumentów", "dokumentach", "documents"},
            "documents": {"dokumenty", "dokumentów", "dokumentach", "documents"},
            "pulpit": {"pulpit", "pulpicie", "pulpitu", "desktop"},
            "desktop": {"pulpit", "pulpicie", "pulpitu", "desktop"},
            "obrazy": {"obrazy", "obrazów", "obrazach", "pictures"},
            "pictures": {"obrazy", "obrazów", "obrazach", "pictures"},
            "muzyka": {"muzyka", "muzyki", "muzyce", "music"},
            "music": {"muzyka", "muzyki", "muzyce", "music"},
            "wideo": {"wideo", "videos"},
            "videos": {"wideo", "videos"},
        }
        if requested:
            expanded = (
                Path.home() / requested[2:] if requested.startswith("~/") else Path(requested)
            )
            for grant in granted_folders:
                gpath_raw = str(grant.get("path", "")).rstrip("/")
                if not gpath_raw:
                    continue
                gpath = Path(gpath_raw)
                if expanded.is_absolute():
                    if (
                        expanded == gpath
                        or (expanded.parent == gpath and not expanded.is_dir())
                        or (grant.get("subfolders") and gpath in expanded.parents)
                    ):
                        return True
                elif requested.lstrip("./").casefold() == gpath.name.casefold():
                    return True
            if not suggested:
                return False
        if suggested:
            aliases = alias_groups.get(suggested, {suggested})
            for grant in granted_folders:
                gpath_raw = str(grant.get("path", "")).rstrip("/")
                if not gpath_raw:
                    continue
                gpath = Path(gpath_raw)
                if gpath.name.casefold() in aliases:
                    return True
                if grant.get("subfolders") and gpath.is_dir():
                    try:
                        if any(
                            child.is_dir() and child.name.casefold() in aliases
                            for child in gpath.iterdir()
                        ):
                            return True
                    except OSError:
                        pass
            return False
        prior_ids = set(run.get("grants_at_failure") or [])
        current_ids = {g.get("id") for g in granted_folders if g.get("id")}
        return bool(current_ids - prior_ids) if prior_ids else bool(current_ids)

    def visibility(self):
        enabled = self.mode.currentData() == "agent"
        settings_open = enabled and self.settings_toggle.isChecked()
        self.settings_box.setVisible(settings_open)
        has_activity = self.tree.topLevelItemCount() > 0
        has_status = bool(self.status.text())
        retry_run = next((r for r in self.runs if r.get("id") == self.retry_id), None)
        has_retry = (
            bool(self.retry_id)
            and not self.active
            and (
                not retry_run
                or (
                    not retry_run.get("continued_by")
                    and (
                        retry_run.get("needs_folder_grant")
                        and self.grant_satisfies_run(retry_run, self.granted_folders)
                        or (
                            not retry_run.get("needs_folder_grant")
                            and retry_run.get("state") in {"failed", "cancelled", "interrupted"}
                        )
                    )
                )
            )
        )
        show_details = settings_open or (bool(self.active) and has_activity)
        self.details.setVisible(enabled and show_details)
        self.scroll.setVisible(enabled and show_details)
        if enabled and show_details:
            min_h = 96 if settings_open else 44
            target_h = max(min_h, self.details.sizeHint().height() + 4)
            self.scroll.setMinimumHeight(target_h)
            self.scroll.setMaximumHeight(max(target_h + 16, 480))
        self.status.setVisible(enabled and has_status)
        self.retry_button.setVisible(enabled and has_retry)
        self.setVisible(enabled and (show_details or has_status or has_retry))
        if hasattr(self.main, "_sync_agent_banner"):
            self.main._sync_agent_banner()

    def load(self, conversation):
        self.conversation = conversation
        self.timer.stop()
        self.active = None
        self.retry_id = None
        self.runs = []
        self.granted_folders = []
        self.folder_grant_cancelled_runs.clear()
        self.retry_button.hide()
        self.status.clear()
        self.status.hide()
        self.tree.clear()
        self.activity_label.hide()
        self.tree.hide()
        self.inspect_hint.hide()
        self.folders.clear()
        self.folders.hide()
        self.revoke.hide()
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
            if (
                records
                and records[0].get("needs_folder_grant")
                and not records[0].get("continued_by")
            ):
                self.retry_id = records[0]["id"]
                self.retry_button.setText(self.main.tr("agent_continue_task"))
                self.visibility()
            elif records and records[0]["state"] in {"failed", "cancelled", "interrupted"}:
                self.retry_id = records[0]["id"]
                self.retry_button.setText(self.main.tr("agent_retry"))
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
        target = next((r for r in self.runs if r.get("id") == self.retry_id), None)
        if (
            target
            and target.get("needs_folder_grant")
            and self.grant_satisfies_run(target, self.granted_folders)
        ):
            self.continue_run(target)
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
        self._start_retry(self.retry_id)

    def continue_run(self, run=None):
        run_id = run.get("id") if isinstance(run, dict) else self.retry_id
        if not run_id or self.active or self.settings_saving:
            return
        self._start_retry(run_id)

    def _start_retry(self, run_id):
        self.busy(True)

        def received(record):
            for existing in self.runs:
                if existing.get("id") == run_id:
                    existing["needs_folder_grant"] = False
                    existing["continued_by"] = record["id"]
            self.active = record["id"]
            self.retry_id = None
            self.render([record])
            self.timer.start()
            self.main.refresh_messages()

        def failed(code):
            self.busy(False)
            self.main.show_error(code)

        self.api.request(
            "POST",
            BASE + f"/runs/{run_id}/retry",
            {"parameters": self.main.request_parameters()},
            success=received,
            failure=failed,
        )

    def refresh_folders(self):
        conversation = self.conversation

        def received(records):
            if self.conversation != conversation:
                return
            self.granted_folders = list(records)
            self.folders.clear()
            for record in records:
                scope_txt = self.main.tr(
                    "agent_scope_read_write"
                    if record.get("allow_write", True)
                    else "agent_scope_read_only"
                )
                sub_txt = self.main.tr(
                    "agent_subfolders_label"
                    if record.get("subfolders", True)
                    else "agent_no_subfolders"
                )
                pers_txt = self.main.tr(
                    "agent_persistence_durable"
                    if record.get("persistent", False)
                    else "agent_persistence_session"
                )
                path_str = record["path"]
                elided = self.folders.fontMetrics().elidedText(path_str, Qt.ElideMiddle, 260)
                self.folders.addItem(f"{elided} · {scope_txt} · {sub_txt} · {pers_txt}")
                item = self.folders.item(self.folders.count() - 1)
                item.setData(Qt.UserRole, record["id"])
                item.setToolTip(f"{path_str}\n{scope_txt} · {sub_txt} · {pers_txt}")
            has_folders = bool(records)
            self.folders.setVisible(has_folders)
            self.revoke.setVisible(has_folders)
            pending_grant_run = next(
                (r for r in self.runs if r.get("needs_folder_grant") and not r.get("continued_by")),
                None,
            )
            if (
                pending_grant_run
                and not self.active
                and self.grant_satisfies_run(pending_grant_run, self.granted_folders)
            ):
                self.retry_id = pending_grant_run["id"]
                self.retry_button.setText(self.main.tr("agent_continue_task"))
            elif (
                pending_grant_run
                and self.retry_id == pending_grant_run["id"]
                and not self.grant_satisfies_run(pending_grant_run, self.granted_folders)
            ):
                self.retry_id = None
            if getattr(self.main, "messages", None):
                self.main.render_messages()
            self.visibility()

        self.api.request("GET", BASE + f"/conversations/{conversation}/folders", success=received)

    def create_folder_grant_dialog(self, path: str) -> QDialog:
        tr = self.main.tr
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("agent_folder"))
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        path_lbl = QLabel(f"{tr('agent_folder_path_label')} {path}")
        path_lbl.setTextFormat(Qt.PlainText)
        path_lbl.setWordWrap(True)
        layout.addWidget(path_lbl)
        warn_lbl = QLabel(tr("agent_folder_warning"))
        warn_lbl.setTextFormat(Qt.PlainText)
        warn_lbl.setWordWrap(True)
        layout.addWidget(warn_lbl)
        form = QFormLayout()
        dialog.scope_combo = QComboBox(dialog)
        dialog.scope_combo.addItem(tr("agent_scope_read_only"), False)
        dialog.scope_combo.addItem(tr("agent_scope_read_write"), True)
        form.addRow(QLabel(tr("agent_scope_label")), dialog.scope_combo)
        dialog.subfolders_check = QCheckBox(tr("agent_subfolders_label"), dialog)
        dialog.subfolders_check.setChecked(True)
        form.addRow(QLabel(""), dialog.subfolders_check)
        dialog.persistence_combo = QComboBox(dialog)
        dialog.persistence_combo.addItem(tr("agent_persistence_session"), False)
        dialog.persistence_combo.addItem(tr("agent_persistence_durable"), True)
        form.addRow(QLabel(tr("agent_persistence_label")), dialog.persistence_combo)
        dialog.sensitive_check = QCheckBox(tr("agent_sensitive_title"), dialog)
        dialog.sensitive_check.setChecked(False)
        dialog.sensitive_check.setToolTip(tr("agent_sensitive_warning"))
        form.addRow(QLabel(""), dialog.sensitive_check)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Yes | QDialogButtonBox.No, dialog)
        buttons.button(QDialogButtonBox.Yes).setText(tr("agent_folder"))
        buttons.button(QDialogButtonBox.No).setText(tr("agent_reject"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog

    def confirm_folder_grant(self, path: str) -> tuple[bool, bool, bool, bool, bool]:
        if not getattr(QMessageBox.question, "__module__", "").startswith("PySide6"):
            if (
                QMessageBox.question(
                    self,
                    self.main.tr("agent_folder"),
                    self.main.tr("agent_folder_warning") + "\n" + path,
                )
                != QMessageBox.Yes
            ):
                return False, False, True, True, False
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
            return True, sensitive, True, True, False
        dialog = self.folder_dialog = self.create_folder_grant_dialog(path)
        try:
            accepted = dialog.exec() == QDialog.Accepted
            return (
                accepted,
                dialog.sensitive_check.isChecked(),
                bool(dialog.scope_combo.currentData()),
                dialog.subfolders_check.isChecked(),
                bool(dialog.persistence_combo.currentData()),
            )
        finally:
            self.folder_dialog = None
            dialog.deleteLater()

    def grant_folder(self, run=None):
        start_dir = ""
        if isinstance(run, dict) and run.get("suggested_folder_name"):
            candidate = Path.home() / run["suggested_folder_name"]
            if candidate.is_dir():
                start_dir = str(candidate)
        path = (
            QFileDialog.getExistingDirectory(self, self.main.tr("agent_folder"), start_dir)
            if start_dir
            else QFileDialog.getExistingDirectory(self, self.main.tr("agent_folder"))
        )
        if not path:
            if isinstance(run, dict) and run.get("id"):
                self.folder_grant_cancelled_runs.add(run["id"])
                self.main.render_messages()
            return
        confirmed, sensitive, allow_write, subfolders, persistent = self.confirm_folder_grant(path)
        if not confirmed:
            if isinstance(run, dict) and run.get("id"):
                self.folder_grant_cancelled_runs.add(run["id"])
                self.main.render_messages()
            return
        if isinstance(run, dict) and run.get("id"):
            self.folder_grant_cancelled_runs.discard(run["id"])
        self.api.request(
            "POST",
            BASE + f"/conversations/{self.conversation}/folders",
            {
                "path": path,
                "confirmed": True,
                "include_sensitive": sensitive,
                "allow_write": allow_write,
                "subfolders": subfolders,
                "persistent": persistent,
            },
            success=lambda _: self.refresh_folders(),
            failure=self.main.show_error,
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
        if hasattr(self.main, "context_preset"):
            self.main.context_preset.setEnabled(not enabled)
        if enabled:
            self.main.stop_button.show()
            self.main.stop_button.setEnabled(True)
            self.main.generation_status.setText(self.main.tr("running"))
            self.retry_button.hide()
        elif not self.main.active_job:
            self.main.stop_button.setEnabled(False)
            self.main.stop_button.hide()
            self.main.generation_status.setText(self.main.tr("ready"))

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
            if record["state"] in TERMINAL:
                self.active = None
                self.timer.stop()
                self.busy(False)
                if self.dialog:
                    self.dialog.reject()
                if record.get("needs_folder_grant") and not record.get("continued_by"):
                    self.retry_id = record["id"]
                    self.retry_button.setText(self.main.tr("agent_continue_task"))
                elif record["state"] in {"failed", "cancelled", "interrupted"}:
                    self.retry_id = record["id"]
                    self.retry_button.setText(self.main.tr("agent_retry"))
                else:
                    self.retry_id = None
                self.render([record])
                self.main.refresh_messages()
            else:
                self.render([record])

        def failed(code):
            self.pending_poll = False
            self.status.setText(self.main.tr(code))

        self.api.request("GET", BASE + f"/runs/{run_id}", success=received, failure=failed)

    def stop(self):
        if self.active:
            self.main.stop_button.setEnabled(False)
            self.api.request(
                "POST",
                BASE + f"/runs/{self.active}/cancel",
                success=lambda _: self.poll(),
                failure=lambda _: self.poll(),
            )

    def render(self, records):
        self.tree.clear()
        if not records:
            self.runs = []
            self.status.setText("")
        elif len(records) == 1 and self.runs:
            updated = False
            for idx, existing in enumerate(self.runs):
                if existing.get("id") == records[0].get("id"):
                    self.runs[idx] = records[0]
                    updated = True
                    break
            if not updated:
                self.runs.insert(0, records[0])
        else:
            self.runs = list(records)
        for record in records[:1]:
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
            if record["state"] == "completed" and not self.active:
                self.status.setText("")
            elif record["state"] in {"failed", "cancelled", "interrupted"} and not record["steps"]:
                self.status.setText(
                    self.main.tr(record.get("error_code") or "agent_" + record["state"])
                )
            else:
                extra = self.main.tr(
                    "agent_progress", done=count, remaining=max(0, limit - attempts)
                )
                if context:
                    extra += self.main.tr(
                        "agent_context_usage", used=context["approx_tokens"], limit=context["limit"]
                    )
                if record["steps"]:
                    current = record["steps"][-1]
                    extra += (
                        " · " + current["tool"] + ": " + self.main.tr("agent_" + current["state"])
                    )
                if record.get("tool_mode"):
                    extra += " · " + self.main.tr("agent_cap_" + record["tool_mode"])
                self.status.setText(
                    self.main.tr(record.get("error_code") or "agent_" + record["state"])
                    + " · "
                    + extra
                )
        has_activity = self.tree.topLevelItemCount() > 0
        self.activity_label.setVisible(has_activity)
        self.tree.setVisible(has_activity)
        self.inspect_hint.setVisible(has_activity)
        self.status.setVisible(self.mode.currentData() == "agent" and bool(self.status.text()))
        self.scroll.setMaximumHeight(220 if has_activity else 160)
        self.visibility()
        if self.active:
            self.busy(True)
            active_run = records[0] if records else None
            if active_run and active_run.get("steps"):
                last_step = active_run["steps"][-1]
                if last_step.get("state") in {"queued", "running", "waiting"}:
                    self.main.generation_status.setText(
                        self.main.tr("agent_executing_tool", tool=last_step["tool"])
                    )
        if not self.active and getattr(self.main, "messages", None):
            self.main.render_messages()

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
