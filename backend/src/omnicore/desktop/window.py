"""Native widgets for the existing API. Network and inference never block Qt."""

import os
import re
import uuid
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut, QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
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
    QMenu,
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from omnicore.desktop.agents import AgentPanel
from omnicore.desktop.composer import Composer
from omnicore.desktop.config import data_path
from omnicore.desktop.history import grouped_history
from omnicore.desktop.i18n import Translator
from omnicore.desktop.model_card import safe_card_markdown
from omnicore.desktop.report import diagnostic_report, save_report
from omnicore.desktop.themes import contrast_ratio, palette, readable_accent
from omnicore.desktop.transcript import ChatTranscript, statistics_text
from omnicore.release import build_info, distribution_version
from omnicore.text.context import context_settings
from omnicore.text.downloads import is_multipart_gguf

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


class ModelCardBrowser(QTextBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)

    def loadResource(self, resource_type, url):
        return None

    def set_safe_markdown(self, text):
        self.document().setMarkdown(
            safe_card_markdown(text),
            QTextDocument.MarkdownDialectGitHub | QTextDocument.MarkdownNoHTML,
        )


class MainWindow(QMainWindow):
    connected = Signal()

    def __init__(self, api, session, config):
        super().__init__()
        self.api, self.session, self.config = api, session, config
        self.config.parameters.setdefault("device", "auto")
        self.config.parameters.setdefault(
            "gpu_layers", 99 if self.config.parameters["device"] != "cpu" else 0
        )
        self.tr = Translator(config.locale)
        self._texts = []
        self.conversations, self.models, self.messages = [], [], []
        self.current_id = None
        self.active_job = None
        self._submitting = False
        self._loading_model = False
        self.last_job = None
        self.downloads, self.remote_files = [], []
        self._hf_search_sequence = 0
        self.model_contexts = {}
        self._context_saving = False
        self._context_dirty = False
        self._context_generation = 0
        self.engines = []
        self.is_connected = False
        self._connection_key = "connecting"
        self._closing = False
        self._allow_close = False
        self._pending_import = None
        self._health_pending = set()
        self.setWindowTitle(f"OmniCore · {distribution_version()}")
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
            ("Ctrl+F", self.focus_history_search),
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
        button.setAccessibleName(self.tr(key))
        button.setToolTip(self.tr(key))
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
        self.shell = QSplitter(Qt.Horizontal)
        self.shell.setChildrenCollapsible(False)
        self.shell.setHandleWidth(4)
        layout.addWidget(self.shell)
        self.width_save_timer = QTimer(self)
        self.width_save_timer.setSingleShot(True)
        self.width_save_timer.setInterval(250)
        self.width_save_timer.timeout.connect(self.config.save)
        self.shell.splitterMoved.connect(self.sidebar_dragged)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.side_layout = QVBoxLayout(self.sidebar)
        self.side_layout.setContentsMargins(8, 12, 8, 12)
        self.brand = QLabel("◈  OmniCore")
        self.brand.setObjectName("brand")
        self.sidebar_header = QHBoxLayout()
        self.sidebar_header.addWidget(self.brand, 1)
        self.side_layout.addLayout(self.sidebar_header)
        self.sidebar_toggle = QPushButton()
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)
        self.sidebar_toggle.setFixedSize(28, 32)
        self.sidebar_toggle.setStyleSheet("padding: 0;")
        self.sidebar_header.addWidget(self.sidebar_toggle)
        self.nav = []
        for index, key in enumerate(("chat", "models", "settings", "diagnostics")):
            button = self.button(key, lambda checked=False, i=index: self.navigate(i))
            button.setCheckable(True)
            button.setObjectName("nav")
            self.nav.append(button)
        self.side_layout.addWidget(self.nav[0])
        self.side_layout.addWidget(self.nav[1])
        self.shell.addWidget(self.sidebar)
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
        self.reconnect_button = self.button("reconnect", self.reconnect)
        header.addWidget(self.reconnect_button)
        body.addLayout(header)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.PlainText)
        self.notice.setObjectName("notice")
        self.notice.hide()
        body.addWidget(self.notice)
        self.onboarding = QFrame()
        self.onboarding.setObjectName("notice")
        intro = QVBoxLayout(self.onboarding)
        intro.addWidget(self.label("welcome_title", title=True))
        intro_text = self.label("welcome_steps")
        intro_text.setWordWrap(True)
        intro.addWidget(intro_text)
        self.welcome_import = self.button("import_gguf", self.first_import, primary=True)
        self.welcome_import.setEnabled(False)
        intro.addLayout(
            self.row(
                self.welcome_import,
                self.button("settings", lambda: self.navigate(2)),
                self.button("dismiss_welcome", self.dismiss_welcome),
            )
        )
        self.onboarding.setVisible(not self.config.onboarding_complete)
        body.addWidget(self.onboarding)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        self._build_chat()
        self.compact_spacer = QWidget()
        self.side_layout.addWidget(self.compact_spacer, 1)
        self.side_layout.addWidget(self.nav[3])
        self.side_layout.addWidget(self.nav[2])
        self._apply_sidebar()
        self._build_models()
        self._build_settings()
        self._build_diagnostics()
        self.shell.addWidget(main)
        self.shell.setStretchFactor(1, 1)
        self._apply_sidebar()
        self.nav[0].setChecked(True)
        self.statusBar().showMessage(self.tr("connecting"))
        self.pages.setEnabled(False)

    def _build_chat(self):
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 12, 0, 0)
        self.history_panel = QWidget()
        left = QVBoxLayout(self.history_panel)
        left.setContentsMargins(0, 0, 0, 0)
        self.sidebar_width = QSpinBox()
        self.sidebar_width.setRange(200, 360)
        self.sidebar_width.setValue(self.config.sidebar_width)
        self.sidebar_width.setSuffix(" px")
        self.sidebar_width.valueChanged.connect(self.resize_sidebar)
        self.new_button = self.button("new_chat", self.new_conversation, primary=True)
        left.addWidget(self.new_button)
        self.history_search = QLineEdit()
        self.history_search.setMaxLength(256)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.refresh_conversations)
        self.history_search.textChanged.connect(lambda _: self.search_timer.start())
        self.history_refresh = QPushButton("↻")
        self.history_refresh.setFixedWidth(32)
        self.history_refresh.setStyleSheet("padding: 6px 0; font-size: 18px;")
        self.history_refresh.clicked.connect(self.refresh_shared_history)
        left.addLayout(self.row(self.history_search, self.history_refresh))
        self.conversation_list = QListWidget()
        self.conversation_list.setObjectName("conversations")
        self.conversation_list.setLayoutMode(QListWidget.Batched)
        self.conversation_list.setBatchSize(128)
        self.conversation_list.setWordWrap(False)
        self.conversation_list.setTextElideMode(Qt.ElideRight)
        self.conversation_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.conversation_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.conversation_list.customContextMenuRequested.connect(self.conversation_menu)
        self.conversation_list.currentItemChanged.connect(self.select_conversation)
        self.conversation_list.currentItemChanged.connect(self.update_history_selection)
        left.addWidget(self.conversation_list, 1)
        self.side_layout.insertWidget(1, self.new_button)
        left.removeWidget(self.new_button)
        self.side_layout.addWidget(self.history_panel, 1)
        pane = QWidget()
        chat = QVBoxLayout(pane)
        chat.setContentsMargins(0, 0, 0, 0)
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(180)
        self.model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.model_combo.currentIndexChanged.connect(self.model_selected)
        chat.addLayout(self.row(self.model_combo, self.button("refresh", self.refresh_models)))
        self.context_mode = QComboBox()
        self.context_mode.addItem(self.tr("context_auto"), "auto")
        self.context_mode.addItem(self.tr("context_manual"), "manual")
        self.context_mode.currentIndexChanged.connect(self._context_mode_changed)
        self.context_mode.currentIndexChanged.connect(self._context_edited)
        self.context_tokens = QSpinBox()
        self.context_tokens.setRange(128, 1_000_000)
        self.context_tokens.setSingleStep(256)
        self.context_tokens.setValue(2048)
        self.context_tokens.valueChanged.connect(self._context_edited)
        self.context_save = self.button("context_save", self.save_model_context)
        chat.addLayout(self.row(self.context_mode, self.context_tokens, self.context_save))
        self.context_status = QLabel()
        self.context_status.setWordWrap(True)
        chat.addWidget(self.context_status)
        self.agent_panel = AgentPanel(self)
        chat.addWidget(self.agent_panel)
        self.transcript = ChatTranscript()
        self.transcript.regenerate_requested.connect(self.regenerate_answer)
        chat.addWidget(self.transcript, 1)
        self.generation_status = self.label("ready")
        chat.addWidget(self.generation_status)
        self.composer = Composer()
        self.composer.submitted.connect(self.send_message)
        self.composer.setObjectName("composer")
        chat.addWidget(self.composer)
        self.context_usage = QLabel()
        self.context_usage.setWordWrap(True)
        chat.addWidget(self.context_usage)
        self.context_meter = QProgressBar()
        self.context_meter.setRange(0, 100)
        self.context_meter.setMaximumHeight(8)
        self.context_meter.setObjectName("contextMeter")
        self.context_meter.setTextVisible(False)
        chat.addWidget(self.context_meter)
        self.context_toggle = self.button("context_details", lambda: None)
        self.context_toggle.setCheckable(True)
        self.context_details = QLabel()
        self.context_details.setTextFormat(Qt.PlainText)
        self.context_details.setWordWrap(True)
        self.context_details.hide()
        self.context_toggle.toggled.connect(self.context_details.setVisible)
        chat.addWidget(self.context_toggle)
        chat.addWidget(self.context_details)
        self.regenerate_button = self.button("regenerate", self.regenerate_answer)
        self.regenerate_button.setToolTip(self.tr("regenerate_branch"))
        self.send_button = self.button("send", self.send_message, primary=True)
        self.stop_button = self.button("stop", self.stop_generation)
        self.stop_button.setEnabled(False)
        chat.addLayout(
            self.row(
                self.button("copy", self.copy_answer),
                self.regenerate_button,
                self.stop_button,
                self.send_button,
            )
        )
        outer.addWidget(pane, 1)
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
        self.model_search = QLineEdit()
        self.model_search.textChanged.connect(self.refresh_model_table)
        self.model_sort = QComboBox()
        for key in ("sort_name", "sort_size", "sort_recent"):
            self.model_sort.addItem(self.tr(key), key)
        self.model_sort.currentIndexChanged.connect(self.refresh_model_table)
        self.favorites_only = QCheckBox(self.tr("favorites_only"))
        self._texts.append((self.favorites_only, "favorites_only"))
        self.favorites_only.toggled.connect(self.refresh_model_table)
        local.addLayout(self.row(self.model_search, self.model_sort, self.favorites_only))
        self.models_empty = self.label("models_empty")
        local.addWidget(self.models_empty)
        self.model_table = QTableWidget(0, 4)
        self.model_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.model_table.setSelectionMode(QTableWidget.SingleSelection)
        self.model_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.model_table.verticalHeader().hide()
        self.model_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3):
            self.model_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents
            )
        self.model_table.itemSelectionChanged.connect(self.model_details)
        local.addWidget(self.model_table, 1)
        self.model_detail = self.label("model_details")
        self.model_detail.setTextFormat(Qt.PlainText)
        self.model_detail.setWordWrap(True)
        local.addWidget(self.model_detail)
        self.favorite_button = self.button("favorite_toggle", self.toggle_favorite_model)
        self.load_button = self.button("load", self.load_model, primary=True)
        self.model_actions = QToolButton()
        self.model_actions.setText("⋯")
        self.model_actions.setFixedSize(32, 32)
        self.model_actions.setPopupMode(QToolButton.InstantPopup)
        self.model_actions_menu = QMenu(self.model_actions)
        self.model_unload_action = self.model_actions_menu.addAction(
            self.tr("unload"), self.unload_model
        )
        self.model_remove_action = self.model_actions_menu.addAction(
            self.tr("remove_entry"), self.remove_model
        )
        self.model_actions.setMenu(self.model_actions_menu)
        local.addLayout(
            self.row(
                self.load_button,
                self.favorite_button,
                self.button("model_configure", self.configure_selected_model),
                self.model_actions,
            )
        )
        self.model_tabs.addTab(installed, "")
        remote = QWidget()
        hf = QVBoxLayout(remote)
        hf.addWidget(self.label("download_hint"))
        splitter = QSplitter(Qt.Horizontal)
        left, right = QWidget(), QWidget()
        left_layout, right_layout = QVBoxLayout(left), QVBoxLayout(right)
        self.hf_query = QLineEdit()
        self.hf_query.returnPressed.connect(self.search_hf)
        left_layout.addLayout(self.row(self.hf_query, self.button("search", self.search_hf)))
        self.hf_sort = QComboBox()
        for key, value in (
            ("sort_downloads", "downloads"),
            ("sort_likes", "likes"),
            ("sort_updated", "lastModified"),
        ):
            self.hf_sort.addItem(self.tr(key), value)
        left_layout.addLayout(
            self.row(self.button("popular_models", self.popular_hf), self.hf_sort)
        )
        self.hf_results = QListWidget()
        self.hf_results.currentItemChanged.connect(self._hf_selection_changed)
        self.hf_sort.currentIndexChanged.connect(self.search_hf)
        left_layout.addWidget(self.hf_results, 1)
        self.hf_detail = QLabel()
        self.hf_detail.setWordWrap(True)
        self.hf_detail.setTextFormat(Qt.PlainText)
        right_layout.addWidget(self.hf_detail)
        self.hf_readme = ModelCardBrowser()
        self.hf_readme.setMinimumHeight(100)
        right_layout.addWidget(self.hf_readme, 1)
        right_layout.addWidget(self.label("files"))
        self.hf_quant_filter = QLineEdit()
        self.hf_quant_filter.setPlaceholderText(self.tr("filter_quantization"))
        self.hf_quant_filter.textChanged.connect(self._filter_hf_files)
        self.hf_size_filter = QDoubleSpinBox()
        self.hf_size_filter.setRange(0, 10000)
        self.hf_size_filter.setSpecialValueText(self.tr("all_sizes"))
        self.hf_size_filter.setSuffix(" GiB")
        self.hf_size_filter.valueChanged.connect(self._filter_hf_files)
        right_layout.addLayout(self.row(self.hf_quant_filter, self.hf_size_filter))
        self.hf_files = QComboBox()
        right_layout.addWidget(self.hf_files)
        self.hf_file_info = QLabel()
        self.hf_file_info.setWordWrap(True)
        self.hf_files.currentIndexChanged.connect(self._hf_file_info)
        right_layout.addWidget(self.hf_file_info)
        self.download_button = self.button("download_file", self.download_file, primary=True)
        right_layout.addWidget(self.download_button)
        transfers = QWidget()
        transfer_layout = QVBoxLayout(transfers)
        self.transfers_empty = self.label("transfers_empty")
        transfer_layout.addWidget(self.transfers_empty)
        self.download_list = QComboBox()
        transfer_layout.addWidget(self.download_list)
        self.download_progress = QProgressBar()
        self.download_progress.setValue(0)
        transfer_layout.addWidget(self.download_progress)
        self.download_status = QLabel()
        transfer_layout.addWidget(self.download_status)
        self.download_list.currentIndexChanged.connect(self._show_download_progress)
        self.cancel_download_button = self.button("cancel_download", self.cancel_download)
        self.resume_download_button = self.button("resume_download", self.resume_download)
        self.import_download_button = self.button("import_download", self.import_download)
        transfer_layout.addLayout(
            self.row(
                self.cancel_download_button,
                self.resume_download_button,
                self.import_download_button,
            )
        )
        for button in (
            self.cancel_download_button,
            self.resume_download_button,
            self.import_download_button,
        ):
            button.hide()
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right)
        splitter.addWidget(left)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([390, 700])
        hf.addWidget(splitter, 1)
        self.model_tabs.addTab(remote, "")
        transfer_layout.addStretch()
        self.model_tabs.addTab(transfers, "")
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
        for key in ("system", "light", "midnight", "graphite", "oled", "ocean", "forest"):
            self.theme.addItem(self.tr(key), key)
        self.theme.setCurrentIndex(
            self.theme.findData("midnight" if self.config.theme == "dark" else self.config.theme)
        )
        self.theme.currentIndexChanged.connect(self.preview_theme)
        self.theme.setIconSize(QSize(84, 26))
        for index in range(self.theme.count()):
            token = palette(self.theme.itemData(index), False)
            preview = QPixmap(84, 26)
            preview.fill(QColor(token[0]))
            painter = QPainter(preview)
            painter.fillRect(0, 0, 22, 26, QColor(token[1]))
            painter.fillRect(30, 6, 48, 5, QColor(token[3]))
            painter.fillRect(30, 15, 32, 5, QColor(token[2]))
            painter.end()
            self.theme.setItemIcon(index, QIcon(preview))
        form.addRow(self.label("theme"), self.theme)
        self.ui_scale = QSpinBox()
        self.ui_scale.setRange(80, 150)
        self.ui_scale.setSingleStep(10)
        self.ui_scale.setSuffix(" %")
        self.ui_scale.setValue(self.config.ui_scale)
        self.ui_scale.valueChanged.connect(self.change_ui_scale)
        form.addRow(self.label("ui_scale"), self.ui_scale)
        form.addRow(self.label("sidebar_width"), self.sidebar_width)
        self.accent_button = self.button("accent", self.choose_accent)
        form.addRow(self.accent_button, self.button("accent_default", self.reset_accent))
        self.device = QComboBox()
        for key in ("auto", "cpu", "cuda"):
            self.device.addItem(self.tr("mode_" + key), key)
        selected = self.config.parameters.get("device", "auto")
        if selected not in {"auto", "cpu", "cuda"}:
            self.device.addItem(selected, selected)
        self.device.setCurrentIndex(self.device.findData(selected))
        form.addRow(self.label("execution_mode"), self.device)
        self.engine_summary = self.label("detecting_engines")
        form.addRow(self.engine_summary)
        form.addRow(self.button("detect_engines", self.refresh_diagnostics))
        basic = form
        self.advanced_settings = QWidget()
        self.advanced_toggle = self.button("advanced_settings", lambda: None)
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self.advanced_settings.setVisible)
        basic.addRow(self.advanced_toggle)
        basic.addRow(self.advanced_settings)
        self.advanced_settings.hide()
        form = QFormLayout(self.advanced_settings)
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
        self.llama_cuda_path = QLineEdit(self.config.llama_cuda_server)
        form.addRow(self.label("llama_cuda_server"), self.llama_cuda_path)
        form.addRow(self.button("choose_cuda", self.choose_llama_cuda))
        form.addRow(self.label("cuda_hint"))
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
            "seed": 0,
            "gpu_layers": 99,
        }
        ranges = {
            "temperature": (0, 2),
            "top_p": (0.01, 1),
            "top_k": (0, 1000),
            "repeat_penalty": (0.01, 3),
            "max_tokens": (1, 32768),
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
        self.device.currentIndexChanged.connect(self.execution_mode_changed)
        self.thinking = QCheckBox(self.tr("thinking"))
        self.thinking.setChecked(self.config.parameters.get("thinking", False))
        self._texts.append((self.thinking, "thinking"))
        form.addRow(self.thinking)
        self.system_prompt = QPlainTextEdit(self.config.parameters.get("system_prompt", ""))
        self.system_prompt.setMaximumHeight(100)
        form.addRow(self.label("system_prompt"), self.system_prompt)
        basic.addRow(self.label("settings_hint"))
        basic.addRow(self.button("save", self.save_settings, primary=True))
        self.about = QLabel()
        self.about.setWordWrap(True)
        self.about.setTextInteractionFlags(Qt.TextSelectableByMouse)
        basic.addRow(self.about)
        scroll.setWidget(page)
        self.pages.addWidget(scroll)

    def _build_diagnostics(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self.label("diagnostics_hint"))
        layout.addWidget(self.button("refresh", self.refresh_diagnostics))
        layout.addWidget(self.button("export_report", self.export_report))
        self.diagnostic_text = QPlainTextEdit()
        self.diagnostic_text.setReadOnly(True)
        layout.addWidget(self.diagnostic_text, 2)
        layout.addWidget(self.label("events"))
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.document().setMaximumBlockCount(250)
        layout.addWidget(self.logs, 1)
        self.pages.addWidget(page)

    def focus_history_search(self):
        if self.config.sidebar_compact:
            self.toggle_sidebar()
        self.history_search.setFocus()

    def sidebar_dragged(self, position, index):
        if self.config.sidebar_compact:
            return
        self.config.sidebar_width = max(200, min(360, self.sidebar.width()))
        self.sidebar_width.blockSignals(True)
        self.sidebar_width.setValue(self.config.sidebar_width)
        self.sidebar_width.blockSignals(False)
        self.width_save_timer.start()

    def resize_sidebar(self, width):
        self.config.sidebar_width = width
        self._apply_sidebar()
        self.config.save()

    def toggle_sidebar(self):
        self.config.sidebar_compact = not self.config.sidebar_compact
        self._apply_sidebar()
        self.config.save()

    def _apply_sidebar(self):
        compact = self.config.sidebar_compact
        self.sidebar.setMinimumWidth(52 if compact else 200)
        self.sidebar.setMaximumWidth(52 if compact else 360)
        if self.shell.count() > 1:
            width = 52 if compact else self.config.sidebar_width
            self.shell.setSizes([width, max(1, self.width() - width - 4)])
            self.shell.handle(1).setEnabled(not compact)
        self.brand.setVisible(not compact)
        self.sidebar_toggle.setText("◈" if compact else "‹")
        self.sidebar_toggle.setToolTip(self.tr("sidebar_expand" if compact else "sidebar_collapse"))
        self.sidebar_width.setToolTip(self.tr("sidebar_width"))
        self.history_refresh.setToolTip(self.tr("refresh"))
        self.history_refresh.setAccessibleName(self.tr("refresh"))
        self.history_panel.setVisible(not compact)
        self.compact_spacer.setVisible(compact)
        for button, key, symbol in zip(
            (self.new_button, *self.nav),
            ("new_chat", "conversations_nav", "models", "settings", "diagnostics"),
            ("＋", "◉", "▣", "⚙", "◌"),
            strict=True,
        ):
            button.setText(
                symbol
                if compact
                else (self.tr(key) if key == "new_chat" else f"{symbol}  {self.tr(key)}")
            )
            button.setToolTip(self.tr(key))
            button.setAccessibleName(self.tr(key))
            button.setStyleSheet("padding: 8px 0;" if compact else "")

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
        self.agent_panel.retranslate()
        for widget, key in self._texts:
            widget.setText(self.tr(key))
        self.page_title.setText(
            self.tr(("chat", "models", "settings", "diagnostics")[self.pages.currentIndex()])
        )
        self._apply_sidebar()
        self.composer.setPlaceholderText(self.tr("composer"))
        self.history_search.setPlaceholderText(self.tr("search_history"))
        self.context_mode.setItemText(0, self.tr("context_auto"))
        self.context_mode.setItemText(1, self.tr("context_manual"))
        self._render_model_context()
        self.model_actions.setToolTip(self.tr("model_actions"))
        self.model_actions.setAccessibleName(self.tr("model_actions"))
        self.model_unload_action.setText(self.tr("unload"))
        self.model_remove_action.setText(self.tr("remove_entry"))
        self.model_search.setPlaceholderText(self.tr("model_search"))
        for index, key in enumerate(("sort_name", "sort_size", "sort_recent")):
            self.model_sort.setItemText(index, self.tr(key))
        self.hf_query.setPlaceholderText(self.tr("hf_query"))
        self.hf_quant_filter.setPlaceholderText(self.tr("filter_quantization"))
        self.hf_size_filter.setSpecialValueText(self.tr("all_sizes"))
        for index, key in enumerate(("sort_downloads", "sort_likes", "sort_updated")):
            self.hf_sort.setItemText(index, self.tr(key))
        self._hf_file_info()
        self._show_download_progress()
        self.model_tabs.setTabText(0, self.tr("installed"))
        self.model_tabs.setTabText(1, self.tr("download"))
        self.model_tabs.setTabText(2, self.tr("transfers"))
        for index, key in enumerate(
            ("system", "light", "midnight", "graphite", "oled", "ocean", "forest")
        ):
            self.theme.setItemText(index, self.tr(key))
        for index, key in enumerate(("auto", "cpu", "cuda")):
            self.device.setItemText(index, self.tr("mode_" + key))
        self.connection.setText(self.tr(self._connection_key))
        info = build_info()
        self.about.setText(
            self.tr("about", path=data_path(), version=distribution_version())
            + "\n"
            + self.tr(
                "build_provenance",
                commit=info.get("source_commit") or self.tr("unknown"),
                date=info.get("built_at") or self.tr("source_checkout"),
                channel=info["channel"],
            )
        )
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
        self.config.save()

    def change_ui_scale(self, value):
        self.config.ui_scale = value
        self.apply_theme()
        self.composer.fit()
        self.refresh_model_table()
        self._fill_conversations()
        self.config.save()

    def choose_accent(self):
        color = QColorDialog.getColor(
            QColor(self.config.accent or "#8b80f9"), self, self.tr("accent")
        )
        if color.isValid():
            self.config.accent = color.name()
            self.apply_theme()
            self.config.save()

    def reset_accent(self):
        self.config.accent = ""
        self.apply_theme()
        self.config.save()

    def system_theme_changed(self, _scheme):
        self.apply_theme()

    def apply_theme(self):
        dark = self.config.theme not in {"system", "light"} or (
            self.config.theme == "system"
            and QApplication.instance().styleHints().colorScheme() == Qt.ColorScheme.Dark
        )
        bg, panel, field, fg, muted, border = palette(self.config.theme, dark)
        accent = {
            "ocean": "#59a8e8",
            "forest": "#65b780",
            "graphite": "#a2a2b5",
            "oled": "#a99bff",
        }.get(self.config.theme, "#8b80f9" if dark else "#6957d9")
        accent = self.config.accent or accent
        button_accent = accent
        accent_text = max(("#000000", "#ffffff"), key=lambda color: contrast_ratio(color, accent))
        accent = readable_accent(accent, fg, (bg, panel, field))
        stylesheet = f"""
            QMainWindow,
    QMenu, QWidget {{ background: {bg};
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
            QWidget#historyGroupRow {{ background: {panel}; }}
            QWidget#historyGroupRow[selected="true"] {{ background: {field}; }}
            QPushButton#historyHeading {{ background: transparent; border: 1px solid transparent;
                padding: 2px 0; text-align: left; }}
            QPushButton#historyHeading:focus {{ border: 2px solid {accent}; }}
            QToolButton {{ background: {field}; border: 1px solid {border}; border-radius: 6px; }}
            QToolButton:hover {{ border-color: {accent}; }}
            QToolButton:focus {{ border: 2px solid {accent}; }}
            QToolButton:disabled {{ color: {muted}; }}
            QPushButton:hover {{ border-color: {accent};
                }}
            QPushButton:pressed {{ background: {border};
                }}
            QPushButton:disabled {{ color: {muted};
                }}
            QPushButton#primary {{ background: {button_accent};
                color: {accent_text};
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
            QComboBox,
    QColorDialog, QSpinBox, QDoubleSpinBox {{
                background: {panel};
                border: 1px solid {border};
                border-radius: 9px;
                padding: 8px;
                selection-background-color: {accent};
                }}
            QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QPushButton:focus,
            QSpinBox:focus, QDoubleSpinBox:focus, QCheckBox:focus,
            QListWidget:focus, QTableWidget:focus, QTextBrowser:focus {{
                border: 2px solid {accent};
                }}
            QFrame#assistantBubble {{ background: transparent; border: none; }}
            QFrame#userBubble {{ background: {field}; border: 1px solid {border};
                border-radius: 14px; }}
            QTextBrowser#messageText {{ background: transparent; border: none; padding: 0; }}
            QLabel#messageAuthor {{ color: {accent}; font-weight: 700; }}
            QLabel#messageStats {{ color: {muted}; font-size: 11px; }}
            QPlainTextEdit#codeBlock {{ font-family: monospace; background: {bg}; }}
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
            QProgressBar#contextMeter {{ min-height: 6px; max-height: 8px; border-radius: 3px; }}
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
        """
        # Only logical font sizes: Qt applies the screen DPR once. Never multiply by
        # devicePixelRatio or modify QT_SCALE_FACTOR / the platform's DPI policy.
        stylesheet = re.sub(
            r"(?P<prefix>font(?:-size)?: )(?P<size>\d+)px",
            lambda m: f"{m['prefix']}{round(int(m['size']) * self.config.ui_scale / 100)}px",
            stylesheet,
        )
        self.setStyleSheet(stylesheet)
        self.brand.setStyleSheet("font-size: 22px;")
        self.ui_scale.setToolTip(self.tr("ui_scale_hint"))
        for widget, key in (
            (self.ui_scale, "ui_scale"),
            (self.model_search, "model_search"),
            (self.history_search, "search_history"),
            (self.composer, "composer"),
            (self.model_combo, "model_name"),
            (self.theme, "theme"),
            (self.engine_filter, "engine"),
        ):
            widget.setAccessibleName(self.tr(key))

    def backend_ready(self):
        if self._closing:
            return
        self.is_connected = True
        self._connection_key = "connected"
        self.welcome_import.setEnabled(True)
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
        if self.active_job:
            job = self.active_job

            def resume(record):
                self.generation_snapshot(record)
                if self.active_job == job:
                    self.api.watch(job)

            self.api.request("GET", TEXT + f"/generations/{job}", success=resume)
        if self._pending_import:
            path, self._pending_import = self._pending_import, None
            self.import_gguf(path)

    def _preferences(self, preferences):
        # Desktop preferences are explicit. Synchronize them without resetting backend mode.
        preferences.update(
            locale=self.config.locale,
            theme=(self.config.theme if self.config.theme in {"system", "light"} else "dark"),
        )
        self.api.request(
            "PUT", "/api/v1/settings", preferences, success=lambda _: self._loaded("settings")
        )

    def _loaded(self, key):
        self._health_pending.discard(key)
        if not self._health_pending:
            self.connected.emit()

    def log_event(self, code):
        if code in self.tr.catalog or code in {"backend_starting", "connected"}:
            self.logs.appendPlainText(f"{datetime.now().strftime('%H:%M:%S')}  {code}")

    def notify(self, text):
        self.notice.setText(text)
        self.notice.show()
        self.statusBar().showMessage(text, 10000)

    def show_error(self, code):
        safe_code = code if code in self.tr.catalog else "unknown_error"
        self.log_event(safe_code)
        if code in {
            "connection_error",
            "backend_exited",
            "backend_process_error",
            "unauthorized",
            "database_incompatible",
            "database_start_error",
        }:
            self.is_connected = False
            self._connection_key = "unauthorized" if code == "unauthorized" else "disconnected"
            self.connection.setText(self.tr(self._connection_key))
        text = self.tr.catalog.get(safe_code) or self.tr("operation_error", code=safe_code)
        self.notify(text)

    def refresh_conversations(self, select=None):
        search = self.history_search.text().strip()

        def received(records):
            if search != self.history_search.text().strip():
                return
            self.conversations = records
            self._fill_conversations(
                select or (records[0]["id"] if records and not self.current_id else None)
            )
            self._loaded("conversations")

        query = urlencode({"query": search})
        self.api.request("GET", TEXT + "/conversations?" + query, success=received)

    def _fill_conversations(self, select=None):
        current = select or self.current_id
        self.conversation_list.blockSignals(True)
        self.conversation_list.setUpdatesEnabled(False)
        self.conversation_list.clear()
        for group, records in grouped_history(self.conversations).items():
            for index, record in enumerate(records):
                title = record["title"] or self.tr("untitled")
                item = QListWidgetItem(title)
                item.setData(Qt.UserRole, record["id"])
                item.setToolTip(escape(title))
                self.conversation_list.addItem(item)
                if index == 0:
                    row = QWidget()
                    row.setObjectName("historyGroupRow")
                    row.setProperty("selected", record["id"] == current)
                    column = QVBoxLayout(row)
                    column.setContentsMargins(4, 8, 4, 4)
                    collapsed = group in self.config.collapsed_history
                    heading = QPushButton(
                        ("▸ " if collapsed else "▾ ") + self.tr("history_" + group)
                    )
                    heading.setObjectName("historyHeading")
                    heading.setAccessibleName(self.tr("history_" + group))
                    heading.clicked.connect(
                        lambda checked=False, key=group: self.toggle_history_group(key)
                    )
                    column.addWidget(heading)
                    label = QLabel(
                        self.fontMetrics().elidedText(
                            title, Qt.ElideRight, max(80, self.config.sidebar_width - 56)
                        )
                    )
                    label.setTextFormat(Qt.PlainText)
                    label.setWordWrap(True)
                    column.addWidget(label)
                    label.setVisible(not collapsed)
                    item.setSizeHint(
                        QSize(
                            0,
                            max(48, heading.sizeHint().height() + 24)
                            if collapsed
                            else max(80, row.sizeHint().height() + 24),
                        )
                    )
                    self.conversation_list.setItemWidget(item, row)
                if index > 0 and group in self.config.collapsed_history:
                    item.setHidden(True)
                if record["id"] == current:
                    self.conversation_list.setCurrentItem(item)
        self.conversation_list.setUpdatesEnabled(True)
        self.conversation_list.blockSignals(False)
        if (
            current
            and not self.history_search.text().strip()
            and not any(record["id"] == current for record in self.conversations)
        ):
            self.current_id = None
            self.messages = []
            self.last_job = None
            self.render_messages()
        elif select:
            self.open_conversation(select)

    def update_history_selection(self, item, previous):
        for candidate in (previous, item):
            widget = self.conversation_list.itemWidget(candidate) if candidate else None
            if widget:
                widget.setProperty("selected", candidate is item)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update()

    def toggle_history_group(self, group):
        if group in self.config.collapsed_history:
            self.config.collapsed_history.remove(group)
        else:
            self.config.collapsed_history.append(group)
        self.config.save()
        self._fill_conversations()

    def conversation_menu(self, position):
        item = self.conversation_list.itemAt(position)
        if not item or self.active_job or self._submitting:
            return
        self.conversation_list.setCurrentItem(item)
        record = next((r for r in self.conversations if r["id"] == item.data(Qt.UserRole)), None)
        if not record:
            return
        menu = QMenu(self)
        menu.addAction(self.tr("rename"), self.rename_conversation)
        menu.addAction(
            self.tr("unpin" if record.get("pinned") else "pin"),
            lambda: self.pin_conversation(record),
        )
        menu.addAction(self.tr("delete"), self.delete_conversation)
        menu.exec(self.conversation_list.viewport().mapToGlobal(position))

    def pin_conversation(self, record):
        if self.active_job or self._submitting:
            return
        self.api.request(
            "PATCH",
            TEXT + f"/conversations/{record['id']}",
            {"pinned": not record.get("pinned", False)},
            success=lambda _: self.refresh_conversations(),
        )

    def refresh_shared_history(self):
        self.refresh_conversations()
        if self.current_id:
            self.refresh_messages()

    def new_conversation(self):
        if self.agent_panel.active:
            self.show_error("conversation_busy")
            return
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
                "parameters": self.request_parameters(),
            },
            success=lambda record: self.refresh_conversations(record["id"]),
        )

    def select_conversation(self, item, _previous):
        if item:
            self.open_conversation(item.data(Qt.UserRole))

    def open_conversation(self, conversation_id):
        if self.agent_panel.active and conversation_id != self.current_id:
            self.show_error("conversation_busy")
            return
        self.current_id = conversation_id
        self.agent_panel.load(conversation_id)
        self.last_job = None
        record = next((r for r in self.conversations if r["id"] == conversation_id), None)
        if record and record["model_id"]:
            index = self.model_combo.findData(record["model_id"])
            if index >= 0:
                self.model_combo.blockSignals(True)
                self.model_combo.setCurrentIndex(index)
                self.model_combo.blockSignals(False)
                self._context_dirty = False
                self._render_model_context()
                self._refresh_model_context()
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
                live = next(
                    (
                        m
                        for m in reversed(messages)
                        if m.get("generation_id") and m.get("status") in {"queued", "running"}
                    ),
                    None,
                )
                if live and not self.active_job:
                    job = live["generation_id"]
                    self.active_job = job
                    self.stop_button.setEnabled(True)
                    self.send_button.setEnabled(False)
                    self.conversation_list.setEnabled(False)
                    self.new_button.setEnabled(False)
                    self.model_combo.setEnabled(False)

                    def observe(record):
                        self.generation_snapshot(record)
                        if self.active_job == job:
                            self.api.watch(job)

                    self.api.request("GET", TEXT + f"/generations/{job}", success=observe)

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
            self.agent_panel.load(None)
            self.current_id = None
            self.last_job = None
            self.messages = []
            self.render_messages()
            self.refresh_conversations()

        self.api.request("DELETE", TEXT + f"/conversations/{self.current_id}", success=deleted)

    def model_selected(self):
        self.render_messages()
        self._context_dirty = False
        self._render_model_context()
        self._refresh_model_context()
        if self.current_id and self.model_combo.currentData() and not self.active_job:
            self.api.request(
                "PATCH",
                TEXT + f"/conversations/{self.current_id}",
                {"model_id": self.model_combo.currentData()},
            )

    def _selected_chat_model(self):
        return next((m for m in self.models if m["id"] == self.model_combo.currentData()), None)

    def _context_edited(self, *_):
        self._context_dirty = True

    def _context_mode_changed(self, *_):
        self.context_tokens.setEnabled(
            bool(self._selected_chat_model())
            and self.context_mode.currentData() == "manual"
            and not self._context_saving
        )

    def _render_model_context(self):
        if not hasattr(self, "context_mode"):
            return
        model = self._selected_chat_model()
        self.context_mode.setEnabled(bool(model) and not self._context_saving)
        self.context_save.setEnabled(
            bool(model) and not self._context_saving and not self.active_job
        )
        if not model:
            self.context_tokens.setEnabled(False)
            self.context_status.setText(self.tr("context_choose_model"))
            return
        if self._context_dirty:
            self._context_mode_changed()
            return
        saved = self.model_contexts.get(model["id"]) or context_settings(model)
        self.context_mode.blockSignals(True)
        self.context_mode.setCurrentIndex(self.context_mode.findData(saved["mode"]))
        self.context_mode.blockSignals(False)
        self.context_tokens.blockSignals(True)
        self.context_tokens.setMaximum(saved["maximum"])
        self.context_tokens.setValue(saved["manual_tokens"])
        self.context_tokens.blockSignals(False)
        self._context_mode_changed()
        applied = saved.get("applied_tokens")
        text = self.tr("context_configured", tokens=saved["effective_tokens"])
        if applied is not None:
            text += " · " + self.tr("context_applied", tokens=applied)
            if applied != saved["effective_tokens"]:
                text += " · " + self.tr("context_reload")
        else:
            text += " · " + self.tr("context_on_start")
        self.context_status.setText(text)

    def _refresh_model_context(self):
        model = self._selected_chat_model()
        if not model:
            return
        model_id = model["id"]
        self._context_generation += 1
        generation = self._context_generation

        def received(settings):
            if generation != self._context_generation:
                return
            self.model_contexts[model_id] = settings
            if self.model_combo.currentData() == model_id and not self._context_dirty:
                self._render_model_context()

        self.api.request("GET", TEXT + f"/models/{model_id}/context", success=received)

    def save_model_context(self):
        if self.agent_panel.active:
            self.show_error("conversation_busy")
            return
        model = self._selected_chat_model()
        if not model or self._context_saving or self.active_job:
            return
        model_id = model["id"]
        body = {
            "mode": self.context_mode.currentData(),
            "manual_tokens": self.context_tokens.value(),
        }
        self._context_saving = True
        self.context_save.setEnabled(False)
        self.context_mode.setEnabled(False)
        self.context_tokens.setEnabled(False)

        def saved(record):
            self._context_saving = False
            self._context_dirty = False
            self.models = [record if item["id"] == model_id else item for item in self.models]
            self.model_contexts[model_id] = context_settings(record)
            self._refresh_model_context()
            self._render_model_context()
            self.notify(self.tr("context_saved"))

        def failed(code):
            self._context_saving = False
            self._render_model_context()
            self.show_error(code)

        self.api.request(
            "PUT", TEXT + f"/models/{model_id}/context", body, success=saved, failure=failed
        )

    def _parameters_for_model(self, model):
        parameters = dict(self.config.parameters)
        if model:
            parameters["context_size"] = context_settings(model)["effective_tokens"]
            if model["backend"] == "ollama":
                parameters.update(device="cpu", gpu_layers=0)
        return parameters

    def request_parameters(self):
        return self._parameters_for_model(self._selected_chat_model())

    def send_message(self):
        if self.agent_panel.active or self.agent_panel.compatibility_busy:
            return
        if self.active_job or self._submitting or self._context_saving or not self.is_connected:
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
        if self.agent_panel.settings_saving or self.agent_panel.settings_loading:
            return
        if self.agent_panel.mode.currentData() == "agent":
            self.agent_panel.send(content, model, self.request_parameters())
            return
        self.send_button.setEnabled(False)
        self._submitting = True
        payload = {
            "content": content,
            "request_key": uuid.uuid4().hex,
            "model_id": model,
            "parameters": self.request_parameters(),
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
            self._render_model_context()
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
        self._render_model_context()

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
        if self.agent_panel.active:
            self.agent_panel.stop()
            return
        if self.active_job:
            self.api.request(
                "POST",
                TEXT + f"/generations/{self.active_job}/cancel",
                success=self.generation_snapshot,
            )

    def render_messages(self):
        messages = [dict(message) for message in self.messages]
        if self.last_job:
            job = self.last_job
            replacement = {
                "role": "assistant",
                "content": job.get("content", ""),
                "model_name": job.get("model_name"),
                "reasoning_content": job.get("reasoning_content", ""),
                "statistics": job,
                "generation_id": job["id"],
            }
            index = next(
                (i for i, m in enumerate(messages) if m.get("generation_id") == job["id"]), None
            )
            if index is not None:
                messages[index] = replacement
            elif job.get("content") or job.get("reasoning_content"):
                messages.append(replacement)
        self.transcript.can_regenerate = bool(
            self.is_connected
            and self.model_combo.currentData()
            and not self.active_job
            and not self._submitting
        )
        self.transcript.set_messages(messages, self.tr)
        self.regenerate_button.setEnabled(
            self.is_connected
            and bool(self.model_combo.currentData())
            and not self.active_job
            and not self._submitting
            and any(m["role"] == "assistant" and m.get("content") for m in messages)
        )
        latest = next(
            (m.get("statistics") or {} for m in reversed(messages) if m["role"] == "assistant"), {}
        )
        self.context_details.setText(
            statistics_text(latest, self.tr) or self.tr("context_unavailable")
        )
        used, limit = latest.get("context_used_tokens"), latest.get("context_limit_tokens")
        if used is not None and limit:
            self.context_usage.setText(
                self.tr("context_last", used=used, limit=limit, percent=round(100 * used / limit))
            )
            self.context_meter.setValue(min(100, round(100 * used / limit)))
            self.context_meter.show()
        else:
            self.context_usage.setText(self.tr("context_unavailable"))
            self.context_meter.hide()
        self.context_usage.setToolTip("")
        device = latest.get("execution_device")
        if device:
            actual = "GPU" if latest.get("gpu_offloaded_layers", 0) else "CPU"
            self.context_usage.setText(self.context_usage.text() + " · " + actual)
            self.context_usage.setToolTip(str(device))

    def regenerate_answer(self, target=None):
        if self.active_job or self._submitting or not self.current_id or not self.is_connected:
            return
        if self.composer.toPlainText().strip():
            self.notify(self.tr("regenerate_draft"))
            return
        source = self.current_id
        self._submitting = True
        self.regenerate_button.setEnabled(False)

        def failed(code):
            self._submitting = False
            self.show_error(code)
            self.render_messages()

        def exported(document):
            messages = document["messages"]
            if isinstance(target, dict):
                target_index = next(
                    (
                        i
                        for i, m in enumerate(messages)
                        if (target.get("id") and m["id"] == target["id"])
                        or (
                            target.get("generation_id")
                            and m.get("generation_id") == target["generation_id"]
                        )
                    ),
                    None,
                )
                if target_index is None:
                    failed("not_found")
                    return
                messages = messages[: target_index + 1]
                document["messages"] = messages
            last_user = next(
                (i for i in range(len(messages) - 1, -1, -1) if messages[i]["role"] == "user"), None
            )
            if (
                last_user is None
                or self.current_id != source
                or not any(
                    m["role"] == "assistant" and m["content"].strip()
                    for m in messages[last_user + 1 :]
                )
            ):
                failed("no_answer")
                return
            content = messages[last_user]["content"]
            document["messages"] = messages[:last_user]
            document["title"] = (document["title"][:220] + " · " + self.tr("regenerate"))[:256]

            def imported(record):
                self._submitting = False
                if self.current_id != source:
                    self.refresh_conversations()
                    return
                self.current_id = record["id"]
                self.messages = document["messages"]
                self.last_job = None
                self.composer.setPlainText(content)
                self.refresh_conversations()
                self.send_message()

            self.api.request(
                "POST", TEXT + "/conversations/import", document, success=imported, failure=failed
            )

        self.api.request(
            "GET", TEXT + f"/conversations/{source}/export", success=exported, failure=failed
        )

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
            if records and not self.config.onboarding_complete:
                self.dismiss_welcome()
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
            self._render_model_context()
            self._refresh_model_context()
            self._loaded("models")

        self.api.request("GET", TEXT + "/models", success=received)

    def refresh_model_table(self):
        selected = self.selected_model()
        self.model_table.setHorizontalHeaderLabels(
            [self.tr(k) for k in ("model_name", "size", "engine", "compatibility")]
        )
        query = self.model_search.text().casefold().strip()
        favorites = self.config.favorite_models
        records = [
            r
            for r in self.models
            if r["backend"] == self.engine_filter.currentText()
            and (not self.favorites_only.isChecked() or r["id"] in favorites)
            and query
            in (
                r["name"]
                + " "
                + str(r.get("quantization") or "")
                + " "
                + str(r.get("metadata", {}).get("architecture") or "")
            ).casefold()
        ]
        sort = self.model_sort.currentData()
        records.sort(
            key=lambda r: (
                r.get("size_bytes") or 0
                if sort == "sort_size"
                else r.get("metadata", {}).get("last_inference", {}).get("at", "")
                if sort == "sort_recent"
                else r["name"].casefold()
            ),
            reverse=sort != "sort_name",
        )
        self.model_table.blockSignals(True)
        self.model_table.setRowCount(len(records))
        self.models_empty.setVisible(not records)
        selected_row = 0
        for row, record in enumerate(records):
            metadata = record.get("metadata", {})
            description = " · ".join(
                str(value)
                for value in (
                    record.get("format"),
                    record.get("quantization"),
                    metadata.get("architecture"),
                )
                if value
            )
            title = (
                ("★ " if record["id"] in favorites else "") + record["name"] + "\n" + description
            )
            for column, value in enumerate(
                (
                    title,
                    human_size(record["size_bytes"]),
                    record["backend"],
                    self.tr(record["compatibility"]),
                )
            ):
                item = QTableWidgetItem(value)
                item.setToolTip(escape(value))
                item.setData(Qt.UserRole, record["id"])
                self.model_table.setItem(row, column, item)
            if selected and selected["id"] == record["id"]:
                selected_row = row
        self.model_table.verticalHeader().setDefaultSectionSize(
            max(54, round(54 * self.config.ui_scale / 100))
        )
        if records:
            self.model_table.selectRow(selected_row)
        self.model_table.blockSignals(False)
        self.model_details()

    def toggle_favorite_model(self):
        record = self.selected_model()
        if not record:
            return
        favorites = self.config.favorite_models
        if record["id"] in favorites:
            favorites.remove(record["id"])
        else:
            favorites.append(record["id"])
        self.config.save()
        self.refresh_model_table()

    def configure_selected_model(self):
        record = self.selected_model()
        if record:
            self.model_combo.setCurrentIndex(self.model_combo.findData(record["id"]))
            self.navigate(0)
            self.context_mode.setFocus()

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
        self.favorite_button.setEnabled(bool(record))
        self.model_actions.setEnabled(bool(record))
        self.model_detail.setToolTip(escape(record["location"]) if record else "")
        if not record:
            self.model_detail.clear()
        if record:
            self.model_detail.setText(
                f"{record['name']} · {record['format']} · {record.get('quantization') or '—'}\n"
                f"{self.tr('license')}: {record.get('license') or self.tr('unknown')}"
            )
            details = self.model_detail.text()
            capabilities = record.get("capabilities") or []
            if capabilities:
                details += "\n" + " · ".join(capabilities)
            self.model_detail.setText(details)
            if record["backend"] == "llama.cpp":

                def context_received(settings):
                    current = self.selected_model()
                    if self._closing or not current or current["id"] != record["id"]:
                        return
                    applied = settings.get("applied_tokens")
                    status = (
                        self.tr("model_running_context", tokens=applied)
                        if applied is not None
                        else self.tr("model_not_loaded")
                    )
                    self.model_detail.setText(details + "\n" + status)

                self.api.request(
                    "GET", TEXT + f"/models/{record['id']}/context", success=context_received
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
            self._refresh_model_context()

        def failure(code):
            self._loading_model = False
            self.load_button.setEnabled(True)
            self.show_error("llama_unavailable" if code == "engine_unavailable" else code)

        self.api.request(
            "POST",
            TEXT + f"/models/{record['id']}/load",
            self._parameters_for_model(record),
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
                success=lambda _: (self.notify(self.tr("unloaded")), self._refresh_model_context()),
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

    def popular_hf(self):
        self.hf_query.clear()
        self.search_hf()

    def search_hf(self, *_):
        query = self.hf_query.text().strip()
        self._hf_search_sequence += 1
        sequence = self._hf_search_sequence

        def received(records):
            if sequence != self._hf_search_sequence:
                return
            self.hf_results.clear()
            self.hf_files.clear()
            self.hf_detail.clear()
            for record in records:
                repository = record.get("repository")
                if not repository:
                    continue
                author, _, model_name = repository.partition("/")
                title = model_name.replace("-", " ").replace("_", " ") or repository
                license_name = record.get("license")
                details = [author]
                if record.get("downloads") and str(record["downloads"]).isdigit():
                    details.append(f"{self.tr('downloads_count')}: {int(record['downloads']):,}")
                if license_name:
                    details.append(str(license_name))
                subtitle = " · ".join(details)
                item = QListWidgetItem(f"{title}\n{subtitle}")
                item.setToolTip(repository)
                item.setData(Qt.UserRole, record)
                self.hf_results.addItem(item)
            if self.hf_results.count():
                self.hf_results.setCurrentRow(0)

        self.api.request(
            "GET",
            TEXT
            + "/huggingface/search?"
            + urlencode({"query": query, "sort": self.hf_sort.currentData()}),
            success=received,
        )

    def _hf_selection_changed(self, current, previous):
        self.remote_files = []
        self.hf_files.clear()
        self.hf_detail.clear()
        self.hf_readme.clear()
        if not current:
            return
        record = current.data(Qt.UserRole)
        repository = record["repository"]
        self.hf_detail.setText(repository)
        self.list_hf_files()

        def still_selected():
            item = self.hf_results.currentItem()
            return item and item.data(Qt.UserRole)["repository"] == repository

        def readme_received(data):
            if still_selected():
                self.hf_readme.set_safe_markdown(data.get("markdown", ""))

        def details_received(data):
            if not still_selected():
                return
            fields = [
                ("author", data.get("author")),
                ("description", data.get("description")),
                ("architecture", data.get("architecture")),
                ("parameters", data.get("parameters")),
                ("license", data.get("license")),
                ("downloads_count", data.get("downloads")),
                (
                    "capabilities",
                    ", ".join(filter(None, [data.get("pipeline"), *data.get("tags", [])[:12]])),
                ),
            ]
            self.hf_detail.setText(
                repository
                + "\n"
                + "\n".join(
                    f"{self.tr(key)}: {str(value)[:500]}"
                    for key, value in fields
                    if value is not None and value != ""
                )
            )
            revision = data.get("revision")
            if revision:
                self.api.request(
                    "GET",
                    TEXT
                    + "/huggingface/readme?"
                    + urlencode({"repository": repository, "revision": revision}),
                    success=readme_received,
                    failure=lambda _: (
                        self.hf_readme.setPlainText(self.tr("readme_unavailable"))
                        if still_selected()
                        else None
                    ),
                )

        self.api.request(
            "GET",
            TEXT + "/huggingface/details?" + urlencode({"repository": repository}),
            success=details_received,
            failure=lambda _: (
                self.hf_readme.setPlainText(self.tr("readme_unavailable"))
                if still_selected()
                else None
            ),
        )

    def list_hf_files(self):
        item = self.hf_results.currentItem()
        if not item:
            return
        repository = item.data(Qt.UserRole)["repository"]

        def received(records):
            current = self.hf_results.currentItem()
            if not current or current.data(Qt.UserRole)["repository"] != repository:
                return
            self.remote_files = sorted(
                records,
                key=lambda record: (
                    is_multipart_gguf(record["filename"]),
                    "mmproj" in record["filename"].casefold(),
                    record["size_bytes"],
                ),
            )
            self._filter_hf_files()

        self.api.request(
            "GET",
            TEXT + "/huggingface/files?" + urlencode({"repository": repository}),
            success=received,
        )

    def _filter_hf_files(self, *_):
        selected = self.hf_files.currentData()
        name = selected.get("filename") if selected else None
        query = self.hf_quant_filter.text().strip().casefold()
        maximum = self.hf_size_filter.value() * 1024**3
        self.hf_files.clear()
        for record in self.remote_files:
            if query in record["filename"].casefold() and (
                not maximum or record["size_bytes"] <= maximum
            ):
                suffix = (
                    f" · {self.tr('multipart_short')}"
                    if is_multipart_gguf(record["filename"])
                    else ""
                )
                self.hf_files.addItem(
                    f"{record['filename']} · {human_size(record['size_bytes'])}{suffix}", record
                )
        for index in range(self.hf_files.count()):
            if self.hf_files.itemData(index)["filename"] == name:
                self.hf_files.setCurrentIndex(index)
                break
        self._hf_file_info()

    def _hf_file_info(self, *_):
        record = self.hf_files.currentData()
        if not record:
            self.hf_file_info.clear()
            self.download_button.setEnabled(False)
            return
        multipart = is_multipart_gguf(record["filename"])
        self.download_button.setEnabled(not multipart)
        self.hf_file_info.setText(
            self.tr("multipart_gguf_unsupported")
            if multipart
            else self.tr("memory_estimate", size=human_size(record["size_bytes"]))
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
                    + (f" · {record['percent']:.0f}%" if record.get("percent") is not None else ""),
                    record["id"],
                )
            index = self.download_list.findData(current)
            self.download_list.setCurrentIndex(max(index, 0))
            self.download_list.blockSignals(False)
            self._show_download_progress()

        self.api.request("GET", TEXT + "/downloads", success=received)

    def _show_download_progress(self, *_):
        record = self.selected_download()
        self.transfers_empty.setVisible(not self.downloads)
        self.download_list.setVisible(bool(self.downloads))
        self.download_progress.setVisible(record is not None)
        self.download_status.setVisible(record is not None)
        percent = record.get("percent") if record else None
        self.download_progress.setRange(0, 0 if record and percent is None else 100)
        if percent is not None:
            self.download_progress.setValue(max(0, min(100, int(percent))))
        elif not record:
            self.download_progress.setValue(0)
        state = record.get("state") if record else None
        self.cancel_download_button.setVisible(state in {"queued", "running"})
        self.resume_download_button.setVisible(state in {"failed", "cancelled", "interrupted"})
        self.import_download_button.setVisible(
            bool(record and state == "completed" and not record.get("model_id"))
        )
        if not record:
            self.download_status.clear()
            return
        speed, eta = record.get("speed_bytes_per_second"), record.get("eta_seconds")
        details = []
        if speed is not None:
            details.append(self.tr("download_speed", value=human_size(speed)))
        if eta is not None:
            details.append(self.tr("download_eta", seconds=int(eta)))
        if record.get("import_error"):
            details.append(self.tr("model_import_failed"))
        elif record.get("model_id"):
            details.append(self.tr("imported"))
        self.download_status.setText(" · ".join(details))
        if record.get("model_id") and record["model_id"] not in {r["id"] for r in self.models}:
            self.refresh_models()

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
        if record and record["state"] == "completed":
            self.api.request(
                "POST",
                TEXT + f"/downloads/{record['id']}/import",
                success=lambda _: self.refresh_downloads(),
            )
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

    def execution_mode_changed(self):
        layers = self.parameter_inputs["gpu_layers"]
        if self.device.currentData() == "cpu":
            layers.setValue(0)
        elif layers.value() == 0:
            layers.setValue(99)

    def choose_llama_cuda(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr("llama_cuda_server"))
        if path:
            self.llama_cuda_path.setText(path)

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
        cuda_path = self.llama_cuda_path.text().strip()
        if cuda_path and (not Path(cuda_path).is_file() or not os.access(cuda_path, os.X_OK)):
            self.show_error("llama_unavailable")
            return
        roots = [self.roots.item(i).text() for i in range(self.roots.count())]
        changed = (
            roots != self.config.model_roots
            or path != self.config.llama_server
            or cuda_path != self.config.llama_cuda_server
            or url != self.config.ollama_url
            or self.ollama_enabled.isChecked() != self.config.ollama_enabled
        )
        if changed and not self.session.owned:
            self.show_error("external_backend_settings")
            return
        self.config.model_roots, self.config.llama_server = roots, path
        self.config.llama_cuda_server = cuda_path
        self.config.ollama_url, self.config.ollama_enabled = url, self.ollama_enabled.isChecked()
        self.config.parameters.update({k: box.value() for k, box in self.parameter_inputs.items()})
        self.config.parameters.update(
            system_prompt=self.system_prompt.toPlainText(),
            device=self.device.currentData(),
            thinking=self.thinking.isChecked(),
        )
        if self.config.parameters["device"] == "cpu":
            self.config.parameters["gpu_layers"] = 0
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
            llama = next((r for r in records if r["info"]["id"] == "llama.cpp"), {})
            devices = llama.get("gpu_devices") or []
            self.engine_summary.setText(
                self.tr("gpu_detected", devices=", ".join(devices))
                if devices
                else self.tr(
                    "cpu_available"
                    if llama.get("info", {}).get("available")
                    else "llama_unavailable"
                )
            )
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

                if record.get("execution_device"):
                    lines.append(
                        f"{self.tr('execution_device')}: {record['execution_device']} · "
                        f"{self.tr('offloaded_layers')}: {record.get('gpu_offloaded_layers', 0)}"
                    )
                for gpu in record.get("nvidia_devices", []):
                    lines.append(
                        f"{gpu['name']} · {self.tr('vram')}: "
                        f"{human_size(gpu['free_bytes'])}/{human_size(gpu['total_bytes'])}"
                    )
                for candidate in record.get("candidates", []):
                    lines.append(
                        f"{candidate['path']}: "
                        + ", ".join(candidate["devices"])
                        + (
                            " · " + self.tr(candidate["error_code"])
                            if candidate.get("error_code")
                            else ""
                        )
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

    def first_import(self):
        self.navigate(1)
        self.choose_gguf()

    def dismiss_welcome(self):
        self.config.onboarding_complete = True
        self.config.save()
        self.onboarding.hide()

    def reconnect(self):
        if self._closing:
            return
        self.is_connected = False
        self._connection_key = "connecting"
        self.connection.setText(self.tr("connecting"))
        self.session.reconnect()

    def export_report(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("export_report"), "OmniCore-diagnostics.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            save_report(Path(path), diagnostic_report(self, QApplication.platformName()))
            self.notify(self.tr("report_saved"))
        except OSError:
            self.show_error("report_failed")

    def closeEvent(self, event):
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        self._closing = True
        self._poll.stop()
        self.agent_panel.timer.stop()
        self.pages.setEnabled(False)
        self._connection_key = "closing"
        self.connection.setText(self.tr("closing"))
        self.session.stop()

    def _stopped(self):
        if self._closing:
            self.api.close()
            self._allow_close = True
            self.close()
