"""Native widgets for the existing API. Network and inference never block Qt."""

import html
import os
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from omnicore.desktop.config import data_path
from omnicore.desktop.i18n import Translator

TEXT = "/api/v1/text"
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def human_size(value):
    if value is None:
        return "—"
    number = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if number < 1024:
            return f"{number:.1f} {unit}"
        number /= 1024
    return f"{number:.1f} PiB"


class MainWindow(QMainWindow):
    connected = Signal()

    def __init__(self, api, session, config):
        super().__init__()
        self.api, self.session, self.config = api, session, config
        self.tr = Translator(config.locale)
        self._texts = []
        self.conversations, self.models, self.messages = [], [], []
        self.current_id = None
        self.active_job = None
        self._submitting = False
        self._loading_model = False
        self.last_job = None
        self.downloads, self.remote_files = [], []
        self.engines = []
        self.is_connected = False
        self._closing = False
        self._allow_close = False
        self._pending_import = None
        self._health_pending = set()
        self.setWindowTitle("OmniCore · 0.1.0 Alpha")
        self.resize(1280, 820)
        self.setMinimumSize(920, 640)
        self._build()
        api.error.connect(self.show_error)
        api.snapshot.connect(self.generation_snapshot)
        api.stream_closed.connect(self.stream_closed)
        session.ready.connect(self.backend_ready)
        session.failed.connect(self.show_error)
        session.log.connect(self.log_event)
        session.stopped.connect(self._stopped)
        self._poll = QTimer(self)
        self._poll.setInterval(1500)
        self._poll.timeout.connect(self.refresh_downloads)
        self._poll.start()
        QApplication.instance().styleHints().colorSchemeChanged.connect(
            lambda _: self.apply_theme()
        )
        for key, handler in (
            ("Ctrl+N", self.new_conversation),
            ("Ctrl+Return", self.send_message),
            ("Escape", self.stop_generation),
            ("Ctrl+,", lambda: self.navigate(2)),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(handler)
        self.retranslate()
        self.apply_theme()

    def label(self, key, *, title=False):
        label = QLabel(self.tr(key))
        label.setWordWrap(True)
        label.setObjectName("title" if title else "label")
        self._texts.append((label, key))
        return label

    def button(self, key, handler, *, primary=False):
        button = QPushButton(self.tr(key))
        button.setCursor(Qt.PointingHandCursor)
        if primary:
            button.setObjectName("primary")
        button.clicked.connect(handler)
        self._texts.append((button, key))
        return button

    @staticmethod
    def row(*widgets):
        layout = QHBoxLayout()
        layout.setSpacing(10)
        for widget in widgets:
            layout.addWidget(widget)
        return layout

    def _build(self):
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(204)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(20, 28, 20, 24)
        brand = QLabel("◈  OmniCore")
        brand.setObjectName("brand")
        side.addWidget(brand)
        side.addWidget(self.label("alpha"))
        side.addSpacing(38)
        self.nav = []
        for index, key in enumerate(("chat", "models", "settings", "diagnostics")):
            button = self.button(key, lambda checked=False, i=index: self.navigate(i))
            button.setCheckable(True)
            button.setObjectName("nav")
            side.addWidget(button)
            self.nav.append(button)
        side.addStretch()
        side.addWidget(self.label("tagline"))
        layout.addWidget(sidebar)
        main = QWidget()
        body = QVBoxLayout(main)
        body.setContentsMargins(28, 22, 28, 22)
        header = QHBoxLayout()
        self.page_title = self.label("chat", title=True)
        header.addWidget(self.page_title)
        header.addStretch()
        self.connection = self.label("connecting")
        self.connection.setObjectName("badge")
        header.addWidget(self.connection)
        body.addLayout(header)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.PlainText)
        self.notice.setObjectName("notice")
        self.notice.hide()
        body.addWidget(self.notice)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        self._build_chat()
        self._build_models()
        self._build_settings()
        self._build_diagnostics()
        layout.addWidget(main, 1)
        self.nav[0].setChecked(True)
        self.statusBar().showMessage(self.tr("connecting"))
        self.pages.setEnabled(False)

    def _build_chat(self):
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 12, 0, 0)
        splitter = QSplitter()
        outer.addWidget(splitter)
        collection = QWidget()
        left = QVBoxLayout(collection)
        left.setContentsMargins(0, 0, 16, 0)
        self.new_button = self.button("new_chat", self.new_conversation, primary=True)
        left.addWidget(self.new_button)
        self.conversation_list = QListWidget()
        self.conversation_list.setObjectName("conversations")
        self.conversation_list.currentItemChanged.connect(self.select_conversation)
        left.addWidget(self.conversation_list, 1)
        left.addLayout(
            self.row(
                self.button("rename", self.rename_conversation),
                self.button("delete", self.delete_conversation),
            )
        )
        splitter.addWidget(collection)
        pane = QWidget()
        chat = QVBoxLayout(pane)
        chat.setContentsMargins(0, 0, 0, 0)
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(180)
        self.model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.model_combo.currentIndexChanged.connect(self.model_selected)
        chat.addLayout(self.row(self.model_combo, self.button("refresh", self.refresh_models)))
        self.transcript = QTextBrowser()
        self.transcript.setObjectName("transcript")
        self.transcript.setOpenExternalLinks(False)
        chat.addWidget(self.transcript, 1)
        self.generation_status = self.label("ready")
        chat.addWidget(self.generation_status)
        self.composer = QPlainTextEdit()
        self.composer.setObjectName("composer")
        self.composer.setMaximumHeight(128)
        self.composer.setMinimumHeight(94)
        chat.addWidget(self.composer)
        self.send_button = self.button("send", self.send_message, primary=True)
        self.stop_button = self.button("stop", self.stop_generation)
        self.stop_button.setEnabled(False)
        chat.addLayout(
            self.row(self.button("copy", self.copy_answer), self.stop_button, self.send_button)
        )
        splitter.addWidget(pane)
        splitter.setSizes([242, 730])
        splitter.setStretchFactor(1, 1)
        self.pages.addWidget(page)

    def _build_models(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.addWidget(self.label("model_hint"))
        self.model_tabs = QTabWidget()
        layout.addWidget(self.model_tabs, 1)
        installed = QWidget()
        local = QVBoxLayout(installed)
        self.engine_filter = QComboBox()
        self.engine_filter.addItems(["llama.cpp", "ollama"])
        self.engine_filter.currentTextChanged.connect(self.refresh_model_table)
        local.addLayout(
            self.row(
                self.button("import_gguf", self.choose_gguf, primary=True),
                self.engine_filter,
                self.button("sync_ollama", self.sync_ollama),
                self.button("refresh", self.refresh_models),
            )
        )
        self.model_table = QTableWidget(0, 4)
        self.model_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.model_table.setSelectionMode(QTableWidget.SingleSelection)
        self.model_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.model_table.verticalHeader().hide()
        self.model_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.model_table.itemSelectionChanged.connect(self.model_details)
        local.addWidget(self.model_table, 1)
        self.model_detail = self.label("model_details")
        self.model_detail.setTextFormat(Qt.PlainText)
        local.addWidget(self.model_detail)
        self.load_button = self.button("load", self.load_model, primary=True)
        local.addLayout(
            self.row(
                self.load_button,
                self.button("unload", self.unload_model),
                self.button("remove_entry", self.remove_model),
            )
        )
        self.model_tabs.addTab(installed, "")
        remote = QWidget()
        hf = QVBoxLayout(remote)
        hf.addWidget(self.label("download_hint"))
        self.hf_query = QLineEdit()
        self.hf_query.returnPressed.connect(self.search_hf)
        hf.addLayout(self.row(self.hf_query, self.button("search", self.search_hf)))
        self.hf_results = QListWidget()
        self.hf_results.itemDoubleClicked.connect(lambda _: self.list_hf_files())
        hf.addWidget(self.hf_results, 1)
        hf.addWidget(self.button("files", self.list_hf_files))
        self.hf_files = QComboBox()
        hf.addWidget(self.hf_files)
        hf.addWidget(self.button("download_file", self.download_file, primary=True))
        self.download_list = QComboBox()
        hf.addWidget(self.download_list)
        self.download_progress = QProgressBar()
        self.download_progress.setValue(0)
        hf.addWidget(self.download_progress)
        hf.addLayout(
            self.row(
                self.button("cancel_download", self.cancel_download),
                self.button("resume_download", self.resume_download),
                self.button("import_download", self.import_download),
            )
        )
        self.model_tabs.addTab(remote, "")
        self.pages.addWidget(page)

    def _build_settings(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(12, 22, 24, 24)
        form.setVerticalSpacing(16)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.language = QComboBox()
        self.language.addItem("Polski", "pl-PL")
        self.language.addItem("English", "en-US")
        self.language.setCurrentIndex(self.language.findData(self.config.locale))
        self.language.currentIndexChanged.connect(self.preview_language)
        form.addRow(self.label("language"), self.language)
        self.theme = QComboBox()
        for key in ("system", "light", "dark"):
            self.theme.addItem(self.tr(key), key)
        self.theme.setCurrentIndex(self.theme.findData(self.config.theme))
        self.theme.currentIndexChanged.connect(self.preview_theme)
        form.addRow(self.label("theme"), self.theme)
        self.roots = QListWidget()
        self.roots.setMaximumHeight(100)
        self.roots.addItems(self.config.model_roots)
        form.addRow(self.label("model_roots"), self.roots)
        form.addRow(
            self.row(
                self.button("add_directory", self.add_directory),
                self.button("remove_directory", self.remove_directory),
            )
        )
        self.llama_path = QLineEdit(self.config.llama_server)
        form.addRow(self.label("llama_server"), self.llama_path)
        form.addRow(self.button("browse", self.choose_llama))
        self.ollama_url = QLineEdit(self.config.ollama_url)
        form.addRow(self.label("ollama_url"), self.ollama_url)
        self.ollama_enabled = QCheckBox()
        self.ollama_enabled.setChecked(self.config.ollama_enabled)
        self._texts.append((self.ollama_enabled, "ollama_enabled"))
        form.addRow(self.ollama_enabled)
        form.addRow(self.label("generation", title=True))
        self.parameter_inputs = {}
        defaults = {
            "temperature": 0.7,
            "top_p": 0.9,
            "top_k": 40,
            "repeat_penalty": 1.1,
            "max_tokens": 256,
            "context_size": 2048,
            "seed": 0,
            "gpu_layers": 0,
        }
        ranges = {
            "temperature": (0, 2),
            "top_p": (0.01, 1),
            "top_k": (0, 1000),
            "repeat_penalty": (0.01, 3),
            "max_tokens": (1, 32768),
            "context_size": (128, 131072),
            "seed": (0, 2**31 - 1),
            "gpu_layers": (0, 999),
        }
        for key, default in defaults.items():
            box = QDoubleSpinBox() if isinstance(default, float) else QSpinBox()
            box.setRange(*ranges[key])
            if isinstance(default, float):
                box.setSingleStep(0.05)
            box.setValue(self.config.parameters.get(key, default))
            form.addRow(self.label(key), box)
            self.parameter_inputs[key] = box
        self.device = QLineEdit(self.config.parameters.get("device", "cpu"))
        form.addRow(self.label("device"), self.device)
        self.system_prompt = QPlainTextEdit(self.config.parameters.get("system_prompt", ""))
        self.system_prompt.setMaximumHeight(100)
        form.addRow(self.label("system_prompt"), self.system_prompt)
        form.addRow(self.label("settings_hint"))
        form.addRow(self.button("save", self.save_settings, primary=True))
        self.about = QLabel()
        self.about.setWordWrap(True)
        self.about.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow(self.about)
        scroll.setWidget(page)
        self.pages.addWidget(scroll)

    def _build_diagnostics(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self.label("diagnostics_hint"))
        layout.addWidget(self.button("refresh", self.refresh_diagnostics))
        self.diagnostic_text = QPlainTextEdit()
        self.diagnostic_text.setReadOnly(True)
        layout.addWidget(self.diagnostic_text, 2)
        layout.addWidget(self.label("events"))
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.document().setMaximumBlockCount(250)
        layout.addWidget(self.logs, 1)
        self.pages.addWidget(page)

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        self.page_title.setText(self.tr(("chat", "models", "settings", "diagnostics")[index]))
        for i, button in enumerate(self.nav):
            button.setChecked(i == index)
        effect = QGraphicsOpacityEffect(self.pages)
        self.pages.setGraphicsEffect(effect)
        self._animation = QPropertyAnimation(effect, b"opacity", self)
        self._animation.setDuration(140)
        self._animation.setStartValue(0.65)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.start()
        if index == 3:
            self.refresh_diagnostics()

    def retranslate(self):
        for widget, key in self._texts:
            widget.setText(self.tr(key))
        self.page_title.setText(
            self.tr(("chat", "models", "settings", "diagnostics")[self.pages.currentIndex()])
        )
        self.composer.setPlaceholderText(self.tr("composer"))
        self.hf_query.setPlaceholderText(self.tr("hf_query"))
        self.model_tabs.setTabText(0, self.tr("installed"))
        self.model_tabs.setTabText(1, self.tr("download"))
        for index, key in enumerate(("system", "light", "dark")):
            self.theme.setItemText(index, self.tr(key))
        self.connection.setText(self.tr("connected" if self.is_connected else "connecting"))
        self.about.setText(self.tr("about", path=data_path()))
        self.refresh_model_table()
        self.render_messages()
        self._fill_conversations()

    def preview_language(self):
        self.config.locale = self.language.currentData()
        self.tr = Translator(self.config.locale)
        self.retranslate()

    def preview_theme(self):
        self.config.theme = self.theme.currentData()
        self.apply_theme()

    def system_theme_changed(self, _scheme):
        self.apply_theme()

    def apply_theme(self):
        dark = self.config.theme == "dark" or (
            self.config.theme == "system"
            and QApplication.instance().styleHints().colorScheme() == Qt.ColorScheme.Dark
        )
        bg, panel, field, fg, muted, border = (
            ("#10151f", "#161e2b", "#1d2736", "#ecf1f9", "#9daec4", "#2b3749")
            if dark
            else ("#f5f6fa", "#ffffff", "#edf0f6", "#202b3c", "#607189", "#dce2ec")
        )
        accent = "#8b80f9" if dark else "#6957d9"
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {bg};
                color: {fg};
                font: 14px 'Sans Serif';
                }}
            QFrame#sidebar {{ background: {panel};
                border-right: 1px solid {border};
                }}
            QLabel {{ background: transparent;
                }}
            QLabel#brand {{ font-size: 24px;
                font-weight: 700;
                color: {accent};
                }}
            QLabel#title {{ font-size: 26px;
                font-weight: 650;
                padding: 4px 0;
                }}
            QLabel#badge {{ color: {accent};
                padding: 8px 12px;
                background: {field};
                border-radius: 12px;
                }}
            QLabel#notice {{ background: {field};
                border-left: 3px solid {accent};
                padding: 12px;
                border-radius: 6px;
                }}
            QPushButton {{ background: {field};
                border: 1px solid {border};
                border-radius: 9px;
                padding: 10px 14px;
                font-weight: 550;
                }}
            QPushButton:hover {{ border-color: {accent};
                }}
            QPushButton:pressed {{ background: {border};
                }}
            QPushButton:disabled {{ color: {muted};
                }}
            QPushButton#primary {{ background: {accent};
                color: white;
                border-color: {accent};
                }}
            QPushButton#primary:disabled {{ background: {field};
                color: {muted};
                border-color: {border};
                }}
            QPushButton#nav {{ text-align: left;
                padding: 13px;
                border: none;
                background: transparent;
                }}
            QPushButton#nav:checked {{ color: {accent};
                background: {field};
                }}
            QLineEdit, QPlainTextEdit, QTextBrowser, QListWidget, QTableWidget,
            QComboBox, QSpinBox, QDoubleSpinBox {{
                background: {panel};
                border: 1px solid {border};
                border-radius: 9px;
                padding: 8px;
                selection-background-color: {accent};
                }}
            QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QPushButton:focus {{
                border: 1px solid {accent};
                }}
            QTextBrowser#transcript {{ padding: 22px;
                }}
            QListWidget::item {{ padding: 12px 8px;
                border-radius: 6px;
                }}
            QListWidget::item:selected, QTableWidget::item:selected {{ background: {field};
                color: {accent};
                }}
            QHeaderView::section {{ background: {field};
                color: {muted};
                border: none;
                padding: 10px;
                }}
            QTabWidget::pane {{ border: none;
                }}
            QTabBar::tab {{ padding: 12px 20px;
                background: {bg};
                color: {muted};
                border-bottom: 2px solid {border};
                }}
            QTabBar::tab:selected {{ color: {accent};
                border-bottom-color: {accent};
                }}
            QScrollArea {{ border: none;
                }}
            QScrollBar:vertical {{ width: 10px;
                background: {bg};
                }}
            QScrollBar::handle:vertical {{ background: {border};
                border-radius: 5px;
                min-height: 32px;
                }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0;
                }}
            QProgressBar {{ border: 1px solid {border};
                border-radius: 7px;
                text-align: center;
                min-height: 22px;
                }}
            QProgressBar::chunk {{ background: {accent};
                border-radius: 6px;
                }}
            QStatusBar {{ color: {muted};
                }}
            QSplitter::handle {{ background: {border};
                width: 1px;
                }}
            QToolTip {{ background: {panel};
                color: {fg};
                border: 1px solid {border};
                }}
        """)

    def backend_ready(self):
        if self._closing:
            return
        self.is_connected = True
        self.pages.setEnabled(True)
        self.connection.setText(self.tr("connected"))
        self.statusBar().showMessage(self.tr("ready"))
        self.log_event("connected")
        self._health_pending = {"models", "conversations", "settings"}
        self.refresh_models()
        self.refresh_conversations()
        self.api.request("GET", "/api/v1/settings", success=self._preferences)
        self.refresh_diagnostics()
        self.refresh_downloads()
        if self._pending_import:
            path, self._pending_import = self._pending_import, None
            self.import_gguf(path)

    def _preferences(self, preferences):
        # Desktop preferences are explicit. Synchronize them without resetting backend mode.
        preferences.update(locale=self.config.locale, theme=self.config.theme)
        self.api.request(
            "PUT", "/api/v1/settings", preferences, success=lambda _: self._loaded("settings")
        )

    def _loaded(self, key):
        self._health_pending.discard(key)
        if not self._health_pending:
            self.connected.emit()

    def log_event(self, code):
        if code.replace("_", "").isalnum() and len(code) < 90:
            self.logs.appendPlainText(f"{datetime.now().strftime('%H:%M:%S')}  {code}")

    def notify(self, text):
        self.notice.setText(text)
        self.notice.show()
        self.statusBar().showMessage(text, 10000)

    def show_error(self, code):
        self.log_event(code)
        text = self.tr.catalog.get(code) or self.tr("operation_error", code=code)
        self.notify(text)

    def refresh_conversations(self, select=None):
        def received(records):
            self.conversations = records
            self._fill_conversations(
                select or (records[0]["id"] if records and not self.current_id else None)
            )
            self._loaded("conversations")

        self.api.request("GET", TEXT + "/conversations", success=received)

    def _fill_conversations(self, select=None):
        current = select or self.current_id
        self.conversation_list.blockSignals(True)
        self.conversation_list.clear()
        for record in self.conversations:
            item = QListWidgetItem(record["title"] or self.tr("untitled"))
            item.setData(Qt.UserRole, record["id"])
            self.conversation_list.addItem(item)
            if record["id"] == current:
                self.conversation_list.setCurrentItem(item)
        self.conversation_list.blockSignals(False)
        if select:
            self.open_conversation(select)

    def new_conversation(self):
        if not self.is_connected:
            return
        if self.active_job:
            self.show_error("busy")
            return
        self.api.request(
            "POST",
            TEXT + "/conversations",
            {
                "title": self.tr("untitled"),
                "model_id": self.model_combo.currentData(),
                "parameters": self.config.parameters,
            },
            success=lambda record: self.refresh_conversations(record["id"]),
        )

    def select_conversation(self, item, _previous):
        if item:
            self.open_conversation(item.data(Qt.UserRole))

    def open_conversation(self, conversation_id):
        self.current_id = conversation_id
        self.last_job = None
        record = next((r for r in self.conversations if r["id"] == conversation_id), None)
        if record and record["model_id"]:
            index = self.model_combo.findData(record["model_id"])
            if index >= 0:
                self.model_combo.blockSignals(True)
                self.model_combo.setCurrentIndex(index)
                self.model_combo.blockSignals(False)
        self.refresh_messages()

    def refresh_messages(self):
        if not self.current_id:
            self.messages = []
            self.render_messages()
            return
        conversation_id = self.current_id

        def received(messages):
            if self.current_id == conversation_id:
                self.messages = messages
                self.render_messages()

        self.api.request(
            "GET", TEXT + f"/conversations/{conversation_id}/messages", success=received
        )

    def rename_conversation(self):
        if not self.current_id or self.active_job:
            return
        title, ok = QInputDialog.getText(self, self.tr("rename"), self.tr("conversation_title"))
        if ok and title.strip():
            self.api.request(
                "PATCH",
                TEXT + f"/conversations/{self.current_id}",
                {"title": title.strip()[:256]},
                success=lambda _: self.refresh_conversations(),
            )

    def delete_conversation(self):
        if not self.current_id or self.active_job:
            return
        if (
            QMessageBox.question(self, self.tr("confirm"), self.tr("delete_conversation"))
            != QMessageBox.Yes
        ):
            return

        def deleted(_):
            self.current_id = None
            self.last_job = None
            self.messages = []
            self.render_messages()
            self.refresh_conversations()

        self.api.request("DELETE", TEXT + f"/conversations/{self.current_id}", success=deleted)

    def model_selected(self):
        if self.current_id and self.model_combo.currentData() and not self.active_job:
            self.api.request(
                "PATCH",
                TEXT + f"/conversations/{self.current_id}",
                {"model_id": self.model_combo.currentData()},
            )

    def send_message(self):
        if self.active_job or self._submitting or not self.is_connected:
            return
        if not self.current_id:
            self.show_error("no_conversation")
            return
        model = self.model_combo.currentData()
        if not model:
            self.show_error("model_required")
            return
        content = self.composer.toPlainText().strip()
        if not content:
            return
        self.send_button.setEnabled(False)
        self._submitting = True
        payload = {
            "content": content,
            "request_key": uuid.uuid4().hex,
            "model_id": model,
            "parameters": self.config.parameters,
        }

        def submitted(record):
            self._submitting = False
            self.composer.clear()
            self.messages.append({"role": "user", "content": content})
            self.active_job = record["id"]
            self.last_job = None
            self.stop_button.setEnabled(True)
            self.conversation_list.setEnabled(False)
            self.new_button.setEnabled(False)
            self.model_combo.setEnabled(False)
            self.generation_snapshot(record)
            self.api.watch(record["id"])

        def failure(code):
            self._submitting = False
            self.send_button.setEnabled(True)
            self.show_error(code)

        self.api.request(
            "POST",
            TEXT + f"/conversations/{self.current_id}/generations",
            payload,
            success=submitted,
            failure=failure,
        )

    def generation_snapshot(self, record):
        if not isinstance(record, dict) or record.get("id") != self.active_job:
            return
        if (
            self.last_job
            and self.last_job["id"] == record["id"]
            and record["sequence"] < self.last_job["sequence"]
        ):
            return
        self.last_job = record
        state = record["state"]
        speed = record.get("tokens_per_second")
        self.generation_status.setText(self.tr(state) + (f" · {speed:.1f} tok/s" if speed else ""))
        self.render_messages()
        if state in TERMINAL:
            self.active_job = None
            self.api.close_stream()
            self._generation_idle()
            self.refresh_messages()
            self.refresh_models()
            if record.get("error_code"):
                self.show_error(record["error_code"])

    def _generation_idle(self):
        self.send_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.conversation_list.setEnabled(True)
        self.new_button.setEnabled(True)
        self.model_combo.setEnabled(True)

    def stream_closed(self):
        if self.active_job:
            job = self.active_job
            self.api.request("GET", TEXT + f"/generations/{job}", success=self.generation_snapshot)
            # Disconnect cancellation is durable but may finish just after the last GET.
            QTimer.singleShot(
                350,
                lambda: (
                    self.api.request(
                        "GET", TEXT + f"/generations/{job}", success=self.generation_snapshot
                    )
                    if self.active_job == job
                    else None
                ),
            )

    def stop_generation(self):
        if self.active_job:
            self.api.request(
                "POST",
                TEXT + f"/generations/{self.active_job}/cancel",
                success=self.generation_snapshot,
            )

    def render_messages(self):
        blocks = []
        for message in self.messages:
            blocks.append(
                (self.tr("you" if message["role"] == "user" else "assistant"), message["content"])
            )
        if (
            self.last_job
            and self.last_job.get("content")
            and not any(m.get("generation_id") == self.last_job["id"] for m in self.messages)
        ):
            blocks.append((self.tr("assistant"), self.last_job["content"]))
        if not blocks:
            text = (
                f'<p style="color:#8190a8;font-size:18px">{html.escape(self.tr("chat_hint"))}</p>'
            )
        else:
            text = "".join(
                '<div style="margin-bottom:28px"><p style="color:#8b80f9;font-size:11px;'
                f'font-weight:700">{html.escape(role)}</p><p style="white-space:pre-wrap;'
                f'line-height:150%;font-size:15px">{html.escape(content)}</p></div>'
                for role, content in blocks
            )
        bar = self.transcript.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 30
        self.transcript.setHtml(text)
        if at_bottom:
            bar.setValue(bar.maximum())

    def copy_answer(self):
        content = self.last_job.get("content") if self.last_job else None
        if not content:
            content = next(
                (m["content"] for m in reversed(self.messages) if m["role"] == "assistant"), ""
            )
        if content:
            QApplication.clipboard().setText(content)
            self.notify(self.tr("copied"))
        else:
            self.show_error("no_answer")

    def refresh_models(self):
        def received(records):
            selected = self.model_combo.currentData()
            if not selected:
                conversation = next(
                    (r for r in self.conversations if r["id"] == self.current_id), None
                )
                selected = conversation["model_id"] if conversation else None
            self.models = records
            self.model_combo.blockSignals(True)
            self.model_combo.clear()
            self.model_combo.addItem(
                self.tr("choose_model") if records else self.tr("no_model"), None
            )
            for record in records:
                self.model_combo.addItem(f"{record['name']} · {record['backend']}", record["id"])
            index = self.model_combo.findData(selected)
            self.model_combo.setCurrentIndex(max(index, 0))
            self.model_combo.blockSignals(False)
            self.refresh_model_table()
            self._loaded("models")

        self.api.request("GET", TEXT + "/models", success=received)

    def refresh_model_table(self):
        selected = self.selected_model()
        self.model_table.setHorizontalHeaderLabels(
            [self.tr(k) for k in ("model_name", "size", "engine", "compatibility")]
        )
        records = [r for r in self.models if r["backend"] == self.engine_filter.currentText()]
        self.model_table.setRowCount(len(records))
        for row, record in enumerate(records):
            for column, value in enumerate(
                (
                    record["name"],
                    human_size(record["size_bytes"]),
                    record["backend"],
                    self.tr(record["compatibility"]),
                )
            ):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, record["id"])
                self.model_table.setItem(row, column, item)
            if selected and selected["id"] == record["id"]:
                self.model_table.selectRow(row)

    def selected_model(self):
        row = self.model_table.currentRow() if hasattr(self, "model_table") else -1
        item = self.model_table.item(row, 0) if row >= 0 else None
        return next((r for r in self.models if item and r["id"] == item.data(Qt.UserRole)), None)

    def model_details(self):
        record = self.selected_model()
        self.load_button.setEnabled(
            bool(record and record["backend"] == "llama.cpp" and not self._loading_model)
        )
        self.load_button.setToolTip(
            self.tr("ollama_managed") if record and record["backend"] == "ollama" else ""
        )
        if record:
            self.model_detail.setText(
                f"{record['name']} · {record['format']} · {record.get('quantization') or '—'}\n"
                f"{self.tr('license')}: {record.get('license') or self.tr('unknown')}\n"
                f"{record['location']}"
            )

    def choose_gguf(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr("choose_file"), "", "GGUF (*.gguf)")
        if path:
            self.import_gguf(path)

    def import_gguf(self, path):
        candidate = Path(path).absolute()
        roots = [data_path().absolute() / "models", *(Path(p) for p in self.config.model_roots)]
        if self.session.owned and not any(candidate.is_relative_to(root) for root in roots):
            if self.active_job:
                self.show_error("busy")
                return
            if (
                QMessageBox.question(
                    self, self.tr("confirm"), self.tr("import_root", path=candidate.parent)
                )
                != QMessageBox.Yes
            ):
                return
            self.config.model_roots.append(str(candidate.parent))
            self.config.save()
            self.roots.addItem(str(candidate.parent))
            self._pending_import = str(candidate)
            self.is_connected = False
            self.connection.setText(self.tr("connecting"))
            self.pages.setEnabled(False)
            self.session.restart(self.config)
            return

        def imported(record):
            self.notify(self.tr("imported"))
            self.engine_filter.setCurrentText(record["backend"])
            self.refresh_models()

        self.api.request(
            "POST", TEXT + "/models/import", {"path": str(candidate)}, success=imported
        )

    def sync_ollama(self):
        self.api.request(
            "POST",
            TEXT + "/models/sync-ollama",
            success=lambda _: (self.engine_filter.setCurrentText("ollama"), self.refresh_models()),
        )

    def load_model(self):
        record = self.selected_model()
        if not record:
            self.show_error("model_required")
            return
        self._loading_model = True
        self.load_button.setEnabled(False)
        self.notify(self.tr("loading"))

        def loaded(_):
            self._loading_model = False
            self.load_button.setEnabled(True)
            self.notify(self.tr("loaded"))
            self.model_combo.setCurrentIndex(self.model_combo.findData(record["id"]))
            self.refresh_models()

        def failure(code):
            self._loading_model = False
            self.load_button.setEnabled(True)
            self.show_error("llama_unavailable" if code == "engine_unavailable" else code)

        self.api.request(
            "POST",
            TEXT + f"/models/{record['id']}/load",
            self.config.parameters,
            success=loaded,
            failure=failure,
            timeout=130000,
        )

    def unload_model(self):
        record = self.selected_model()
        if record:
            self.api.request(
                "POST",
                TEXT + f"/models/{record['id']}/unload",
                success=lambda _: self.notify(self.tr("unloaded")),
            )

    def remove_model(self):
        record = self.selected_model()
        if (
            record
            and QMessageBox.question(self, self.tr("confirm"), self.tr("remove_model"))
            == QMessageBox.Yes
        ):
            self.api.request(
                "DELETE",
                TEXT + f"/models/{record['id']}",
                {"delete_file": False},
                success=lambda _: self.refresh_models(),
            )

    def search_hf(self):
        query = self.hf_query.text().strip()
        if not query:
            return

        def received(records):
            self.hf_results.clear()
            for record in records:
                item = QListWidgetItem(record["repository"])
                item.setData(Qt.UserRole, record["repository"])
                self.hf_results.addItem(item)

        self.api.request(
            "GET", TEXT + "/huggingface/search?" + urlencode({"query": query}), success=received
        )

    def list_hf_files(self):
        item = self.hf_results.currentItem()
        repository = item.data(Qt.UserRole) if item else self.hf_query.text().strip()

        def received(records):
            self.remote_files = records
            self.hf_files.clear()
            for record in records:
                self.hf_files.addItem(
                    f"{record['filename']} · {human_size(record['size_bytes'])}", record
                )

        self.api.request(
            "GET",
            TEXT + "/huggingface/files?" + urlencode({"repository": repository}),
            success=received,
        )

    def download_file(self):
        record = self.hf_files.currentData()
        if not record:
            return
        text = self.tr(
            "confirm_download",
            file=record["filename"],
            size=human_size(record["size_bytes"]),
            license=record.get("license") or self.tr("unknown"),
        )
        if QMessageBox.question(self, self.tr("confirm"), text) != QMessageBox.Yes:
            return
        payload = {
            "repository": record["repository"],
            "filename": record["filename"],
            "revision": record["revision"],
            "confirmed": True,
            "expected_size": record["size_bytes"],
        }
        self.api.request(
            "POST", TEXT + "/downloads", payload, success=lambda _: self.refresh_downloads()
        )

    def refresh_downloads(self):
        if not self.is_connected or self._closing:
            return

        def received(records):
            current = self.download_list.currentData()
            self.downloads = records
            self.download_list.blockSignals(True)
            self.download_list.clear()
            for record in records:
                self.download_list.addItem(
                    f"{record['source']['filename']} · {self.tr(record['state'])}"
                    f" · {record['percent']:.0f}%",
                    record["id"],
                )
            index = self.download_list.findData(current)
            self.download_list.setCurrentIndex(max(index, 0))
            self.download_list.blockSignals(False)
            selected = self.selected_download()
            self.download_progress.setValue(int(selected["percent"]) if selected else 0)

        self.api.request("GET", TEXT + "/downloads", success=received)

    def selected_download(self):
        return next(
            (r for r in self.downloads if r["id"] == self.download_list.currentData()), None
        )

    def cancel_download(self):
        record = self.selected_download()
        if record:
            self.api.request(
                "POST",
                TEXT + f"/downloads/{record['id']}/cancel",
                success=lambda _: self.refresh_downloads(),
            )

    def resume_download(self):
        record = self.selected_download()
        if record:
            self.api.request(
                "POST",
                TEXT + f"/downloads/{record['id']}/resume",
                success=lambda _: self.refresh_downloads(),
            )

    def import_download(self):
        record = self.selected_download()
        if record and record["state"] == "completed" and record.get("path"):
            self.import_gguf(record["path"])
        elif record and record.get("error_code"):
            self.show_error(record["error_code"])

    def add_directory(self):
        path = QFileDialog.getExistingDirectory(self, self.tr("choose_directory"))
        if path and path not in [self.roots.item(i).text() for i in range(self.roots.count())]:
            self.roots.addItem(path)

    def remove_directory(self):
        item = self.roots.takeItem(self.roots.currentRow())
        del item

    def choose_llama(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr("choose_executable"))
        if path:
            self.llama_path.setText(path)

    def save_settings(self):
        if self.active_job:
            self.show_error("busy")
            return
        from urllib.parse import urlsplit

        url = self.ollama_url.text().strip()
        parsed = urlsplit(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            self.show_error("invalid_backend_url")
            return
        path = self.llama_path.text().strip()
        if path and (not Path(path).is_file() or not os.access(path, os.X_OK)):
            self.show_error("llama_unavailable")
            return
        roots = [self.roots.item(i).text() for i in range(self.roots.count())]
        changed = (
            roots != self.config.model_roots
            or path != self.config.llama_server
            or url != self.config.ollama_url
            or self.ollama_enabled.isChecked() != self.config.ollama_enabled
        )
        if changed and not self.session.owned:
            self.show_error("external_backend_settings")
            return
        self.config.model_roots, self.config.llama_server = roots, path
        self.config.ollama_url, self.config.ollama_enabled = url, self.ollama_enabled.isChecked()
        self.config.parameters = {k: box.value() for k, box in self.parameter_inputs.items()}
        self.config.parameters.update(
            system_prompt=self.system_prompt.toPlainText(), device=self.device.text().strip()
        )
        from omnicore.text.types import GenerationParameters

        try:
            GenerationParameters.model_validate(self.config.parameters)
            self.config.save()
        except (ValueError, OSError):
            self.show_error("invalid_settings")
            return
        self.notify(self.tr("saved"))
        if changed:
            self.is_connected = False
            self.connection.setText(self.tr("connecting"))
            self.pages.setEnabled(False)
            self.session.restart(self.config)
        else:
            self.api.request("GET", "/api/v1/settings", success=self._preferences)

    def refresh_diagnostics(self):
        if not self.is_connected:
            return

        def received(records):
            self.engines = records
            lines = [
                f"{self.tr('backend')}: {self.api.base_url}",
                f"{self.tr('active_task')}: {self.active_job or self.tr('none')}",
            ]
            for record in records:
                info = record["info"]
                resources = info.get("resources") or {}
                lines.extend(
                    [
                        "",
                        info["id"]
                        + ": "
                        + self.tr("available" if info["available"] else "unavailable"),
                        str(info.get("version") or "—"),
                        f"{self.tr('gpu')}: {', '.join(record['gpu_devices']) or self.tr('none')}",
                        f"{self.tr('ram')}: {human_size(resources.get('ram_bytes'))}",
                        f"{self.tr('vram')}: {human_size(resources.get('vram_bytes'))}",
                    ]
                )

            def hardware_received(snapshot):
                hardware = snapshot["hardware"]
                lines.extend(
                    [
                        "",
                        f"{self.tr('cpu')}: {hardware['cpu_architecture']}"
                        f" · {hardware['cpu_count']}",
                        f"{self.tr('ram_total')}: {human_size(hardware['ram_total_bytes'])} / "
                        f"{human_size(hardware['ram_available_bytes'])}",
                        f"{self.tr('disk_free')}: {human_size(hardware['disk_free_bytes'])}",
                    ]
                )
                for record in snapshot["generations"]:
                    if record["state"] not in TERMINAL or record["error_code"]:
                        lines.append(
                            f"{record['id']}: {self.tr(record['state'])} · "
                            f"{record['error_code'] or '—'}"
                        )
                self.diagnostic_text.setPlainText("\n".join(lines))

            self.api.request("GET", TEXT + "/diagnostics", success=hardware_received)

        self.api.request("GET", TEXT + "/engines", success=received)

    def closeEvent(self, event):
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        self._closing = True
        self._poll.stop()
        self.pages.setEnabled(False)
        self.connection.setText(self.tr("closing"))
        self.session.stop()

    def _stopped(self):
        if self._closing:
            self.api.close()
            self._allow_close = True
            self.close()
