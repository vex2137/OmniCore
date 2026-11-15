"""Native widgets for the existing API. Network and inference never block Qt."""

import errno
import math
import os
import platform
import stat
import uuid
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from PySide6.QtCore import (
    QEvent,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
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
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
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
from omnicore.desktop.errors import describe_error
from omnicore.desktop.history import grouped_history
from omnicore.desktop.i18n import Translator
from omnicore.desktop.model_card import safe_card_markdown
from omnicore.desktop.report import diagnostic_report, save_report
from omnicore.desktop.resources import (
    ResourceMonitor,
    ResourceSnapshot,
)
from omnicore.desktop.resources import (
    format_details as format_resource_details,
)
from omnicore.desktop.resources import (
    format_summary as format_resource_summary,
)
from omnicore.desktop.styles import (
    app_icon,
    build_stylesheet,
    ensure_arrow_icon,
    make_divider,
    polish_property,
)
from omnicore.desktop.themes import palette, resolve_theme_tokens
from omnicore.desktop.transcript import (
    ChatTranscript,
    statistics_text,
)
from omnicore.desktop.updates import UpdatePanel
from omnicore.release import build_info, distribution_version
from omnicore.text.context import CONTEXT_PRESETS, context_settings
from omnicore.text.downloads import is_multipart_gguf

TEXT = "/api/v1/text"
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
sidebar_icon = app_icon


def human_size(value):
    if value is None:
        return "—"
    number = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if number < 1024:
            return f"{number:.1f} {unit}"
        number /= 1024
    return f"{number:.1f} PiB"


def sidebar_text(text, metrics, width):
    """Wrap complete sidebar labels using the current platform's actual font metrics."""
    lines, line = [], ""
    for word in text.split():
        candidate = (line + " " + word).strip()
        if line and metrics.horizontalAdvance(candidate) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    return "\n".join([*lines, line])


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


class ModelComboBox(QComboBox):
    """Combo box that middle-elides closed text while keeping popup entries full-width."""

    def paintEvent(self, _event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        text_rect = self.style().subControlRect(
            QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, self
        )
        available = max(24, text_rect.width() - 4)
        option.currentText = self.fontMetrics().elidedText(
            self.currentText(), Qt.ElideRight, available
        )
        painter.drawControl(QStyle.CE_ComboBoxLabel, option)

    def showPopup(self):
        view = self.view()
        if view is not None:
            view.setTextElideMode(Qt.ElideNone)
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            fm = view.fontMetrics()
            max_text = max(
                (fm.horizontalAdvance(self.itemText(i)) for i in range(self.count())),
                default=0,
            )
            window_cap = max(420, self.window().width() - 48) if self.window() else 760
            view.setMinimumWidth(max(self.width(), min(max_text + 56, window_cap)))
        super().showPopup()


class MainWindow(QMainWindow):
    connected = Signal()

    def __init__(self, api, session, config):
        super().__init__()
        self.api, self.session, self.config = api, session, config
        self.config.parameters.setdefault("device", "auto")
        self.config.parameters.setdefault(
            "gpu_offload_mode",
            "cpu" if self.config.parameters["device"] == "cpu" else "auto",
        )
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
        self._gpu_saving = False
        self._gpu_dirty = False
        self._context_generation = 0
        self.engines = []
        self.is_connected = False
        self._connection_key = "connecting"
        self._closing = False
        self._allow_close = False
        self._pending_import = None
        self._pending_authorize_dir = None
        self._pending_authorize_model_id = None
        self._pending_authorize_target = None
        self._health_pending = set()
        self._backend_pid = None
        self._last_error_meta = None
        self._loaded_models = {}
        self._theme_colors = ("#ecf1f9", "#8b80f9", "#000000")
        self.resource_monitor = ResourceMonitor(self._resource_root_pids, interval_seconds=2.0)
        self.resource_monitor.updated.connect(self._apply_resource_snapshot)
        if hasattr(session, "ready"):
            session.ready.connect(self._sync_backend_pid)
        if hasattr(session, "stopped"):
            session.stopped.connect(self._sync_backend_pid)
        self.setWindowTitle(f"OmniCore · {distribution_version()}")
        self.resize(1280, 820)
        self.setMinimumSize(720, 460)
        self.setContentsMargins(0, 0, 0, 0)
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
        root.setObjectName("centralHost")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)
        self.shell = QSplitter(Qt.Horizontal)
        self.shell.setObjectName("mainShell")
        self.shell.setContentsMargins(0, 0, 0, 0)
        self.shell.setChildrenCollapsible(False)
        self.shell.setHandleWidth(1)
        layout.addWidget(self.shell)
        self.width_save_timer = QTimer(self)
        self.width_save_timer.setSingleShot(True)
        self.width_save_timer.setInterval(250)
        self.width_save_timer.timeout.connect(self.config.save)
        self.width_save_timer.timeout.connect(self._fill_conversations)
        self.shell.splitterMoved.connect(self.sidebar_dragged)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.installEventFilter(self)
        self.side_layout = QVBoxLayout(self.sidebar)
        self.side_layout.setContentsMargins(10, 12, 10, 12)
        self.side_layout.setSpacing(8)
        self.brand_mark = QLabel()
        self.brand_mark.setObjectName("brandMark")
        self.brand = QLabel("OmniCore")
        self.brand.setObjectName("brand")
        self.sidebar_header = QHBoxLayout()
        self.sidebar_header.setContentsMargins(2, 0, 0, 4)
        self.sidebar_header.setSpacing(8)
        self.sidebar_header.addWidget(self.brand_mark)
        self.sidebar_header.addWidget(self.brand, 1)
        self.side_layout.addLayout(self.sidebar_header)
        self.sidebar_toggle = QPushButton()
        self.sidebar_toggle.setObjectName("sidebarToggle")
        self.sidebar_toggle.setCursor(Qt.PointingHandCursor)
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)
        self.sidebar_toggle.setFixedSize(32, 32)
        self.sidebar_header.addWidget(self.sidebar_toggle)
        self.new_button = self.button("new_chat", self.new_conversation, primary=True)
        self.new_button.setCursor(Qt.PointingHandCursor)
        self.nav = []
        for index, key in enumerate(("chat", "models", "settings", "diagnostics")):
            button = self.button(key, lambda checked=False, i=index: self.navigate(i))
            button.setCheckable(True)
            button.setObjectName("nav")
            button.setCursor(Qt.PointingHandCursor)
            self.nav.append(button)
        self.top_actions_grid = QGridLayout()
        self.top_actions_grid.setContentsMargins(0, 0, 0, 0)
        self.top_actions_grid.setSpacing(6)
        self.top_actions_grid.addWidget(self.new_button, 0, 0)
        self.top_actions_grid.addWidget(self.nav[0], 0, 1)
        self.side_layout.addLayout(self.top_actions_grid)

        self._history_search_open = False
        self.history_panel = QWidget()
        self.history_panel.setObjectName("historyPanel")
        left = QVBoxLayout(self.history_panel)
        left.setContentsMargins(0, 4, 0, 0)
        left.setSpacing(6)
        self.history_toolbar = QHBoxLayout()
        self.history_toolbar.setContentsMargins(0, 0, 0, 2)
        self.history_toolbar.setSpacing(6)
        self.history_search_toggle = QPushButton()
        self.history_search_toggle.setObjectName("historySearchTrigger")
        self.history_search_toggle.setCursor(Qt.PointingHandCursor)
        self.history_search_toggle.clicked.connect(self.open_history_search)
        self.history_menu_btn = QPushButton()
        self.history_menu_btn.setObjectName("historyHeaderButton")
        self.history_menu_btn.setCursor(Qt.PointingHandCursor)
        self.history_menu_btn.clicked.connect(self.open_history_menu)
        self.history_search = QLineEdit()
        self.history_search.setObjectName("historySearch")
        self.history_search.setMaxLength(256)
        self.history_search.setClearButtonEnabled(True)
        self.history_search.installEventFilter(self)
        self.history_search.hide()
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.refresh_conversations)
        self.history_search.textChanged.connect(lambda _: self.search_timer.start())
        self.history_search_close = QPushButton()
        self.history_search_close.setObjectName("historyHeaderButton")
        self.history_search_close.setCursor(Qt.PointingHandCursor)
        self.history_search_close.clicked.connect(self.close_history_search)
        self.history_search_close.hide()
        self.history_toolbar.addWidget(self.history_search_toggle, 1)
        self.history_toolbar.addWidget(self.history_menu_btn)
        self.history_toolbar.addWidget(self.history_search, 1)
        self.history_toolbar.addWidget(self.history_search_close)
        left.addLayout(self.history_toolbar)

        self.sidebar_width = QSpinBox()
        self.sidebar_width.setRange(200, 360)
        self.sidebar_width.setValue(self.config.sidebar_width)
        self.sidebar_width.setSuffix(" px")
        self.sidebar_width.valueChanged.connect(self.resize_sidebar)

        self.conversation_list = QListWidget()
        self.conversation_list.setObjectName("conversations")
        self.conversation_list.setFrameShape(QFrame.NoFrame)
        self.conversation_list.viewport().setAutoFillBackground(False)
        self.conversation_list.setLayoutMode(QListWidget.Batched)
        self.conversation_list.setBatchSize(128)
        self.conversation_list.setWordWrap(False)
        self.conversation_list.setTextElideMode(Qt.ElideRight)
        self.conversation_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.conversation_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.conversation_list.customContextMenuRequested.connect(self.conversation_menu)
        self.conversation_list.currentItemChanged.connect(self.select_conversation)
        self.conversation_list.currentItemChanged.connect(self.update_history_selection)
        self.conversation_list.itemClicked.connect(
            lambda _item=None: self.navigate(0) if self.pages.currentIndex() != 0 else None
        )
        left.addWidget(self.conversation_list, 1)
        self.side_layout.addWidget(self.history_panel, 1)
        self.compact_spacer = QWidget()
        self.compact_spacer.setObjectName("compactSpacer")
        self.side_layout.addWidget(self.compact_spacer, 1)
        self.nav_footer_divider = make_divider()
        self.side_layout.addWidget(self.nav_footer_divider)
        self.side_layout.addWidget(self.nav[1])
        self.side_layout.addWidget(self.nav[3])
        self.side_layout.addWidget(self.nav[2])
        self.shell.addWidget(self.sidebar)

        main = QWidget()
        main.setObjectName("mainPane")
        main.setMinimumWidth(360)
        main.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.main_pane = main
        self.body_layout = QVBoxLayout(main)
        body = self.body_layout
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.topbar = QFrame()
        self.topbar.setObjectName("appTopbar")
        self.topbar_layout = QHBoxLayout(self.topbar)
        topbar_layout = self.topbar_layout
        topbar_layout.setContentsMargins(
            self._scaled(16), self._scaled(10), self._scaled(16), self._scaled(10)
        )
        topbar_layout.setSpacing(8)
        self.chat_header_widget = QWidget()
        self.chat_header_widget.setMinimumWidth(0)
        self.chat_header = QHBoxLayout(self.chat_header_widget)
        self.chat_header.setContentsMargins(0, 0, 0, 0)
        self.chat_header.setSpacing(8)
        topbar_layout.addWidget(self.chat_header_widget, 1)
        self.page_title = self.label("chat", title=True)
        self.page_title.hide()
        topbar_layout.addWidget(self.page_title, 1)
        self.chat_gpu_pill = QLabel("GPU")
        self.chat_gpu_pill.setObjectName("statusPill")
        self.chat_gpu_pill.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.chat_gpu_pill.hide()
        topbar_layout.addWidget(self.chat_gpu_pill)
        self.resource_monitor_btn = QPushButton(
            format_resource_summary(ResourceSnapshot(), self.tr)
        )
        self.resource_monitor_btn.setObjectName("resourceMonitorBtn")
        self.resource_monitor_btn.setCheckable(True)
        self.resource_monitor_btn.setCursor(Qt.PointingHandCursor)
        self.resource_monitor_btn.setToolTip(self.tr("resources_tooltip"))
        self.resource_monitor_btn.setAccessibleName(self.tr("resources_label"))
        self.resource_monitor_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        topbar_layout.addWidget(self.resource_monitor_btn)
        self.connection = self.label("connecting")
        self.connection.setObjectName("statusPill")
        self.connection.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        polish_property(self.connection, "tone", "warn")
        topbar_layout.addWidget(self.connection)
        self.reconnect_button = self.button("reconnect", self.reconnect)
        self.reconnect_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.reconnect_button.hide()
        topbar_layout.addWidget(self.reconnect_button)
        self.context_button = QPushButton()
        self.context_button.setObjectName("iconButton")
        self.context_button.setCursor(Qt.PointingHandCursor)
        self.context_button.setFixedWidth(32)
        self.context_button.setCheckable(True)
        topbar_layout.addWidget(self.context_button)
        body.addWidget(self.topbar)

        self.alerts_layout = QVBoxLayout()
        self.alerts_layout.setContentsMargins(self._scaled(16), 0, self._scaled(16), 0)
        self.alerts_layout.setSpacing(self._scaled(8))
        body.addLayout(self.alerts_layout)

        self.resource_details_frame = QFrame()
        self.resource_details_frame.setObjectName("resourceDetails")
        self.resource_details_frame.hide()
        res_layout = QVBoxLayout(self.resource_details_frame)
        res_layout.setContentsMargins(12, 8, 12, 8)
        self.resource_details_label = QLabel(format_resource_details(ResourceSnapshot(), self.tr))
        self.resource_details_label.setObjectName("mutedMeta")
        self.resource_details_label.setTextFormat(Qt.PlainText)
        self.resource_details_label.setWordWrap(True)
        self.resource_details_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        res_layout.addWidget(self.resource_details_label)
        self.resource_monitor_btn.toggled.connect(self.resource_details_frame.setVisible)
        self.alerts_layout.addWidget(self.resource_details_frame)

        self.notice_card = QFrame()
        self.notice_card.setObjectName("noticeCard")
        self.notice_card.hide()
        notice_layout = QVBoxLayout(self.notice_card)
        notice_layout.setContentsMargins(12, 10, 12, 10)
        notice_layout.setSpacing(8)
        notice_row = QHBoxLayout()
        notice_row.setContentsMargins(0, 0, 0, 0)
        notice_row.setSpacing(8)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.PlainText)
        self.notice.setObjectName("notice")
        self.notice.hide()
        self.notice_action_button = QPushButton()
        self.notice_action_button.setObjectName("primary")
        self.notice_action_button.setCursor(Qt.PointingHandCursor)
        self.notice_action_button.clicked.connect(lambda: self.authorize_model_directory())
        self.notice_action_button.hide()
        self.notice_details_toggle = QPushButton(self.tr("error_details_toggle"))
        self.notice_details_toggle.setObjectName("errorDetailsToggle")
        self.notice_details_toggle.setCheckable(True)
        self.notice_details_toggle.setCursor(Qt.PointingHandCursor)
        self.notice_details_toggle.hide()
        self.notice_close = QToolButton()
        self.notice_close.setObjectName("noticeClose")
        self.notice_close.setText("×")
        self.notice_close.setToolTip(self.tr("close_notice"))
        self.notice_close.setCursor(Qt.PointingHandCursor)
        self.notice_close.clicked.connect(self._dismiss_notice)
        notice_row.addWidget(self.notice, 1)
        notice_row.addWidget(self.notice_action_button)
        notice_row.addWidget(self.notice_details_toggle)
        notice_row.addWidget(self.notice_close)
        notice_layout.addLayout(notice_row)
        self.notice_details_frame = QFrame()
        self.notice_details_frame.setObjectName("errorDetailsBox")
        self.notice_details_frame.hide()
        nd_layout = QVBoxLayout(self.notice_details_frame)
        nd_layout.setContentsMargins(10, 8, 10, 8)
        self.notice_details_label = QLabel()
        self.notice_details_label.setObjectName("mutedMeta")
        self.notice_details_label.setTextFormat(Qt.PlainText)
        self.notice_details_label.setWordWrap(True)
        self.notice_details_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        nd_layout.addWidget(self.notice_details_label)
        self.notice_details_toggle.toggled.connect(self.notice_details_frame.setVisible)
        notice_layout.addWidget(self.notice_details_frame)
        self.alerts_layout.addWidget(self.notice_card)
        self._sync_backend_pid()
        self.resource_monitor.start()
        self.onboarding = QFrame()
        self.onboarding.setObjectName("onboardingCard")
        self.onboarding.setMaximumWidth(540)
        intro = QVBoxLayout(self.onboarding)
        intro.setContentsMargins(14, 12, 14, 12)
        intro.setSpacing(8)
        intro.addWidget(self.label("welcome_title", title=True))
        intro_text = self.label("welcome_steps")
        intro_text.setObjectName("subtleHint")
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
        self.pages = QStackedWidget()
        self.pages.setMinimumWidth(0)
        self.pages.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.pages.setContentsMargins(0, 0, 0, 0)
        if self.pages.layout():
            self.pages.layout().setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.pages, 1)
        self._build_chat()
        self._build_models()
        self._build_settings()
        self._build_diagnostics()
        self.shell.addWidget(main)
        self.shell.setStretchFactor(0, 0)
        self.shell.setStretchFactor(1, 1)
        self._apply_sidebar()
        self.nav[0].setChecked(True)
        self.statusBar().showMessage(self.tr("connecting"))
        self.statusBar().hide()
        self.pages.setEnabled(False)

    def _build_chat(self):
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        pane = QWidget()
        self.chat_pane = pane
        chat = QVBoxLayout(pane)
        self.chat_pane_layout = chat
        chat.setContentsMargins(
            self._scaled(16), self._scaled(8), self._scaled(16), self._scaled(10)
        )
        chat.setSpacing(self._scaled(8))

        self.model_combo = ModelComboBox()
        self.model_combo.setMinimumWidth(160)
        self.model_combo.setMaximumWidth(440)
        self.model_combo.setMinimumContentsLength(16)
        self.model_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.model_combo.currentIndexChanged.connect(self.model_selected)

        self.chat_refresh = QPushButton()
        self.chat_refresh.setObjectName("iconButton")
        self.chat_refresh.setCursor(Qt.PointingHandCursor)
        self.chat_refresh.setFixedSize(32, 32)
        self.chat_refresh.clicked.connect(self.refresh_models)

        self.mode_switch = QFrame()
        self.mode_switch.setObjectName("modeSwitch")
        self.mode_switch.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        mode_layout = QHBoxLayout(self.mode_switch)
        mode_layout.setContentsMargins(2, 2, 2, 2)
        mode_layout.setSpacing(2)
        self.mode_chat_btn = QPushButton(self.tr("agent_chat"))
        self.mode_chat_btn.setObjectName("modeSegBtn")
        self.mode_chat_btn.setCheckable(True)
        self.mode_chat_btn.setChecked(True)
        self.mode_chat_btn.setCursor(Qt.PointingHandCursor)
        self.mode_agent_btn = QPushButton(self.tr("agent_mode"))
        self.mode_agent_btn.setObjectName("modeSegBtn")
        self.mode_agent_btn.setCheckable(True)
        self.mode_agent_btn.setCursor(Qt.PointingHandCursor)
        self.mode_group = QButtonGroup(self.mode_switch)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.mode_chat_btn)
        self.mode_group.addButton(self.mode_agent_btn)
        self.mode_chat_btn.clicked.connect(lambda: self._set_mode_from_pill("chat"))
        self.mode_agent_btn.clicked.connect(lambda: self._set_mode_from_pill("agent"))
        mode_layout.addWidget(self.mode_chat_btn)
        mode_layout.addWidget(self.mode_agent_btn)

        self.agent_panel = AgentPanel(self)
        self.agent_panel.mode.hide()
        self.agent_panel.mode.currentIndexChanged.connect(
            lambda _index=0: self._sync_mode_settings()
        )
        self.chat_header.addWidget(self.model_combo, 100)
        self.chat_header.addWidget(self.chat_refresh)
        self.chat_header.addWidget(self.mode_switch)
        self.chat_header.addStretch(1)
        self.chat_header.addWidget(self.agent_panel.mode)

        self.context_button.toggled.connect(lambda _checked=False: self._sync_mode_settings())
        self.context_button.toggled.connect(lambda _checked=False: self._sync_chat_icons())

        self.transcript = ChatTranscript()
        self.transcript.regenerate_requested.connect(self.regenerate_answer)
        self.transcript.authorize_directory_requested.connect(self.authorize_model_directory)
        self.transcript.grant_folder_requested.connect(self.agent_panel.grant_folder)
        self.transcript.continue_run_requested.connect(self.agent_panel.continue_run)
        self.transcript.empty_slot.addWidget(self.onboarding, 0, Qt.AlignHCenter)
        self.transcript.sync_empty_state(self.tr)
        chat.addWidget(self.transcript, 1)

        self.composer_wrap = QWidget()
        self.composer_wrap.setMinimumWidth(0)
        self.composer_wrap.setMaximumWidth(850)
        wrap_layout = QVBoxLayout(self.composer_wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.setSpacing(6)

        self.agent_inline_banner = QFrame()
        self.agent_inline_banner.setObjectName("agentInlineBanner")
        self.agent_inline_banner.hide()
        banner_layout = QHBoxLayout(self.agent_inline_banner)
        banner_layout.setContentsMargins(12, 6, 10, 6)
        banner_layout.setSpacing(8)
        self.agent_banner_label = QLabel()
        self.agent_banner_label.setObjectName("mutedMeta")
        self.agent_banner_label.setTextFormat(Qt.PlainText)
        self.agent_banner_label.setWordWrap(False)
        self.agent_banner_retry_btn = QPushButton(self.tr("agent_retry"))
        self.agent_banner_retry_btn.setObjectName("primary")
        self.agent_banner_retry_btn.setCursor(Qt.PointingHandCursor)
        self.agent_banner_retry_btn.clicked.connect(self.agent_panel.retry)
        self.agent_banner_retry_btn.hide()
        self.agent_banner_open_btn = QPushButton(self.tr("drawer_title"))
        self.agent_banner_open_btn.setObjectName("compactToggle")
        self.agent_banner_open_btn.setCursor(Qt.PointingHandCursor)
        self.agent_banner_open_btn.clicked.connect(lambda: self.context_button.setChecked(True))
        banner_layout.addWidget(self.agent_banner_label, 1)
        banner_layout.addWidget(self.agent_banner_retry_btn)
        banner_layout.addWidget(self.agent_banner_open_btn)
        wrap_layout.addWidget(self.agent_inline_banner)

        self.composer_box = QFrame()
        self.composer_box.setObjectName("composerBox")
        self.composer_box.setProperty("focused", False)
        box_layout = QHBoxLayout(self.composer_box)
        box_layout.setContentsMargins(12, 6, 8, 6)
        box_layout.setSpacing(8)
        self.composer = Composer()
        self.composer.submitted.connect(self.send_message)
        self.composer.focus_changed.connect(self._set_composer_focused)
        self.composer.setObjectName("composer")
        box_layout.addWidget(self.composer, 1)

        self.stop_button = QPushButton()
        self.stop_button.setObjectName("composerStopBtn")
        self.stop_button.setCursor(Qt.PointingHandCursor)
        self.stop_button.setToolTip(self.tr("stop"))
        self.stop_button.setAccessibleName(self.tr("stop"))
        self.stop_button.clicked.connect(self.stop_generation)
        self.stop_button.setEnabled(False)
        self.stop_button.hide()
        self.send_button = QPushButton()
        self.send_button.setObjectName("composerSendBtn")
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.setToolTip(self.tr("send"))
        self.send_button.setAccessibleName(self.tr("send"))
        self.send_button.clicked.connect(self.send_message)
        composer_btns = QHBoxLayout()
        composer_btns.setContentsMargins(0, 0, 0, 0)
        composer_btns.setSpacing(6)
        composer_btns.addWidget(self.stop_button, 0, Qt.AlignBottom)
        composer_btns.addWidget(self.send_button, 0, Qt.AlignBottom)
        box_layout.addLayout(composer_btns)
        wrap_layout.addWidget(self.composer_box)

        self.generation_status = self.label("ready")
        self.generation_status.setObjectName("composerMeta")
        self.generation_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.composer_hint = QLabel(self.tr("composer_hint"))
        self.composer_hint.setObjectName("composerMeta")
        self.composer_hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        meta_caption = QHBoxLayout()
        meta_caption.setContentsMargins(8, 0, 8, 2)
        meta_caption.setSpacing(8)
        meta_caption.addWidget(self.generation_status, 1)
        meta_caption.addWidget(self.composer_hint)
        wrap_layout.addLayout(meta_caption)

        composer_row = QHBoxLayout()
        composer_row.setContentsMargins(16, 0, 16, 2)
        composer_row.addStretch(1)
        composer_row.addWidget(self.composer_wrap, 100)
        composer_row.addStretch(1)
        chat.addLayout(composer_row)
        outer.addWidget(pane, 1)

        self.chat_drawer = QFrame()
        self.chat_drawer.setObjectName("rightDrawer")
        self.chat_drawer.setFixedWidth(320)
        self.chat_drawer.hide()
        drawer_outer = QVBoxLayout(self.chat_drawer)
        drawer_outer.setContentsMargins(0, 0, 0, 0)
        drawer_outer.setSpacing(0)
        drawer_hdr = QHBoxLayout()
        drawer_hdr.setContentsMargins(14, 10, 10, 8)
        drawer_hdr.setSpacing(8)
        self.drawer_title = QLabel(self.tr("drawer_title"))
        self.drawer_title.setObjectName("drawerHeading")
        self.drawer_close_btn = QPushButton()
        self.drawer_close_btn.setObjectName("iconButton")
        self.drawer_close_btn.setCursor(Qt.PointingHandCursor)
        self.drawer_close_btn.setFixedSize(28, 28)
        self.drawer_close_btn.setToolTip(self.tr("close_notice"))
        self.drawer_close_btn.setAccessibleName(self.tr("close_notice"))
        self.drawer_close_btn.clicked.connect(lambda: self.context_button.setChecked(False))
        drawer_hdr.addWidget(self.drawer_title, 1)
        drawer_hdr.addWidget(self.drawer_close_btn)
        drawer_outer.addLayout(drawer_hdr)
        drawer_outer.addWidget(make_divider())

        self.chat_drawer_scroll = QScrollArea()
        self.chat_drawer_scroll.setObjectName("drawerScroll")
        self.chat_drawer_scroll.setWidgetResizable(True)
        self.chat_drawer_scroll.setFrameShape(QFrame.NoFrame)
        self.chat_drawer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        drawer_body = QWidget()
        drawer_body.setObjectName("drawerBody")
        drawer_body_layout = QVBoxLayout(drawer_body)
        drawer_body_layout.setContentsMargins(12, 10, 12, 14)
        drawer_body_layout.setSpacing(12)

        self.context_controls = QFrame()
        self.context_controls.setObjectName("contextCard")
        context_layout = QVBoxLayout(self.context_controls)
        context_layout.setContentsMargins(2, 2, 2, 2)
        context_layout.setSpacing(8)
        self.context_controls.hide()
        self.context_label = self.label("context_label")
        self.context_label.setObjectName("drawerHeading")
        self.context_preset = QComboBox()
        self.context_preset.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.context_preset.setMinimumContentsLength(6)
        self.context_preset.setAccessibleName(self.tr("context_configure"))
        self._populate_context_presets(1_000_000)
        self.context_preset.currentIndexChanged.connect(self._context_preset_changed)
        self.context_mode = QComboBox()
        self.context_mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.context_mode.setMinimumContentsLength(6)
        self.context_mode.addItem(self.tr("context_auto"), "auto")
        self.context_mode.addItem(self.tr("context_manual"), "manual")
        self.context_mode.currentIndexChanged.connect(self._context_mode_changed)
        self.context_mode.currentIndexChanged.connect(self._context_edited)
        self.context_tokens = QSpinBox()
        self.context_tokens.setRange(128, 1_000_000)
        self.context_tokens.setSingleStep(256)
        self.context_tokens.setValue(2048)
        self.context_tokens.setMinimumWidth(56)
        self.context_tokens.valueChanged.connect(self._context_edited)
        self.context_tokens.valueChanged.connect(self._sync_context_preset)
        self.context_save = self.button("context_save", self.save_model_context)
        self.context_save.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        context_layout.addWidget(self.context_label)
        context_layout.addWidget(self.context_mode)
        context_layout.addWidget(self.context_preset)
        ctx_row2 = QHBoxLayout()
        ctx_row2.setContentsMargins(0, 0, 0, 0)
        ctx_row2.setSpacing(6)
        ctx_row2.addWidget(self.context_tokens, 1)
        ctx_row2.addWidget(self.context_save)
        context_layout.addLayout(ctx_row2)
        self.context_status = QLabel()
        self.context_status.setObjectName("mutedMeta")
        self.context_status.setWordWrap(True)
        self.context_slider = QSlider(Qt.Horizontal)
        self.context_slider.setRange(0, 1000)
        self.context_slider.setAccessibleName(self.tr("context_configure"))
        self.context_slider.valueChanged.connect(self.context_slider_changed)
        self.context_tokens.valueChanged.connect(self.sync_context_slider)
        context_layout.addWidget(self.context_slider)
        context_layout.addWidget(self.context_status)

        self.context_usage = QLabel()
        self.context_usage.setObjectName("mutedMeta")
        self.context_usage.setWordWrap(True)
        self.context_usage.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.context_meter = QProgressBar()
        self.context_meter.setRange(0, 100)
        self.context_meter.setMaximumHeight(6)
        self.context_meter.setMaximumWidth(84)
        self.context_meter.setObjectName("contextMeter")
        self.context_meter.setTextVisible(False)
        self.context_toggle = self.button("context_details", lambda: None)
        self.context_toggle.setObjectName("compactToggle")
        self.context_toggle.setCheckable(True)
        self.context_toggle.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.context_details = QLabel()
        self.context_details.setObjectName("mutedMeta")
        self.context_details.setTextFormat(Qt.PlainText)
        self.context_details.setWordWrap(True)
        self.context_details.hide()
        self.context_toggle.toggled.connect(self.context_details.setVisible)
        usage_row = QHBoxLayout()
        usage_row.setContentsMargins(0, 0, 0, 0)
        usage_row.setSpacing(8)
        usage_row.addWidget(self.context_usage, 1)
        usage_row.addWidget(self.context_meter)
        context_layout.addLayout(usage_row)
        context_layout.addWidget(self.context_toggle, 0, Qt.AlignLeft)
        context_layout.addWidget(self.context_details)

        self.context_gpu_divider = make_divider("contextDivider")
        context_layout.addWidget(self.context_gpu_divider)
        self.chat_gpu_label = self.label("gpu_section_label")
        self.chat_gpu_label.setObjectName("drawerHeading")
        self.chat_gpu_mode = QComboBox()
        self.chat_gpu_mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.chat_gpu_mode.setMinimumContentsLength(8)
        self.chat_gpu_mode.setAccessibleName(self.tr("gpu_offload_mode"))
        for key in ("auto", "max", "manual", "cpu"):
            self.chat_gpu_mode.addItem(self.tr("offload_" + key), key)
        self.chat_gpu_mode.currentIndexChanged.connect(self._chat_gpu_mode_changed)
        self.chat_gpu_mode.currentIndexChanged.connect(self._chat_gpu_edited)
        self.chat_gpu_layers = QSpinBox()
        self.chat_gpu_layers.setRange(0, 999)
        self.chat_gpu_layers.setValue(99)
        self.chat_gpu_layers.setMinimumWidth(56)
        self.chat_gpu_layers.setAccessibleName(self.tr("gpu_layers"))
        self.chat_gpu_layers.valueChanged.connect(self._chat_gpu_edited)
        self.chat_gpu_save = self.button("save_short", self.save_model_gpu)
        self.chat_gpu_save.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        context_layout.addWidget(self.chat_gpu_label)
        context_layout.addWidget(self.chat_gpu_mode)
        gpu_row = QHBoxLayout()
        gpu_row.setContentsMargins(0, 0, 0, 0)
        gpu_row.setSpacing(6)
        gpu_row.addWidget(self.chat_gpu_layers, 1)
        gpu_row.addWidget(self.chat_gpu_save)
        context_layout.addLayout(gpu_row)
        self.chat_gpu_status = QLabel()
        self.chat_gpu_status.setObjectName("mutedMeta")
        self.chat_gpu_status.setTextFormat(Qt.PlainText)
        self.chat_gpu_status.setWordWrap(True)
        context_layout.addWidget(self.chat_gpu_status)
        self.context_reload_btn = self.button("gpu_reload_now", self.reload_selected_chat_model)
        self.context_reload_btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.context_reload_btn.hide()
        context_layout.addWidget(self.context_reload_btn, 0, Qt.AlignLeft)

        drawer_body_layout.addWidget(self.context_controls)
        drawer_body_layout.addWidget(self.agent_panel)
        drawer_body_layout.addStretch(1)
        self.chat_drawer_scroll.setWidget(drawer_body)
        drawer_outer.addWidget(self.chat_drawer_scroll, 1)
        outer.addWidget(self.chat_drawer)
        if getattr(self.config, "drawer_open", False):
            self.context_button.blockSignals(True)
            self.context_button.setChecked(True)
            self.context_button.blockSignals(False)
        self.context_button.toggled.connect(self._on_drawer_toggled)
        self.pages.addWidget(page)

    def _build_models(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.models_page_layout = layout
        layout.setContentsMargins(
            self._scaled(16), self._scaled(10), self._scaled(16), self._scaled(10)
        )
        layout.setSpacing(10)
        self.model_tabs = QTabWidget()
        layout.addWidget(self.model_tabs, 1)

        installed = QWidget()
        local = QVBoxLayout(installed)
        local.setContentsMargins(0, 10, 0, 0)
        local.setSpacing(10)

        controls_strip = QFrame()
        controls_strip.setObjectName("toolbarStrip")
        controls_layout = QVBoxLayout(controls_strip)
        controls_layout.setContentsMargins(0, 0, 0, 10)
        controls_layout.setSpacing(8)
        self.engine_filter = QComboBox()
        self.engine_filter.addItems(["llama.cpp", "ollama"])
        self.engine_filter.currentTextChanged.connect(self.refresh_model_table)
        self.scan_button = self.button("scan_models", self.scan_models)
        import_btn = self.button("import_gguf", self.choose_gguf, primary=True)
        sync_btn = self.button("sync_ollama", self.sync_ollama)
        refresh_btn = self.button("refresh", self.refresh_models)
        for btn in (import_btn, self.scan_button, sync_btn, refresh_btn):
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        action_bar = QHBoxLayout()
        action_bar.setContentsMargins(0, 0, 0, 0)
        action_bar.setSpacing(8)
        action_bar.addWidget(import_btn)
        action_bar.addWidget(self.scan_button)
        action_bar.addWidget(sync_btn)
        models_hint = self.label("model_hint")
        models_hint.setObjectName("mutedMeta")
        action_bar.addStretch(1)
        action_bar.addWidget(models_hint)
        action_bar.addWidget(refresh_btn)
        controls_layout.addLayout(action_bar)

        self.model_search = QLineEdit()
        self.model_search.textChanged.connect(self.refresh_model_table)
        self.model_sort = QComboBox()
        for key in ("sort_name", "sort_size", "sort_recent"):
            self.model_sort.addItem(self.tr(key), key)
        self.model_sort.currentIndexChanged.connect(self.refresh_model_table)
        self.favorites_only = QCheckBox(self.tr("favorites_only"))
        self._texts.append((self.favorites_only, "favorites_only"))
        self.favorites_only.toggled.connect(self.refresh_model_table)
        filter_bar = self.row(
            self.model_search, self.engine_filter, self.model_sort, self.favorites_only
        )
        filter_bar.setStretch(0, 1)
        controls_layout.addLayout(filter_bar)
        local.addWidget(controls_strip)

        self.models_empty = self.label("models_empty")
        self.models_empty.setObjectName("subtleHint")
        local.addWidget(self.models_empty)

        self.model_table = QTableWidget(0, 5)
        self.model_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.model_table.setSelectionMode(QTableWidget.SingleSelection)
        self.model_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.model_table.setShowGrid(False)
        self.model_table.setAlternatingRowColors(True)
        self.model_table.verticalHeader().hide()
        self.model_table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.model_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3, 4):
            self.model_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents
            )
        self.model_table.itemSelectionChanged.connect(self.model_details)
        local.addWidget(self.model_table, 1)

        inspector = QFrame()
        inspector.setObjectName("modelInspector")
        footer_layout = QHBoxLayout(inspector)
        footer_layout.setContentsMargins(14, 10, 14, 10)
        footer_layout.setSpacing(12)
        self.model_detail = self.label("model_details")
        self.model_detail.setObjectName("subtleHint")
        self.model_detail.setTextFormat(Qt.PlainText)
        self.model_detail.setWordWrap(True)
        footer_layout.addWidget(self.model_detail, 1)
        self.favorite_button = self.button("favorite_toggle", self.toggle_favorite_model)
        self.model_authorize_button = self.button(
            "authorize_model_directory", self.authorize_selected_model, primary=True
        )
        self.model_authorize_button.hide()
        self.load_button = self.button("load", self.load_model, primary=True)
        configure_btn = self.button("model_configure", self.configure_selected_model)
        self.model_actions = QToolButton()
        self.model_actions.setObjectName("iconButton")
        self.model_actions.setCursor(Qt.PointingHandCursor)
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
        for btn in (
            self.model_authorize_button,
            self.load_button,
            self.favorite_button,
            configure_btn,
        ):
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            footer_layout.addWidget(btn)
        footer_layout.addWidget(self.model_actions)
        local.addWidget(inspector)
        self.model_tabs.addTab(installed, "")

        remote = QWidget()
        hf = QVBoxLayout(remote)
        hf.setContentsMargins(0, 10, 0, 0)
        hf.setSpacing(10)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        left = QFrame()
        left.setObjectName("sectionGroup")
        right = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 12, 14, 12)
        right_layout.setSpacing(10)
        self.hf_query = QLineEdit()
        self.hf_query.returnPressed.connect(self.search_hf)
        hf_search_btn = self.button("search", self.search_hf, primary=True)
        hf_search_btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        left_layout.addLayout(self.row(self.hf_query, hf_search_btn))
        self.hf_sort = QComboBox()
        for key, value in (
            ("sort_downloads", "downloads"),
            ("sort_likes", "likes"),
            ("sort_updated", "lastModified"),
        ):
            self.hf_sort.addItem(self.tr(key), value)
        popular_btn = self.button("popular_models", self.popular_hf)
        popular_btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        left_layout.addLayout(self.row(popular_btn, self.hf_sort))
        self.hf_results = QListWidget()
        self.hf_results.currentItemChanged.connect(self._hf_selection_changed)
        self.hf_sort.currentIndexChanged.connect(self.search_hf)
        left_layout.addWidget(self.hf_results, 1)
        download_hint = self.label("download_hint")
        download_hint.setObjectName("mutedMeta")
        download_hint.setWordWrap(True)
        left_layout.addWidget(download_hint)

        self.hf_detail = QLabel()
        self.hf_detail.setObjectName("sectionTitle")
        self.hf_detail.setWordWrap(True)
        self.hf_detail.setTextFormat(Qt.PlainText)
        right_layout.addWidget(self.hf_detail)
        self.hf_readme = ModelCardBrowser()
        self.hf_readme.setMinimumHeight(140)
        right_layout.addWidget(self.hf_readme, 1)
        right_layout.addWidget(make_divider())
        files_label = self.label("files")
        files_label.setObjectName("drawerHeading")
        right_layout.addWidget(files_label)
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
        hf_dl_bar = QHBoxLayout()
        hf_dl_bar.setContentsMargins(0, 0, 0, 0)
        hf_dl_bar.setSpacing(10)
        self.hf_file_info = QLabel()
        self.hf_file_info.setObjectName("mutedMeta")
        self.hf_file_info.setWordWrap(True)
        self.hf_files.currentIndexChanged.connect(self._hf_file_info)
        self.download_button = self.button("download_file", self.download_file, primary=True)
        self.download_button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        hf_dl_bar.addWidget(self.hf_file_info, 1)
        hf_dl_bar.addWidget(self.download_button)
        right_layout.addLayout(hf_dl_bar)

        right_scroll = QScrollArea()
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right)
        splitter.addWidget(left)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([360, 680])
        hf.addWidget(splitter, 1)

        transfers = QWidget()
        transfer_layout = QVBoxLayout(transfers)
        transfer_layout.setContentsMargins(0, 10, 0, 0)
        transfer_layout.setSpacing(12)
        transfers_card = QFrame()
        transfers_card.setObjectName("sectionGroup")
        tc_layout = QVBoxLayout(transfers_card)
        tc_layout.setContentsMargins(16, 14, 16, 14)
        tc_layout.setSpacing(10)
        self.transfers_empty = self.label("transfers_empty")
        self.transfers_empty.setObjectName("subtleHint")
        self.transfers_empty.setWordWrap(True)
        tc_layout.addWidget(self.transfers_empty)
        transfer_head = QHBoxLayout()
        transfer_head.setContentsMargins(0, 0, 0, 0)
        transfer_head.setSpacing(8)
        self.download_list = QComboBox()
        self.download_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.transfer_state_badge = QLabel()
        self.transfer_state_badge.setObjectName("statusPill")
        self.transfer_state_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.transfer_state_badge.hide()
        transfer_head.addWidget(self.download_list, 1)
        transfer_head.addWidget(self.transfer_state_badge)
        tc_layout.addLayout(transfer_head)
        self.download_progress = QProgressBar()
        self.download_progress.setMinimumHeight(8)
        self.download_progress.setValue(0)
        tc_layout.addWidget(self.download_progress)
        self.download_status = QLabel()
        self.download_status.setObjectName("mutedMeta")
        self.download_status.setWordWrap(True)
        tc_layout.addWidget(self.download_status)
        self.transfer_error_banner = QFrame()
        self.transfer_error_banner.setObjectName("errorBanner")
        self.transfer_error_banner.hide()
        err_layout = QHBoxLayout(self.transfer_error_banner)
        err_layout.setContentsMargins(10, 6, 10, 6)
        self.transfer_error_label = QLabel()
        self.transfer_error_label.setObjectName("notice")
        self.transfer_error_label.setWordWrap(True)
        err_layout.addWidget(self.transfer_error_label, 1)
        tc_layout.addWidget(self.transfer_error_banner)
        self.download_list.currentIndexChanged.connect(self._show_download_progress)
        self.cancel_download_button = self.button("cancel_download", self.cancel_download)
        self.resume_download_button = self.button("resume_download", self.resume_download)
        self.import_download_button = self.button("import_download", self.import_download)
        dl_actions = QHBoxLayout()
        dl_actions.setContentsMargins(0, 2, 0, 0)
        dl_actions.setSpacing(8)
        for button in (
            self.cancel_download_button,
            self.resume_download_button,
            self.import_download_button,
        ):
            button.hide()
            button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            dl_actions.addWidget(button)
        dl_actions.addStretch(1)
        tc_layout.addLayout(dl_actions)
        transfer_layout.addWidget(transfers_card)

        self.transfer_queue_heading = self.label("transfer_queue")
        self.transfer_queue_heading.setObjectName("drawerHeading")
        self.transfer_queue_heading.hide()
        transfer_layout.addWidget(self.transfer_queue_heading)
        self.transfers_queue = QListWidget()
        self.transfers_queue.setObjectName("sectionGroup")
        self.transfers_queue.hide()
        self.transfers_queue.currentRowChanged.connect(self._transfer_queue_selected)
        transfer_layout.addWidget(self.transfers_queue, 1)
        transfer_layout.addStretch(1)

        self.model_tabs.addTab(remote, "")
        self.model_tabs.addTab(transfers, "")
        self.pages.addWidget(page)

    def _build_settings(self):
        settings_page = QWidget()
        page_layout = QVBoxLayout(settings_page)
        self.settings_page_layout = page_layout
        page_layout.setContentsMargins(
            self._scaled(16), self._scaled(10), self._scaled(16), self._scaled(10)
        )
        page_layout.setSpacing(10)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        self.settings_scroll = scroll
        outer = QWidget()
        outer_layout = QHBoxLayout(outer)
        outer_layout.setContentsMargins(0, 8, 0, 16)
        outer_layout.addStretch(1)
        self.settings_container = QWidget()
        self.settings_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.settings_container.setMaximumWidth(850)
        outer_layout.addWidget(self.settings_container, 10)
        outer_layout.addStretch(1)
        container_layout = QVBoxLayout(self.settings_container)
        container_layout.setContentsMargins(0, 6, 0, 12)
        container_layout.setSpacing(14)

        nav_row = QHBoxLayout()
        nav_row.setContentsMargins(0, 0, 0, 4)
        nav_row.setSpacing(6)
        self.settings_nav_group = QButtonGroup(self.settings_container)
        self.settings_nav_group.setExclusive(True)
        self.settings_nav_pills = {}

        def make_section(key):
            section = QFrame()
            section.setObjectName("sectionGroup")
            sec_layout = QVBoxLayout(section)
            sec_layout.setContentsMargins(18, 14, 18, 16)
            sec_layout.setSpacing(12)
            head = self.label(key)
            head.setObjectName("drawerHeading")
            sec_layout.addWidget(head)
            sec_layout.addWidget(make_divider())
            card_form = QFormLayout()
            card_form.setContentsMargins(0, 2, 0, 0)
            card_form.setHorizontalSpacing(18)
            card_form.setVerticalSpacing(12)
            card_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
            sec_layout.addLayout(card_form)
            container_layout.addWidget(section)
            pill = QPushButton(self.tr(key))
            pill.setObjectName("sectionPill")
            pill.setCheckable(True)
            pill.setCursor(Qt.PointingHandCursor)
            self._texts.append((pill, key))
            self.settings_nav_group.addButton(pill)
            self.settings_nav_pills[key] = (pill, section)
            nav_row.addWidget(pill)
            return section, sec_layout, card_form

        def compact_row(*widgets):
            box = QHBoxLayout()
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(10)
            for w in widgets:
                box.addWidget(w)
            box.addStretch(1)
            return box

        container_layout.addLayout(nav_row)

        appearance_sec, _, appearance_form = make_section("settings_appearance")
        self.language = QComboBox()
        self.language.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.language.setMinimumContentsLength(16)
        self.language.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.language.addItem("Polski", "pl-PL")
        self.language.addItem("English", "en-US")
        self.language.setCurrentIndex(self.language.findData(self.config.locale))
        self.language.currentIndexChanged.connect(self.preview_language)
        appearance_form.addRow(self.label("language"), self.language)
        self.theme = QComboBox()
        self.theme.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.theme.setMinimumContentsLength(16)
        self.theme.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
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
        appearance_form.addRow(self.label("theme"), self.theme)
        self.ui_scale = QSpinBox()
        self.ui_scale.setRange(80, 150)
        self.ui_scale.setSingleStep(10)
        self.ui_scale.setSuffix(" %")
        self.ui_scale.setValue(self.config.ui_scale)
        self.ui_scale.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.ui_scale.valueChanged.connect(self.change_ui_scale)
        appearance_form.addRow(self.label("ui_scale"), self.ui_scale)
        self.sidebar_width.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        appearance_form.addRow(self.label("sidebar_width"), self.sidebar_width)
        self.accent_button = self.button("accent", self.choose_accent)
        appearance_form.addRow(
            compact_row(self.accent_button, self.button("accent_default", self.reset_accent))
        )

        engine_sec, engine_box, engine_form = make_section("settings_engine")
        self.device = QComboBox()
        self.device.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.device.setMinimumContentsLength(24)
        self.device.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for key in ("auto", "cpu", "cuda"):
            self.device.addItem(self.tr("mode_" + key), key)
        selected = self.config.parameters.get("device", "auto")
        if selected not in {"auto", "cpu", "cuda"}:
            self.device.addItem(selected, selected)
        self.device.setCurrentIndex(self.device.findData(selected))
        engine_form.addRow(self.label("execution_mode"), self.device)
        self.gpu_offload_mode = QComboBox()
        self.gpu_offload_mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.gpu_offload_mode.setMinimumContentsLength(20)
        self.gpu_offload_mode.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for key in ("auto", "max", "manual", "cpu"):
            self.gpu_offload_mode.addItem(self.tr("offload_" + key), key)
        offload_selected = self.config.parameters.get(
            "gpu_offload_mode",
            "cpu" if selected == "cpu" else "auto",
        )
        if self.gpu_offload_mode.findData(offload_selected) < 0:
            offload_selected = "auto"
        self.gpu_offload_mode.setCurrentIndex(self.gpu_offload_mode.findData(offload_selected))
        engine_form.addRow(self.label("gpu_offload_mode"), self.gpu_offload_mode)
        engine_callout = QFrame()
        engine_callout.setObjectName("engineCallout")
        ec_layout = QHBoxLayout(engine_callout)
        ec_layout.setContentsMargins(12, 8, 12, 8)
        self.engine_summary = self.label("detecting_engines")
        self.engine_summary.setObjectName("subtleHint")
        self.engine_summary.setWordWrap(True)
        ec_layout.addWidget(self.engine_summary, 1)
        engine_box.addWidget(engine_callout)
        self.advanced_toggle = self.button("advanced_settings", lambda: None)
        self.advanced_toggle.setCheckable(True)
        engine_box.addLayout(
            compact_row(
                self.button("detect_engines", self.refresh_diagnostics),
                self.advanced_toggle,
            )
        )

        self.advanced_settings = QFrame()
        self.advanced_settings.setObjectName("sectionGroup")
        self.advanced_toggle.toggled.connect(self.advanced_settings.setVisible)
        container_layout.addWidget(self.advanced_settings)
        self.advanced_settings.hide()
        adv_outer = QVBoxLayout(self.advanced_settings)
        adv_outer.setContentsMargins(18, 14, 18, 16)
        adv_outer.setSpacing(12)
        adv_paths_head = self.label("settings_paths")
        adv_paths_head.setObjectName("drawerHeading")
        adv_outer.addWidget(adv_paths_head)
        adv_outer.addWidget(make_divider())
        form = QFormLayout()
        form.setContentsMargins(0, 2, 0, 0)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        adv_outer.addLayout(form)
        self.roots = QListWidget()
        self.roots.setMaximumHeight(96)
        self.roots.addItems(self.config.model_roots)
        form.addRow(self.label("model_roots"), self.roots)
        form.addRow(
            compact_row(
                self.button("add_directory", self.add_directory),
                self.button("remove_directory", self.remove_directory),
            )
        )
        self.llama_path = QLineEdit(self.config.llama_server)
        form.addRow(self.label("llama_server"), self.llama_path)
        self.llama_cuda_path = QLineEdit(self.config.llama_cuda_server)
        form.addRow(self.label("llama_cuda_server"), self.llama_cuda_path)
        form.addRow(
            compact_row(
                self.button("choose_cuda", self.choose_llama_cuda),
                self.button("browse", self.choose_llama),
            )
        )
        cuda_hint = self.label("cuda_hint")
        cuda_hint.setObjectName("mutedMeta")
        cuda_hint.setWordWrap(True)
        form.addRow(cuda_hint)
        self.ollama_url = QLineEdit(self.config.ollama_url)
        form.addRow(self.label("ollama_url"), self.ollama_url)
        self.ollama_enabled = QCheckBox()
        self.ollama_enabled.setChecked(self.config.ollama_enabled)
        self._texts.append((self.ollama_enabled, "ollama_enabled"))
        form.addRow(self.ollama_enabled)
        adv_outer.addWidget(make_divider())
        gen_head = self.label("generation")
        gen_head.setObjectName("drawerHeading")
        adv_outer.addWidget(gen_head)
        gen_form = QFormLayout()
        gen_form.setContentsMargins(0, 2, 0, 0)
        gen_form.setHorizontalSpacing(18)
        gen_form.setVerticalSpacing(12)
        gen_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        adv_outer.addLayout(gen_form)
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
            box.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            gen_form.addRow(self.label(key), box)
            self.parameter_inputs[key] = box
        self.device.currentIndexChanged.connect(self.execution_mode_changed)
        self.gpu_offload_mode.currentIndexChanged.connect(self.offload_mode_changed)
        self._sync_offload_controls()
        self.thinking = QCheckBox(self.tr("thinking"))
        self.thinking.setChecked(self.config.parameters.get("thinking", False))
        self._texts.append((self.thinking, "thinking"))
        gen_form.addRow(self.thinking)
        self.system_prompt = QPlainTextEdit(self.config.parameters.get("system_prompt", ""))
        self.system_prompt.setMaximumHeight(96)
        gen_form.addRow(self.label("system_prompt"), self.system_prompt)

        about_sec, about_box, _ = make_section("settings_about")
        self.about = QLabel()
        self.about.setObjectName("mutedMeta")
        self.about.setWordWrap(True)
        self.about.setTextInteractionFlags(Qt.TextSelectableByMouse)
        about_box.addWidget(self.about)
        self.updates = UpdatePanel(self.config, self.tr, self)
        about_box.addWidget(self.updates)

        adv_pill = QPushButton(self.tr("advanced_settings"))
        adv_pill.setObjectName("sectionPill")
        adv_pill.setCheckable(True)
        adv_pill.setCursor(Qt.PointingHandCursor)
        self._texts.append((adv_pill, "advanced_settings"))
        self.settings_nav_group.addButton(adv_pill)
        nav_row.insertWidget(2, adv_pill)
        nav_row.addStretch(1)

        def scroll_to(widget):
            if widget is self.advanced_settings and not self.advanced_toggle.isChecked():
                self.advanced_toggle.setChecked(True)
            self.settings_scroll.ensureWidgetVisible(widget, 16, 16)

        for pill, sec in self.settings_nav_pills.values():
            pill.clicked.connect(lambda _c=False, target=sec: scroll_to(target))
        adv_pill.clicked.connect(lambda: scroll_to(self.advanced_settings))
        self.settings_nav_pills["settings_appearance"][0].setChecked(True)

        container_layout.addStretch(1)
        scroll.setWidget(outer)
        scroll.setMinimumWidth(0)
        page_layout.addWidget(scroll, 1)

        self.settings_save_bar = QFrame()
        self.settings_save_bar.setObjectName("modelInspector")
        self.settings_save_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.settings_save_bar.setMaximumWidth(850)
        save_layout = QHBoxLayout(self.settings_save_bar)
        save_layout.setContentsMargins(16, 10, 16, 10)
        save_layout.setSpacing(12)
        settings_hint = self.label("settings_hint")
        settings_hint.setObjectName("subtleHint")
        settings_hint.setWordWrap(True)
        save_btn = self.button("save", self.save_settings, primary=True)
        save_btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        save_layout.addWidget(settings_hint, 1)
        save_layout.addWidget(save_btn)
        save_wrap = QHBoxLayout()
        save_wrap.setContentsMargins(0, 0, 0, 6)
        save_wrap.addStretch(1)
        save_wrap.addWidget(self.settings_save_bar, 10)
        save_wrap.addStretch(1)
        page_layout.addLayout(save_wrap)

        self.pages.addWidget(settings_page)

    def _build_diagnostics(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.diagnostics_page_layout = layout
        layout.setContentsMargins(
            self._scaled(16), self._scaled(10), self._scaled(16), self._scaled(10)
        )
        layout.setSpacing(12)

        top_strip = QFrame()
        top_strip.setObjectName("toolbarStrip")
        strip_layout = QHBoxLayout(top_strip)
        strip_layout.setContentsMargins(0, 0, 0, 10)
        strip_layout.setSpacing(10)
        diag_hint = self.label("diagnostics_hint")
        diag_hint.setObjectName("subtleHint")
        diag_hint.setWordWrap(True)
        refresh_btn = self.button("refresh", self.refresh_diagnostics, primary=True)
        export_btn = self.button("export_report", self.export_report)
        refresh_btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        export_btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        strip_layout.addWidget(diag_hint, 1)
        strip_layout.addWidget(export_btn)
        strip_layout.addWidget(refresh_btn)
        layout.addWidget(top_strip)

        tiles_grid = QGridLayout()
        tiles_grid.setContentsMargins(0, 0, 0, 0)
        tiles_grid.setSpacing(10)
        self._diag_tiles = {}
        for col, (tile_id, key) in enumerate(
            (
                ("backend", "diag_health_title"),
                ("gpu", "diag_gpu_title"),
                ("cpu", "diag_cpu_title"),
                ("storage", "diag_storage_title"),
            )
        ):
            tile = QFrame()
            tile.setObjectName("metricTile")
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(14, 10, 14, 10)
            tl.setSpacing(3)
            hdr = self.label(key)
            hdr.setObjectName("metricTitle")
            val = QLabel("—")
            val.setObjectName("metricValue")
            val.setTextFormat(Qt.PlainText)
            sub = QLabel("")
            sub.setObjectName("metricSub")
            sub.setTextFormat(Qt.PlainText)
            sub.setWordWrap(True)
            tl.addWidget(hdr)
            tl.addWidget(val)
            tl.addWidget(sub)
            tl.addStretch(1)
            tiles_grid.addWidget(tile, 0, col)
            tiles_grid.setColumnStretch(col, 1)
            self._diag_tiles[tile_id] = (val, sub)
        layout.addLayout(tiles_grid)

        diag_splitter = QSplitter(Qt.Horizontal)
        diag_splitter.setHandleWidth(6)

        report_pane = QWidget()
        rep_layout = QVBoxLayout(report_pane)
        rep_layout.setContentsMargins(0, 0, 6, 0)
        rep_layout.setSpacing(6)
        diag_title = self.label("diagnostics")
        diag_title.setObjectName("drawerHeading")
        rep_layout.addWidget(diag_title)
        self.diagnostic_text = QPlainTextEdit()
        self.diagnostic_text.setReadOnly(True)
        rep_layout.addWidget(self.diagnostic_text, 1)

        logs_pane = QWidget()
        logs_layout = QVBoxLayout(logs_pane)
        logs_layout.setContentsMargins(6, 0, 0, 0)
        logs_layout.setSpacing(6)
        events_title = self.label("events")
        events_title.setObjectName("drawerHeading")
        logs_layout.addWidget(events_title)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.document().setMaximumBlockCount(250)
        logs_layout.addWidget(self.logs, 1)

        diag_splitter.addWidget(report_pane)
        diag_splitter.addWidget(logs_pane)
        diag_splitter.setStretchFactor(0, 11)
        diag_splitter.setStretchFactor(1, 9)
        layout.addWidget(diag_splitter, 1)
        self.pages.addWidget(page)

    def focus_history_search(self):
        if self.config.sidebar_compact:
            self.toggle_sidebar()
        self.open_history_search()

    def open_history_search(self):
        if self.config.sidebar_compact:
            self.toggle_sidebar()
        self._history_search_open = True
        self._apply_sidebar()
        self.history_search.setFocus()
        self.history_search.selectAll()

    def close_history_search(self):
        self._history_search_open = False
        self._apply_sidebar()
        if self.history_search.text():
            self.history_search.blockSignals(True)
            self.history_search.clear()
            self.history_search.blockSignals(False)
            self.search_timer.stop()
            self.refresh_conversations()

    def eventFilter(self, watched, event):
        if watched is getattr(self, "sidebar", None) and event.type() == QEvent.Resize:
            self._sync_history_toolbar()
            self._sync_sidebar_nav_labels()
        elif (
            watched is getattr(self, "history_search", None)
            and event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress)
            and event.key() == Qt.Key_Escape
        ):
            if event.type() == QEvent.ShortcutOverride:
                event.accept()
                return True
            self.close_history_search()
            return True
        return super().eventFilter(watched, event)

    def _set_composer_focused(self, focused: bool):
        if hasattr(self, "composer_box"):
            polish_property(self.composer_box, "focused", bool(focused))

    def _set_mode_from_pill(self, mode_key: str):
        idx = self.agent_panel.mode.findData(mode_key)
        if idx >= 0 and self.agent_panel.mode.currentIndex() != idx:
            self.agent_panel.mode.setCurrentIndex(idx)

    def _sync_agent_banner(self):
        if not hasattr(self, "agent_inline_banner"):
            return
        agent_mode = self.agent_panel.mode.currentData() == "agent"
        drawer_open = hasattr(self, "context_button") and self.context_button.isChecked()
        has_active = bool(self.agent_panel.active)
        has_retry = not self.agent_panel.retry_button.isHidden()
        status_txt = self.agent_panel.status.text().strip()
        show = agent_mode and not drawer_open and (has_active or has_retry or bool(status_txt))
        self.agent_inline_banner.setVisible(show)
        self.agent_banner_retry_btn.setText(self.agent_panel.retry_button.text())
        self.agent_banner_retry_btn.setVisible(show and has_retry)
        if show:
            self.agent_banner_label.setText(status_txt or self.tr("agent_running_banner"))

    def _on_drawer_toggled(self, checked: bool):
        self.config.drawer_open = bool(checked)
        try:
            self.config.save()
        except OSError:
            pass

    def _sync_mode_settings(self):
        agent_mode = self.agent_panel.mode.currentData() == "agent"
        if hasattr(self, "mode_chat_btn") and hasattr(self, "mode_agent_btn"):
            self.mode_chat_btn.blockSignals(True)
            self.mode_agent_btn.blockSignals(True)
            self.mode_chat_btn.setChecked(not agent_mode)
            self.mode_agent_btn.setChecked(agent_mode)
            self.mode_chat_btn.blockSignals(False)
            self.mode_agent_btn.blockSignals(False)
        open_settings = self.context_button.isChecked()
        if hasattr(self, "chat_drawer"):
            self.chat_drawer.setVisible(open_settings)
        self.context_controls.setVisible(open_settings)
        if self.context_controls.layout():
            self.context_controls.layout().activate()
        self.agent_panel.settings_toggle.blockSignals(True)
        self.agent_panel.settings_toggle.setChecked(open_settings and agent_mode)
        self.agent_panel.settings_toggle.blockSignals(False)
        self.agent_panel.visibility()
        if self.agent_panel.layout():
            self.agent_panel.layout().activate()
        self._sync_agent_banner()
        self._sync_responsive_chat_layout()
        if (
            getattr(self, "pages", None)
            and self.pages.currentWidget()
            and self.pages.currentWidget().layout()
        ):
            self.pages.currentWidget().layout().activate()
        self._render_resource_widgets()
        self._render_model_gpu()
        self._sync_model_combo_width()
        tip = (
            self.agent_panel.settings_toggle.text() if agent_mode else self.tr("context_configure")
        )
        self.context_button.setToolTip(tip)
        self.context_button.setAccessibleName(tip)

    def sidebar_dragged(self, position, index):
        if self.config.sidebar_compact:
            return
        self.config.sidebar_width = max(200, min(360, self.sidebar.width()))
        self._sync_history_toolbar()
        self._sync_sidebar_nav_labels()
        self._sync_responsive_chat_layout()
        self.sidebar_width.blockSignals(True)
        self.sidebar_width.setValue(self.config.sidebar_width)
        self.sidebar_width.blockSignals(False)
        self.width_save_timer.start()

    def resize_sidebar(self, width):
        self.config.sidebar_width = width
        self._apply_sidebar()
        self.config.save()
        self.width_save_timer.start()

    def toggle_sidebar(self):
        self.config.sidebar_compact = not self.config.sidebar_compact
        self._apply_sidebar()
        self.config.save()

    def _scaled(self, value: int) -> int:
        return max(1, round(value * self.config.ui_scale / 100))

    def _sync_chat_icons(self):
        if not hasattr(self, "context_button"):
            return
        fg, accent, accent_text = self._theme_colors
        icon_px = self._scaled(16)
        ctx_color = accent if self.context_button.isChecked() else fg
        self.context_button.setIcon(app_icon("sliders", ctx_color, icon_px))
        self.context_button.setIconSize(QSize(icon_px, icon_px))
        self.chat_refresh.setIcon(app_icon("refresh", fg, icon_px))
        self.chat_refresh.setIconSize(QSize(icon_px, icon_px))
        if hasattr(self, "drawer_close_btn"):
            close_px = self._scaled(14)
            self.drawer_close_btn.setIcon(app_icon("close", fg, close_px))
            self.drawer_close_btn.setIconSize(QSize(close_px, close_px))
        if hasattr(self, "send_button"):
            btn_icon = self._scaled(16)
            self.send_button.setText("")
            self.send_button.setIcon(app_icon("send", accent_text, btn_icon))
            self.send_button.setIconSize(QSize(btn_icon, btn_icon))
        if hasattr(self, "stop_button"):
            danger = self._tokens.danger if hasattr(self, "_tokens") else "#f07078"
            btn_icon = self._scaled(15)
            self.stop_button.setText("")
            self.stop_button.setIcon(app_icon("stop", danger, btn_icon))
            self.stop_button.setIconSize(QSize(btn_icon, btn_icon))
        if hasattr(self, "model_actions"):
            menu_icon = self._scaled(15)
            self.model_actions.setIcon(app_icon("menu", fg, menu_icon))
            self.model_actions.setIconSize(QSize(menu_icon, menu_icon))

    def _apply_scaled_metrics(self):
        icon_btn = self._scaled(32)
        for widget in (
            self.context_button,
            self.chat_refresh,
        ):
            widget.setFixedSize(icon_btn, icon_btn)
        if hasattr(self, "drawer_close_btn"):
            self.drawer_close_btn.setFixedSize(self._scaled(28), self._scaled(28))
        mode_fm = (
            self.mode_chat_btn.fontMetrics()
            if hasattr(self, "mode_chat_btn")
            else self.agent_panel.mode.fontMetrics()
        )
        widest_mode = max(
            (
                mode_fm.horizontalAdvance(self.agent_panel.mode.itemText(i))
                for i in range(self.agent_panel.mode.count())
            ),
            default=0,
        )
        if hasattr(self, "mode_chat_btn") and hasattr(self, "mode_agent_btn"):
            from PySide6.QtGui import QFontMetrics

            bold_font = self.mode_agent_btn.font()
            bold_font.setBold(True)
            bold_fm = QFontMetrics(bold_font)
            widest_bold = max(
                (
                    bold_fm.horizontalAdvance(self.agent_panel.mode.itemText(i))
                    for i in range(self.agent_panel.mode.count())
                ),
                default=0,
            )
            seg_w = max(self._scaled(58), widest_bold + self._scaled(26))
            seg_h = self._scaled(26)
            for seg in (self.mode_chat_btn, self.mode_agent_btn):
                seg.setFixedSize(seg_w, seg_h)
            self.mode_switch.setFixedHeight(self._scaled(32))
        mode_w = max(self._scaled(124), widest_mode + self._scaled(64))
        self.agent_panel.mode.setFixedWidth(mode_w)
        self.agent_panel.mode.setFixedHeight(self._scaled(32))
        self.model_combo.setFixedHeight(self._scaled(32))
        scale = self.config.ui_scale / 100
        send_sz = max(24, round(17 * scale) * 2)
        self.send_button.setFixedSize(send_sz, send_sz)
        self.stop_button.setFixedSize(send_sz, send_sz)
        self.model_actions.setFixedSize(self._scaled(32), self._scaled(32))
        self.onboarding.setMaximumWidth(self._scaled(540))
        self.settings_container.setMaximumWidth(self._scaled(850))
        if hasattr(self, "settings_save_bar"):
            self.settings_save_bar.setMaximumWidth(self._scaled(850))
        self.context_meter.setMaximumWidth(self._scaled(90))
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)
        self.topbar_layout.setContentsMargins(
            self._scaled(16), self._scaled(10), self._scaled(16), self._scaled(10)
        )
        self.alerts_layout.setContentsMargins(self._scaled(16), 0, self._scaled(16), 0)
        self.alerts_layout.setSpacing(self._scaled(8))
        if hasattr(self, "chat_pane_layout"):
            self.chat_pane_layout.setContentsMargins(
                self._scaled(16), self._scaled(8), self._scaled(16), self._scaled(10)
            )
            self.chat_pane_layout.setSpacing(self._scaled(8))
        for page_layout in (
            getattr(self, "models_page_layout", None),
            getattr(self, "settings_page_layout", None),
            getattr(self, "diagnostics_page_layout", None),
        ):
            if page_layout is not None:
                page_layout.setContentsMargins(
                    self._scaled(16), self._scaled(10), self._scaled(16), self._scaled(10)
                )
        self._sync_responsive_chat_layout()
        self._render_resource_widgets()
        self._render_model_gpu()
        self._sync_chat_icons()

    def _sync_responsive_chat_layout(self):
        scale = self.config.ui_scale / 100
        compact_w = self._scaled(56)
        expanded_w = min(360, max(200, getattr(self.config, "sidebar_width", 240)))
        sidebar_w = compact_w if self.config.sidebar_compact else expanded_w
        avail = max(320, self.width() - sidebar_w - 1)
        if hasattr(self, "chat_drawer"):
            base_drawer = min(376, max(296, round(324 * min(1.16, scale))))
            drawer_w = min(base_drawer, max(236, int(avail * 0.42)))
            self.chat_drawer.setFixedWidth(drawer_w)
        col_max = self._scaled(980)
        if hasattr(self, "composer_wrap"):
            self.composer_wrap.setMaximumWidth(min(col_max, self._scaled(964)))
        if getattr(self, "transcript", None) and self.transcript.widget():
            self.transcript.widget().setMaximumWidth(col_max)
        self._sync_model_combo_width()

    def _topbar_pane_width(self) -> int:
        compact_w = self._scaled(56)
        expanded_w = min(360, max(200, getattr(self.config, "sidebar_width", 240)))
        sidebar_w = compact_w if self.config.sidebar_compact else expanded_w
        drawer_w = 0
        if hasattr(self, "chat_drawer") and not self.chat_drawer.isHidden():
            drawer_w = self.chat_drawer.minimumWidth() or self.chat_drawer.width()
        return max(self._scaled(260), self.width() - sidebar_w - drawer_w - self._scaled(16))

    def _sync_model_combo_width(self):
        if not hasattr(self, "model_combo"):
            return
        fm = self.model_combo.fontMetrics()
        widest_item = max(
            (
                fm.horizontalAdvance(self.model_combo.itemText(i))
                for i in range(self.model_combo.count())
            ),
            default=0,
        )
        needed = widest_item + self._scaled(64) if widest_item > 0 else self._scaled(220)
        pane_w = self._topbar_pane_width()
        min_w = min(self._scaled(110), max(84, pane_w // 4))
        pane_cap = (
            self._scaled(520) if pane_w >= self._scaled(680) else max(min_w, int(pane_w * 0.48))
        )
        max_w = max(min_w, min(self._scaled(520), needed, pane_cap))
        self.model_combo.setMinimumWidth(min_w)
        self.model_combo.setMaximumWidth(max_w)

    def _sync_model_combo_tooltip(self):
        if hasattr(self, "model_combo"):
            tip = (
                self.model_combo.currentData(Qt.ToolTipRole) or self.model_combo.currentText() or ""
            )
            self.model_combo.setToolTip(tip)

    def _sidebar_metrics(self) -> tuple[int, int]:
        """Return (margin_h, row_gap) for the expanded sidebar."""
        expanded_w = max(200, min(360, self.config.sidebar_width))
        if self.config.ui_scale > 100 and expanded_w < self._scaled(220):
            return max(6, self._scaled(7)), max(4, self._scaled(4))
        return self._scaled(10), self._scaled(6)

    def _sync_history_toolbar(self):
        if self.config.sidebar_compact or not hasattr(self, "history_search_toggle"):
            return
        margin_h, row_gap = self._sidebar_metrics()
        header_btn = self._scaled(32)
        header_icon = self._scaled(15)
        cfg_w = max(200, min(360, self.config.sidebar_width))
        actual_w = self.sidebar.width()
        sidebar_w = min(cfg_w, actual_w) if actual_w >= 180 else cfg_w
        toolbar_avail = max(header_btn, sidebar_w - 2 * margin_h - header_btn - row_gap - 6)
        btn = self.history_search_toggle
        btn.setMinimumSize(header_btn, header_btn)
        btn.setMaximumSize(16777215, header_btn)
        btn.setFixedHeight(header_btn)
        label = self.tr("search_short")
        btn.setText(label)
        btn.ensurePolished()
        fm_need = header_icon + self._scaled(28) + btn.fontMetrics().horizontalAdvance(label)
        if max(btn.minimumSizeHint().width(), fm_need) > toolbar_avail:
            btn.setText("")

    def _sync_sidebar_nav_labels(self):
        if self.config.sidebar_compact or not hasattr(self, "nav"):
            return
        margin_h, row_gap = self._sidebar_metrics()
        cfg_w = max(200, min(360, self.config.sidebar_width))
        actual_w = self.sidebar.width()
        effective_w = min(cfg_w, actual_w) if actual_w >= 180 else cfg_w
        avail_new = effective_w - 2 * margin_h - self._scaled(32) - row_gap - 1
        full_new = self.tr("new_chat")
        self.new_button.setText(full_new)
        self.new_button.ensurePolished()
        if self.new_button.minimumSizeHint().width() > avail_new:
            chrome = max(
                self._scaled(28),
                self.new_button.minimumSizeHint().width()
                - self.new_button.fontMetrics().horizontalAdvance(full_new),
            )
            self.new_button.setText(
                self.new_button.fontMetrics().elidedText(
                    full_new, Qt.ElideRight, max(24, avail_new - chrome)
                )
            )
        self.nav[0].setText("")
        max_text_w = max(48, effective_w - self._scaled(76))
        for button, key in zip(
            (self.nav[1], self.nav[2], self.nav[3]),
            ("models", "settings", "diagnostics"),
            strict=True,
        ):
            button.ensurePolished()
            button.setText(sidebar_text(self.tr(key), button.fontMetrics(), max_text_w))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_responsive_chat_layout()
        self._render_resource_widgets()
        if hasattr(self, "chat_gpu_pill"):
            self._render_model_gpu()
        self._sync_history_toolbar()

    def _sync_backend_pid(self):
        proc = getattr(self.session, "process", None)
        pid = 0
        if proc is not None:
            try:
                pid = int(proc.processId() or 0)
            except Exception:
                pid = 0
        self._backend_pid = pid if pid > 0 else None

    def _resource_root_pids(self) -> list[int]:
        pids = [os.getpid()]
        backend_pid = self._backend_pid
        if isinstance(backend_pid, int) and backend_pid > 0:
            pids.append(backend_pid)
        return pids

    def _render_resource_widgets(self, snapshot: ResourceSnapshot | None = None):
        snap = snapshot if snapshot is not None else self.resource_monitor.latest
        full_summary = format_resource_summary(snap, self.tr)
        if hasattr(self, "resource_monitor_btn"):
            pane_w = self._topbar_pane_width()
            if pane_w < self._scaled(500) and " · " in full_summary:
                vram_parts = [p for p in full_summary.split(" · ") if "VRAM" in p]
                ram_parts = [p for p in full_summary.split(" · ") if "RAM" in p]
                display = (vram_parts or ram_parts or [full_summary])[0]
            elif pane_w < self._scaled(820) and " · " in full_summary:
                parts = [p for p in full_summary.split(" · ") if "RAM" in p]
                display = " · ".join(parts[:2]) if parts else full_summary
            else:
                display = full_summary
            self.resource_monitor_btn.setText(display)
            self.resource_monitor_btn.setToolTip(full_summary + "\n" + self.tr("resources_tooltip"))
            self.resource_monitor_btn.setAccessibleName(self.tr("resources_label"))
            self.resource_monitor_btn.adjustSize()
            self.resource_monitor_btn.updateGeometry()
            if hasattr(self, "topbar") and self.topbar.layout():
                self.topbar.layout().activate()
        if hasattr(self, "resource_details_label"):
            self.resource_details_label.setText(format_resource_details(snap, self.tr))

    def _apply_resource_snapshot(self, snapshot):
        if self._closing or not isinstance(snapshot, ResourceSnapshot):
            return
        self._render_resource_widgets(snapshot)
        if hasattr(self, "chat_gpu_status") and getattr(self, "context_controls", None):
            if self.context_controls.isVisible() and not self._gpu_dirty:
                self._render_model_gpu()

    def _format_notice_details(
        self, code: str, *, component: str | None = None, target: str | None = None
    ) -> str:
        info = describe_error(code, self.tr, component=component, target=target)
        return "\n".join(
            [
                f"{self.tr('error_code_label')}: {info['code']}",
                f"{self.tr('error_component_label')}: {info['component']}",
                f"{self.tr('error_cause_label')}: {info['cause']}",
                f"{self.tr('error_solution_label')}: {info['solution']}",
            ]
        )

    def _dismiss_notice(self):
        self._last_error_meta = None
        self.notice_action_button.hide()
        self.notice_details_toggle.setChecked(False)
        self.notice_details_toggle.hide()
        self.notice_details_frame.hide()
        self.notice.hide()
        self.notice_card.hide()

    def _apply_sidebar(self):
        compact = self.config.sidebar_compact
        compact_width = self._scaled(56)
        btn_size = self._scaled(36)
        icon_px = self._scaled(18 if compact else 15)
        fg, accent, accent_text = self._theme_colors
        expanded_margin_h, row_gap = self._sidebar_metrics()
        margin_h = max(4, (compact_width - 1 - btn_size) // 2) if compact else expanded_margin_h
        margin_v = self._scaled(10 if compact else 12)
        self.side_layout.setContentsMargins(margin_h, margin_v, margin_h, margin_v)
        self.side_layout.setSpacing(row_gap if not compact else self._scaled(6))
        self.sidebar.setProperty("compact", compact)
        self.sidebar.style().unpolish(self.sidebar)
        self.sidebar.style().polish(self.sidebar)
        self.sidebar_header.setContentsMargins(
            0 if compact else self._scaled(2), 0, 0, self._scaled(4)
        )
        self.sidebar_header.setSpacing(0 if compact else row_gap)
        self.side_layout.setAlignment(
            self.sidebar_header, Qt.AlignHCenter if compact else Qt.Alignment()
        )
        brand_px = self._scaled(16)
        self.brand_mark.setPixmap(app_icon("brand", accent, brand_px).pixmap(brand_px, brand_px))
        self.brand_mark.setVisible(not compact)
        self.brand.setVisible(not compact)

        toggle_size = btn_size if compact else self._scaled(26)
        toggle_icon = self._scaled(19 if compact else 14)
        header_btn = self._scaled(32)
        header_icon = self._scaled(15)
        self.top_actions_grid.setSpacing(row_gap)
        self.history_toolbar.setSpacing(row_gap)
        self.history_toolbar.setContentsMargins(0, 0, 0, self._scaled(4))
        self.history_search_toggle.setIcon(app_icon("search", fg, header_icon))
        self.history_search_toggle.setIconSize(QSize(header_icon, header_icon))
        self.history_menu_btn.setFixedSize(header_btn, header_btn)
        self.history_menu_btn.setText("")
        self.history_menu_btn.setIcon(app_icon("menu", fg, header_icon))
        self.history_menu_btn.setIconSize(QSize(header_icon, header_icon))
        self.history_search_close.setFixedSize(header_btn, header_btn)
        self.history_search_close.setText("")
        self.history_search_close.setIcon(app_icon("close", fg, header_icon))
        self.history_search_close.setIconSize(QSize(header_icon, header_icon))
        self.history_search.setFixedHeight(header_btn)
        self._sync_history_toolbar()
        search_open = not compact and self._history_search_open
        self.history_search_toggle.setVisible(not compact and not search_open)
        self.history_menu_btn.setVisible(not compact and not search_open)
        self.history_search.setVisible(search_open)
        self.history_search_close.setVisible(search_open)
        self.sidebar_toggle.setFixedSize(toggle_size, toggle_size)
        self.sidebar_toggle.setStyleSheet("")
        self.sidebar_toggle.setText("")
        self.sidebar_toggle.setIcon(app_icon("expand" if compact else "collapse", fg, toggle_icon))
        self.sidebar_toggle.setIconSize(QSize(toggle_icon, toggle_icon))
        self._sync_model_combo_width()
        self.sidebar.setSizePolicy(
            QSizePolicy.Fixed if compact else QSizePolicy.Preferred, QSizePolicy.Expanding
        )
        self.sidebar.setMinimumWidth(compact_width if compact else 200)
        self.sidebar.setMaximumWidth(compact_width if compact else 360)
        if self.shell.count() > 1:
            handle_w = 1
            self.shell.setHandleWidth(handle_w)
            width = compact_width if compact else max(200, min(360, self.config.sidebar_width))
            self.shell.setSizes([width, max(1, self.width() - width - handle_w)])
            self.shell.handle(1).setEnabled(not compact)
        self.sidebar_toggle.setToolTip(self.tr("sidebar_expand" if compact else "sidebar_collapse"))
        self.sidebar_width.setToolTip(self.tr("sidebar_width"))
        self.history_search_toggle.setToolTip(self.tr("search_history"))
        self.history_search_toggle.setAccessibleName(self.tr("search_history"))
        self.history_search_close.setToolTip(self.tr("cancel"))
        self.history_search_close.setAccessibleName(self.tr("cancel"))
        self.history_menu_btn.setToolTip(self.tr("history_menu"))
        self.history_menu_btn.setAccessibleName(self.tr("history_menu"))
        self.history_panel.setVisible(not compact)
        self.nav_footer_divider.setVisible(not compact)
        self.compact_spacer.setVisible(compact)
        self.top_actions_grid.removeWidget(self.new_button)
        self.top_actions_grid.removeWidget(self.nav[0])
        if compact:
            self.new_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.top_actions_grid.addWidget(self.new_button, 0, 0, Qt.AlignHCenter)
            self.top_actions_grid.addWidget(self.nav[0], 1, 0, Qt.AlignHCenter)
            self.top_actions_grid.setColumnStretch(0, 1)
            self.top_actions_grid.setColumnStretch(1, 0)
        else:
            self.new_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.top_actions_grid.addWidget(self.new_button, 0, 0)
            self.top_actions_grid.addWidget(self.nav[0], 0, 1)
            self.top_actions_grid.setAlignment(self.new_button, Qt.Alignment())
            self.top_actions_grid.setAlignment(self.nav[0], Qt.Alignment())
            self.top_actions_grid.setColumnStretch(0, 1)
            self.top_actions_grid.setColumnStretch(1, 0)
        for button, key in zip(
            (self.new_button, *self.nav),
            ("new_chat", "conversations_nav", "models", "settings", "diagnostics"),
            strict=True,
        ):
            icon_color = accent_text if key == "new_chat" else accent if button.isChecked() else fg
            button.setIcon(app_icon(key, icon_color, icon_px))
            button.setIconSize(QSize(icon_px, icon_px))
            button.setToolTip(self.tr(key))
            button.setAccessibleName(self.tr(key))
            if compact:
                if button is self.nav[0]:
                    polish_property(button, "iconOnly", True)
                button.setFixedSize(btn_size, btn_size)
                button.setStyleSheet("")
                button.setText("")
                if button in (self.nav[1], self.nav[2], self.nav[3]):
                    self.side_layout.setAlignment(button, Qt.AlignHCenter)
            else:
                if button is self.nav[0]:
                    polish_property(button, "iconOnly", True)
                    nav_sz = self._scaled(32)
                    button.setFixedSize(nav_sz, nav_sz)
                    button.setText("")
                else:
                    polish_property(button, "iconOnly", False)
                    button.setMinimumSize(0, 0)
                    button.setMaximumSize(16777215, 16777215)
                button.setStyleSheet("")
                if button in (self.nav[1], self.nav[2], self.nav[3]):
                    self.side_layout.setAlignment(button, Qt.Alignment())
        self._sync_sidebar_nav_labels()
        self._sync_responsive_chat_layout()

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        is_chat = index == 0
        self.chat_header_widget.setVisible(is_chat)
        self.page_title.setVisible(not is_chat)
        self.context_button.setVisible(is_chat)
        self.page_title.setText(self.tr(("chat", "models", "settings", "diagnostics")[index]))
        for i, button in enumerate(self.nav):
            button.setChecked(i == index)
        self._apply_sidebar()
        self._render_model_gpu()
        if index == 3:
            self.refresh_diagnostics()

    def retranslate(self):
        self.agent_panel.retranslate()
        for widget, key in self._texts:
            widget.setText(self.tr(key))
        self.page_title.setText(
            self.tr(("chat", "models", "settings", "diagnostics")[self.pages.currentIndex()])
        )
        if hasattr(self, "mode_chat_btn"):
            self.mode_chat_btn.setText(self.tr("agent_chat"))
            self.mode_agent_btn.setText(self.tr("agent_mode"))
        if hasattr(self, "drawer_title"):
            self.drawer_title.setText(self.tr("drawer_title"))
            self.drawer_close_btn.setToolTip(self.tr("close_notice"))
            self.drawer_close_btn.setAccessibleName(self.tr("close_notice"))
        if hasattr(self, "composer_hint"):
            self.composer_hint.setText(self.tr("composer_hint"))
        if hasattr(self, "agent_banner_open_btn"):
            self.agent_banner_open_btn.setText(self.tr("drawer_title"))
            self.agent_banner_retry_btn.setText(self.tr("agent_retry"))
        self.send_button.setToolTip(self.tr("send"))
        self.send_button.setAccessibleName(self.tr("send"))
        self.stop_button.setToolTip(self.tr("stop"))
        self.stop_button.setAccessibleName(self.tr("stop"))
        self.transcript.sync_empty_state(
            self.tr, self._theme_colors[1] if hasattr(self, "_theme_colors") else None
        )
        self._apply_sidebar()
        self._update_chat_title()
        self.composer.setPlaceholderText(self.tr("composer"))
        self.history_search.setPlaceholderText(self.tr("search_history"))
        self.context_mode.setItemText(0, self.tr("context_auto"))
        self.context_mode.setItemText(1, self.tr("context_manual"))
        if hasattr(self, "context_preset"):
            self._populate_context_presets(self.context_tokens.maximum())
        if hasattr(self, "chat_gpu_mode"):
            for index, key in enumerate(("auto", "max", "manual", "cpu")):
                self.chat_gpu_mode.setItemText(index, self.tr("offload_" + key))
            self.chat_gpu_mode.setAccessibleName(self.tr("gpu_offload_mode"))
            self.chat_gpu_layers.setAccessibleName(self.tr("gpu_layers"))
        self._render_model_context()
        self._sync_last_request_context()
        self.model_actions.setToolTip(self.tr("model_actions"))
        self.model_actions.setAccessibleName(self.tr("model_actions"))
        self.model_unload_action.setText(self.tr("unload"))
        self.model_remove_action.setText(self.tr("remove_entry"))
        self.context_button.setToolTip(self.tr("context_configure"))
        self.context_button.setAccessibleName(self.tr("context_configure"))
        self._sync_mode_settings()
        self.chat_refresh.setToolTip(self.tr("refresh"))
        self.chat_refresh.setAccessibleName(self.tr("refresh"))
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
        for index, key in enumerate(("auto", "max", "manual", "cpu")):
            self.gpu_offload_mode.setItemText(index, self.tr("offload_" + key))
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
        self.updates.retranslate(self.tr)
        self._render_resource_widgets()
        self.notice_details_toggle.setText(self.tr("error_details_toggle"))
        self.notice_close.setToolTip(self.tr("close_notice"))
        if self._last_error_meta is not None and self.notice_card.isVisible():
            safe_code, component, target = self._last_error_meta
            self.notice.setText(
                self.tr.catalog.get(safe_code) or self.tr("operation_error", code=safe_code)
            )
            self.notice_details_label.setText(
                self._format_notice_details(safe_code, component=component, target=target)
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
        self._apply_sidebar()
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
        from PySide6.QtGui import QPalette

        system_dark = (
            self.config.theme == "system"
            and QApplication.instance().styleHints().colorScheme() == Qt.ColorScheme.Dark
        )
        t = resolve_theme_tokens(self.config.theme, system_dark, self.config.accent)
        arrows = {
            "down": ensure_arrow_icon("down", t.fg),
            "down_muted": ensure_arrow_icon("down", t.muted),
            "up": ensure_arrow_icon("up", t.fg),
            "up_muted": ensure_arrow_icon("up", t.muted),
        }
        qt_palette = QPalette()
        for role, hex_color in (
            (QPalette.Window, t.bg),
            (QPalette.WindowText, t.fg),
            (QPalette.Base, t.panel),
            (QPalette.AlternateBase, t.field),
            (QPalette.Text, t.fg),
            (QPalette.Button, t.field),
            (QPalette.ButtonText, t.fg),
            (QPalette.Highlight, t.field),
            (QPalette.HighlightedText, t.accent),
            (QPalette.ToolTipBase, t.elevated),
            (QPalette.ToolTipText, t.fg),
            (QPalette.PlaceholderText, t.muted),
        ):
            qt_palette.setColor(role, QColor(hex_color))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            qt_palette.setColor(QPalette.Disabled, role, QColor(t.muted))
        QApplication.instance().setPalette(qt_palette)
        # Only logical font/control sizes: Qt applies the screen DPR once. Never multiply by
        # devicePixelRatio or modify QT_SCALE_FACTOR / the platform's DPI policy.
        scale = self.config.ui_scale / 100
        stylesheet = build_stylesheet(t, arrows, scale)
        prev_dark = getattr(self, "_theme_dark", None)
        self._theme_dark = t.dark
        self._tokens = t
        self._theme_colors = (t.fg, t.accent, t.accent_text)
        self.setStyleSheet(stylesheet)
        self._apply_scaled_metrics()
        self._apply_sidebar()
        if getattr(self, "transcript", None):
            self.transcript.sync_empty_state(self.tr, t.accent)
        if prev_dark is not None and prev_dark != t.dark and getattr(self, "transcript", None):
            self.transcript.locale = None
            self.render_messages()
        if self.conversations:
            self._fill_conversations()
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
        self.reconnect_button.hide()
        self.connection.setText(self.tr("connected"))
        polish_property(self.connection, "tone", "ok")
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
        if self._pending_authorize_dir:
            auth_dir, self._pending_authorize_dir = self._pending_authorize_dir, None
            self._pending_authorize_model_id = None
            self._pending_authorize_target = None
            self.notify(self.tr("model_directory_authorized", path=auth_dir))
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
        self._last_error_meta = None
        self.notice_action_button.hide()
        self.notice_card.setProperty("kind", "info")
        self.notice_card.style().unpolish(self.notice_card)
        self.notice_card.style().polish(self.notice_card)
        self.notice.setText(text)
        self.notice.show()
        self.notice_details_toggle.setChecked(False)
        self.notice_details_toggle.hide()
        self.notice_details_frame.hide()
        self.notice_card.show()
        self.statusBar().showMessage(text, 10000)

    def notify_error_card(
        self, text: str, code: str, *, component: str | None = None, target: str | None = None
    ):
        self._last_error_meta = (code, component, target)
        self.notice_card.setProperty("kind", "error")
        self.notice_card.style().unpolish(self.notice_card)
        self.notice_card.style().polish(self.notice_card)
        self.notice.setText(text)
        self.notice.show()
        if code in {"model_directory_unauthorized", "path_not_allowed"} and self.session.owned:
            self.notice_action_button.setText(self.tr("authorize_model_directory"))
            self.notice_action_button.show()
        else:
            self.notice_action_button.hide()
        self.notice_details_label.setText(
            self._format_notice_details(code, component=component, target=target)
        )
        self.notice_details_toggle.setText(self.tr("error_details_toggle"))
        self.notice_details_toggle.setChecked(False)
        self.notice_details_toggle.show()
        self.notice_details_frame.hide()
        self.notice_card.show()
        self.statusBar().showMessage(text, 10000)

    def show_error(self, code, *, component: str | None = None, target: str | None = None):
        safe_code = code if code in self.tr.catalog else "unknown_error"
        self.log_event(safe_code)
        if safe_code in {"model_directory_unauthorized", "path_not_allowed"}:
            rec = self._selected_chat_model() or self.selected_model()
            if isinstance(rec, dict) and not self._is_model_record_authorized(rec):
                self._pending_authorize_model_id = rec.get("id")
                self._pending_authorize_target = rec.get("location")
                if target is None:
                    target = rec.get("location")
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
            polish_property(self.connection, "tone", "error")
            self.reconnect_button.show()
        text = self.tr.catalog.get(safe_code) or self.tr("operation_error", code=safe_code)
        self.notify_error_card(text, safe_code, component=component, target=target)

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

    def _build_history_title_row(self, title: str, selected: bool, elide_width: int) -> QWidget:
        title_row = QWidget(self.conversation_list)
        title_row.setObjectName("historyTitleRow")
        title_row.setProperty("selected", selected)
        title_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        box = QVBoxLayout(title_row)
        box.setContentsMargins(0, self._scaled(1), 0, self._scaled(1))
        box.setSpacing(0)
        label = QLabel()
        label.setObjectName("historyItemTitle")
        label.setProperty("selected", selected)
        label.setContentsMargins(self._scaled(8), self._scaled(5), self._scaled(8), self._scaled(5))
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(False)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        label.ensurePolished()
        label.setText(label.fontMetrics().elidedText(title, Qt.ElideRight, elide_width))
        label_h = max(
            label.minimumSizeHint().height(),
            label.sizeHint().height(),
            label.fontMetrics().height() + self._scaled(12),
        )
        label.setFixedHeight(label_h)
        box.addWidget(label)
        title_row.ensurePolished()
        box.activate()
        title_row.setFixedHeight(
            max(title_row.minimumSizeHint().height(), title_row.sizeHint().height())
        )
        return title_row

    def _fill_conversations(self, select=None):
        current = select or self.current_id
        self.conversation_list.blockSignals(True)
        self.conversation_list.setUpdatesEnabled(False)
        self.conversation_list.clear()
        viewport_w = self.conversation_list.viewport().width()
        avail_w = (
            viewport_w if viewport_w > 60 else max(60, self.config.sidebar_width - self._scaled(24))
        )
        elide_width = max(60, avail_w - self._scaled(24))
        heading_width = max(48, avail_w - self._scaled(8))
        for group, records in grouped_history(self.conversations).items():
            for index, record in enumerate(records):
                title = record["title"] or self.tr("untitled")
                selected = record["id"] == current
                item = QListWidgetItem(title)
                item.setData(Qt.UserRole, record["id"])
                item.setToolTip(escape(title))
                self.conversation_list.addItem(item)
                if index == 0:
                    row = QWidget(self.conversation_list)
                    row.setObjectName("historyGroupRow")
                    row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                    column = QVBoxLayout(row)
                    column.setContentsMargins(0, self._scaled(4), 0, self._scaled(1))
                    column.setSpacing(self._scaled(2))
                    collapsed = group in self.config.collapsed_history
                    heading = QPushButton(
                        ("▸ " if collapsed else "▾ ") + self.tr("history_" + group)
                    )
                    heading.setObjectName("historyHeading")
                    heading.setAccessibleName(self.tr("history_" + group))
                    heading.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                    heading.clicked.connect(
                        lambda checked=False, key=group: self.toggle_history_group(key)
                    )
                    column.addWidget(heading)
                    heading.ensurePolished()
                    heading.setToolTip(self.tr("history_" + group))
                    heading.setText(
                        heading.fontMetrics().elidedText(
                            heading.text(), Qt.ElideRight, heading_width
                        )
                    )
                    heading_h = max(
                        heading.minimumSizeHint().height(),
                        heading.sizeHint().height(),
                        heading.fontMetrics().height() + self._scaled(10),
                    )
                    heading.setFixedHeight(heading_h)
                    title_row = self._build_history_title_row(title, selected, elide_width)
                    column.addWidget(title_row)
                    title_row.setVisible(not collapsed)
                    row.ensurePolished()
                    column.activate()
                    row_h = max(
                        row.minimumSizeHint().height(), row.sizeHint().height()
                    ) + self._scaled(2)
                    item.setSizeHint(QSize(0, row_h))
                    self.conversation_list.setItemWidget(item, row)
                else:
                    title_row = self._build_history_title_row(title, selected, elide_width)
                    item.setSizeHint(QSize(0, title_row.height() + self._scaled(2)))
                    self.conversation_list.setItemWidget(item, title_row)
                if index > 0 and group in self.config.collapsed_history:
                    item.setHidden(True)
                if selected:
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
                selected = candidate is item
                title_row = (
                    widget
                    if widget.objectName() == "historyTitleRow"
                    else widget.findChild(QWidget, "historyTitleRow")
                )
                for target in (title_row, widget.findChild(QLabel, "historyItemTitle")):
                    if target is not None:
                        target.setProperty("selected", selected)
                        target.style().unpolish(target)
                        target.style().polish(target)
                        target.update()

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
        menu.addSeparator()
        menu.addAction(self.tr("delete_all_conversations"), self.delete_all_conversations)
        menu.exec(self.conversation_list.viewport().mapToGlobal(position))

    def _build_history_menu(self) -> QMenu:
        menu = QMenu(self)
        busy = bool(self.active_job or self._submitting)
        menu.addAction(self.tr("refresh"), self.refresh_shared_history)
        menu.addSeparator()
        delete_one = menu.addAction(
            self.tr("delete_selected_conversation"), self.delete_conversation
        )
        delete_one.setEnabled(bool(self.current_id and not busy))
        menu.addSeparator()
        delete_all = menu.addAction(
            self.tr("delete_all_conversations"), self.delete_all_conversations
        )
        delete_all.setEnabled(bool((self.conversations or self.history_search.text()) and not busy))
        return menu

    def open_history_menu(self):
        menu = self._build_history_menu()
        menu.exec(self.history_menu_btn.mapToGlobal(self.history_menu_btn.rect().bottomLeft()))

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

    def _update_chat_title(self):
        if not hasattr(self, "chat_title"):
            return
        record = next((r for r in self.conversations if r["id"] == self.current_id), None)
        title = (record.get("title") or "").strip() if record else ""
        if not title or title == self.tr("untitled"):
            title = self.tr("new_chat")
        elided = self.chat_title.fontMetrics().elidedText(title, Qt.ElideRight, self._scaled(280))
        self.chat_title.setText(elided)
        self.chat_title.setToolTip(title)

    def open_conversation(self, conversation_id):
        if self.agent_panel.active and conversation_id != self.current_id:
            self.show_error("conversation_busy")
            return
        self.current_id = conversation_id
        self.agent_panel.load(conversation_id)
        self.last_job = None
        self._update_chat_title()
        record = next((r for r in self.conversations if r["id"] == conversation_id), None)
        self._context_dirty = False
        self._gpu_dirty = False
        if record and record["model_id"]:
            index = self.model_combo.findData(record["model_id"])
            if index >= 0:
                self.model_combo.blockSignals(True)
                self.model_combo.setCurrentIndex(index)
                self.model_combo.blockSignals(False)
                self._sync_model_combo_tooltip()
                self._sync_model_combo_width()
        self._render_model_context()
        self._refresh_model_context()
        self._sync_last_request_context()
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
                    self.stop_button.show()
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

    def delete_all_conversations(self):
        if self.active_job or self._submitting:
            self.show_error("conversation_busy")
            return
        if not self.conversations and not self.history_search.text():
            return
        if (
            QMessageBox.question(
                self,
                self.tr("confirm"),
                self.tr("delete_all_conversations_confirm"),
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            != QMessageBox.Yes
        ):
            return

        def deleted_all(_):
            self.agent_panel.load(None)
            self.current_id = None
            self.last_job = None
            self.messages = []
            self.conversations = []
            if self._history_search_open or self.history_search.text():
                self.search_timer.stop()
                self.history_search.blockSignals(True)
                self.history_search.clear()
                self.history_search.blockSignals(False)
                self._history_search_open = False
                self._apply_sidebar()
            self.render_messages()
            self.refresh_conversations()
            self.notify(self.tr("all_conversations_deleted"))

        self.api.request("DELETE", TEXT + "/conversations", success=deleted_all)

    def _authorized_model_roots(self) -> list[Path]:
        roots = [data_path().absolute() / "models"]
        for raw in self.config.model_roots:
            if not raw:
                continue
            p = Path(raw)
            if p.is_absolute() and ".." not in p.parts:
                roots.append(p.absolute())
        return roots

    def _is_model_path_authorized(self, location: str | Path | None) -> bool:
        if not location:
            return False
        p = Path(location)
        if not p.is_absolute() or ".." in p.parts:
            return False
        abs_path = p.absolute()
        return any(
            abs_path.is_relative_to(root) and abs_path != root
            for root in self._authorized_model_roots()
        )

    def _is_model_record_authorized(self, record: dict | None) -> bool:
        if not isinstance(record, dict) or record.get("backend") != "llama.cpp":
            return True
        file_status = (record.get("metadata") or {}).get("file_status")
        if file_status == "unauthorized":
            return False
        location = record.get("location")
        if not location:
            return True
        if self.session.owned:
            return self._is_model_path_authorized(location)
        return True

    @staticmethod
    def _validate_authorizable_model_file(path: Path) -> str | None:
        if not path.is_absolute() or ".." in path.parts:
            return "invalid_path"
        cur = Path(path.anchor or "/")
        for part in path.parts[1:-1]:
            cur = cur / part
            try:
                st = os.lstat(cur)
            except OSError as exc:
                return "model_file_missing" if exc.errno == errno.ENOENT else "invalid_path"
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                return "invalid_path"
        try:
            st = os.lstat(path)
        except OSError as exc:
            return "model_file_missing" if exc.errno == errno.ENOENT else "invalid_path"
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            return "invalid_path"
        return None

    def authorize_selected_model(self):
        self.authorize_model_directory(self.selected_model())

    def authorize_model_directory(self, target: object = None):
        if self.active_job or self.agent_panel.active:
            self.show_error("busy")
            return
        candidate_str: str | None = None
        if isinstance(target, (str, Path)):
            candidate_str = str(target)
        elif isinstance(target, dict):
            if target.get("location"):
                candidate_str = str(target["location"])
            elif target.get("model_id"):
                rec = next((m for m in self.models if m.get("id") == target["model_id"]), None)
                if rec and rec.get("location"):
                    candidate_str = str(rec["location"])
        if not candidate_str and self._pending_authorize_model_id:
            rec = next(
                (m for m in self.models if m.get("id") == self._pending_authorize_model_id), None
            )
            if rec and rec.get("location"):
                candidate_str = str(rec["location"])
        if not candidate_str and self._pending_authorize_target:
            candidate_str = str(self._pending_authorize_target)
        if not candidate_str:
            rec = self._selected_chat_model() or self.selected_model()
            if rec and rec.get("location"):
                candidate_str = str(rec["location"])
        if not candidate_str:
            self.show_error("model_required")
            return
        candidate = Path(candidate_str)
        err = self._validate_authorizable_model_file(candidate)
        if err is not None:
            self.show_error(err, component="file_validation", target=str(candidate))
            return
        directory = str(candidate.parent)
        if directory not in self.config.model_roots:
            self.config.model_roots.append(directory)
            self.config.save()
        existing_roots = [self.roots.item(i).text() for i in range(self.roots.count())]
        if directory not in existing_roots:
            self.roots.addItem(directory)
        self._dismiss_notice()
        if self.session.owned:
            self._pending_authorize_dir = directory
            self.is_connected = False
            self.connection.setText(self.tr("connecting"))
            self.pages.setEnabled(False)
            self.session.restart(self.config)
        else:
            self.notify(self.tr("model_directory_authorized", path=directory))

    def _warn_if_selected_model_unauthorized(self):
        rec = self._selected_chat_model()
        if rec and not self._is_model_record_authorized(rec):
            self.show_error(
                "model_directory_unauthorized",
                component="file_validation",
                target=rec.get("location"),
            )
        elif (
            isinstance(self._last_error_meta, tuple)
            and self._last_error_meta[0] == "model_directory_unauthorized"
            and (rec is None or self._is_model_record_authorized(rec))
        ):
            self._dismiss_notice()

    def model_selected(self):
        if not self.active_job:
            self.last_job = None
        self._sync_model_combo_tooltip()
        self._sync_model_combo_width()
        self._context_dirty = False
        self._gpu_dirty = False
        self._sync_last_request_context()
        self._render_model_context()
        self._refresh_model_context()
        self._warn_if_selected_model_unauthorized()
        if self.current_id and self.model_combo.currentData() and not self.active_job:
            self.api.request(
                "PATCH",
                TEXT + f"/conversations/{self.current_id}",
                {"model_id": self.model_combo.currentData()},
            )

    def _selected_chat_model(self):
        return next((m for m in self.models if m["id"] == self.model_combo.currentData()), None)

    def _populate_context_presets(self, maximum: int):
        if not hasattr(self, "context_preset"):
            return
        current = self.context_preset.currentData()
        self.context_preset.blockSignals(True)
        self.context_preset.clear()
        self.context_preset.addItem(self.tr("context_preset_auto"), "auto")
        for preset in CONTEXT_PRESETS:
            if preset <= max(2048, maximum):
                self.context_preset.addItem(f"{preset} ({preset // 1024}K)", preset)
        self.context_preset.addItem(self.tr("context_preset_custom"), "custom")
        idx = self.context_preset.findData(current if current is not None else "auto")
        self.context_preset.setCurrentIndex(idx if idx >= 0 else 0)
        self.context_preset.blockSignals(False)

    def _sync_context_preset(self, *_):
        if not hasattr(self, "context_preset"):
            return
        self.context_preset.blockSignals(True)
        if self.context_mode.currentData() == "auto":
            self.context_preset.setCurrentIndex(self.context_preset.findData("auto"))
        else:
            val = self.context_tokens.value()
            idx = self.context_preset.findData(val)
            if idx >= 0:
                self.context_preset.setCurrentIndex(idx)
            else:
                self.context_preset.setCurrentIndex(self.context_preset.findData("custom"))
        self.context_preset.blockSignals(False)

    def _context_preset_changed(self, *_):
        data = self.context_preset.currentData()
        if data == "auto":
            self.context_mode.setCurrentIndex(self.context_mode.findData("auto"))
        elif isinstance(data, int):
            self.context_mode.setCurrentIndex(self.context_mode.findData("manual"))
            self.context_tokens.setValue(min(data, self.context_tokens.maximum()))
        elif data == "custom":
            self.context_mode.setCurrentIndex(self.context_mode.findData("manual"))
        self._context_edited()

    def _context_edited(self, *_):
        self._context_dirty = True

    def sync_context_slider(self, *_):
        maximum = self.context_tokens.maximum()
        position = (
            round(1000 * math.log(self.context_tokens.value() / 128) / math.log(maximum / 128))
            if maximum > 128
            else 0
        )
        self.context_slider.blockSignals(True)
        self.context_slider.setValue(position)
        self.context_slider.blockSignals(False)

    def context_slider_changed(self, position):
        maximum = self.context_tokens.maximum()
        self.context_tokens.setValue(round(128 * (maximum / 128) ** (position / 1000)))

    def _context_mode_changed(self, *_):
        self._sync_context_preset()
        self.context_slider.setEnabled(
            bool(self._selected_chat_model())
            and self.context_mode.currentData() == "manual"
            and not self._context_saving
            and not self.active_job
            and not self.agent_panel.active
        )
        self.context_tokens.setEnabled(
            bool(self._selected_chat_model())
            and self.context_mode.currentData() == "manual"
            and not self._context_saving
        )

    def _model_gpu_config(self, model=None):
        params = dict(self.config.parameters) if isinstance(self.config.parameters, dict) else {}
        cfg = {
            "device": params.get("device", "auto"),
            "gpu_offload_mode": params.get("gpu_offload_mode", "auto"),
            "gpu_layers": params.get("gpu_layers", 99),
        }
        if not model:
            return cfg
        if model.get("backend") == "ollama":
            return {"device": "cpu", "gpu_offload_mode": "cpu", "gpu_layers": 0}
        saved_gpu = (model.get("metadata") or {}).get("desktop_gpu")
        if isinstance(saved_gpu, dict) and saved_gpu:
            if saved_gpu.get("device"):
                cfg["device"] = saved_gpu["device"]
            if saved_gpu.get("gpu_offload_mode"):
                cfg["gpu_offload_mode"] = saved_gpu["gpu_offload_mode"]
            if isinstance(saved_gpu.get("gpu_layers"), int):
                cfg["gpu_layers"] = saved_gpu["gpu_layers"]
        return cfg

    def _context_params_kwargs(self, model=None):
        target = model if model is not None else self._selected_chat_model()
        cfg = self._model_gpu_config(target)
        return {
            "device": cfg.get("device"),
            "gpu_offload_mode": cfg.get("gpu_offload_mode"),
        }

    @staticmethod
    def _normalize_gpu_layers(mode: str | None, value: int | None) -> int:
        if mode == "cpu":
            return 0
        layers = int(value) if isinstance(value, int) else 99
        if mode in ("auto", "max") and layers <= 0:
            return 99
        return max(0, layers)

    def _gpu_reason_label(self, reason: str | None, fallback: str | None = None) -> str | None:
        code = str(reason or fallback or "").strip()
        if not code:
            return None
        if code == "vram_partial_offload":
            return self.tr("gpu_reason_vram_partial_offload")
        if code.startswith("oom_retry"):
            return self.tr("gpu_reason_oom_retry")
        if code == "gpu_offload_unverified":
            return self.tr("gpu_reason_gpu_offload_unverified")
        if code == "gpu_unavailable":
            return self.tr("gpu_reason_gpu_unavailable")
        return None

    def _merge_optimistic_context(self, model_id: str, record: dict) -> dict:
        prev = self.model_contexts.get(model_id)
        fresh = context_settings(record, **self._context_params_kwargs(record))
        if isinstance(prev, dict):
            for key in ("active", "applied_tokens", "loaded_model_name"):
                if key in prev:
                    fresh[key] = prev[key]
            prev_gpu = prev.get("gpu")
            if isinstance(prev_gpu, dict) and isinstance(fresh.get("gpu"), dict):
                for key in (
                    "applied_mode",
                    "applied_requested_layers",
                    "applied_offloaded_layers",
                    "applied_total_layers",
                    "applied_device",
                    "applied_reason",
                    "fallback_reason",
                    "active_other_model",
                    "vram_total_bytes",
                    "vram_free_bytes",
                    "vram_used_bytes",
                    "engine_vram_bytes",
                    "external_vram_bytes",
                    "model_estimated_vram_bytes",
                ):
                    if key in prev_gpu:
                        fresh["gpu"][key] = prev_gpu[key]
        return fresh

    def _sync_reload_button(
        self,
        *,
        is_active: bool,
        needs_reload: bool,
        busy: bool,
    ):
        if not hasattr(self, "context_reload_btn"):
            return
        self.context_reload_btn.setVisible(bool(is_active and needs_reload))
        self.context_reload_btn.setEnabled(bool(is_active and needs_reload and not busy))

    def _chat_gpu_edited(self, *_):
        self._gpu_dirty = True
        self._render_model_context()

    def _chat_gpu_mode_changed(self, *_):
        if not hasattr(self, "chat_gpu_mode"):
            return
        model = self._selected_chat_model()
        is_llama = bool(model and model.get("backend") == "llama.cpp")
        mode = self.chat_gpu_mode.currentData()
        if mode == "cpu":
            self.chat_gpu_layers.blockSignals(True)
            self.chat_gpu_layers.setValue(0)
            self.chat_gpu_layers.blockSignals(False)
        elif mode in ("auto", "max", "manual") and self.chat_gpu_layers.value() <= 0:
            self.chat_gpu_layers.blockSignals(True)
            self.chat_gpu_layers.setValue(99)
            self.chat_gpu_layers.blockSignals(False)
        busy = bool(
            self._gpu_saving or self._loading_model or self.active_job or self.agent_panel.active
        )
        self.chat_gpu_layers.setEnabled(is_llama and mode == "manual" and not busy)

    def _sync_chat_gpu_pill(self, label: str, tone: str, visible: bool):
        if not hasattr(self, "chat_gpu_pill"):
            return
        self.chat_gpu_pill.setText(label)
        polish_property(self.chat_gpu_pill, "tone", tone)
        fits_topbar = self._topbar_pane_width() >= self._scaled(760)
        self.chat_gpu_pill.setVisible(visible and fits_topbar and self.pages.currentIndex() == 0)

    def _render_model_gpu(self) -> bool:
        if not hasattr(self, "chat_gpu_mode"):
            return False
        model = self._selected_chat_model()
        is_llama = bool(model and model.get("backend") == "llama.cpp")
        busy = bool(
            self._gpu_saving or self._loading_model or self.active_job or self.agent_panel.active
        )
        self.chat_gpu_mode.setEnabled(is_llama and not busy)
        self.chat_gpu_save.setEnabled(is_llama and not busy)
        if not model:
            self.chat_gpu_layers.setEnabled(False)
            self.chat_gpu_status.setText(self.tr("context_choose_model"))
            self._sync_chat_gpu_pill("", "", False)
            return False
        if not is_llama:
            self.chat_gpu_mode.blockSignals(True)
            self.chat_gpu_mode.setCurrentIndex(self.chat_gpu_mode.findData("cpu"))
            self.chat_gpu_mode.blockSignals(False)
            self.chat_gpu_layers.blockSignals(True)
            self.chat_gpu_layers.setValue(0)
            self.chat_gpu_layers.blockSignals(False)
            self.chat_gpu_layers.setEnabled(False)
            self.chat_gpu_status.setText(self.tr("gpu_status_cpu_only"))
            self._sync_chat_gpu_pill("CPU", "", True)
            return False
        cfg = self._model_gpu_config(model)
        ctx_data = self.model_contexts.get(model["id"], {})
        gpu_info = ctx_data.get("gpu") if isinstance(ctx_data.get("gpu"), dict) else {}
        if not self._gpu_dirty:
            mode = gpu_info.get("gpu_offload_mode") or cfg["gpu_offload_mode"]
            raw_layers = gpu_info.get("gpu_layers")
            if not isinstance(raw_layers, int):
                raw_layers = cfg["gpu_layers"]
            layers = self._normalize_gpu_layers(mode, raw_layers)
            self.chat_gpu_mode.blockSignals(True)
            idx = self.chat_gpu_mode.findData(mode)
            self.chat_gpu_mode.setCurrentIndex(idx if idx >= 0 else 0)
            self.chat_gpu_mode.blockSignals(False)
            self.chat_gpu_layers.blockSignals(True)
            self.chat_gpu_layers.setValue(layers)
            self.chat_gpu_layers.blockSignals(False)
        self._chat_gpu_mode_changed()

        cur_mode = self.chat_gpu_mode.currentData()
        cur_layers = self._normalize_gpu_layers(cur_mode, self.chat_gpu_layers.value())
        mode_text = self.tr("offload_" + cur_mode)
        if cur_mode == "manual":
            mode_text += self.tr("gpu_status_layers_arg", layers=cur_layers)
        parts = [self.tr("gpu_status_configured", mode=mode_text)]
        if self._gpu_dirty:
            parts.append(self.tr("gpu_pending_unsaved"))
        applied_mode = gpu_info.get("applied_mode")
        off_l = gpu_info.get("applied_offloaded_layers")
        tot_l = gpu_info.get("applied_total_layers")
        req_l = gpu_info.get("applied_requested_layers")
        applied_reason = gpu_info.get("applied_reason")
        fallback_reason = gpu_info.get("fallback_reason")
        reduced_offload = False
        if applied_mode is not None:
            dev = gpu_info.get("applied_device") or "cpu"
            if off_l is not None and tot_l:
                actual_str = f"{off_l}/{tot_l}"
            elif off_l is not None:
                actual_str = str(off_l)
            else:
                actual_str = "-"
            if req_l is not None:
                parts.append(
                    self.tr(
                        "gpu_status_req_actual",
                        requested=req_l,
                        actual=actual_str,
                        device=dev,
                    )
                )
            reduced_offload = bool(
                applied_reason
                in {"vram_partial_offload", "gpu_offload_unverified", "gpu_unavailable"}
                or str(applied_reason or "").startswith("oom_retry")
                or fallback_reason in {"gpu_offload_unverified", "gpu_unavailable"}
                or (
                    applied_mode in {"auto", "max"}
                    and tot_l
                    and off_l is not None
                    and off_l < tot_l
                )
            )
            reason_note = self._gpu_reason_label(
                applied_reason or ("vram_partial_offload" if reduced_offload else None),
                fallback_reason,
            )
            if reason_note:
                parts.append(reason_note)
        else:
            if cur_mode == "manual":
                parts.append(self.tr("gpu_status_req_layers", requested=cur_layers))
            other_running = gpu_info.get("active_other_model") or ctx_data.get("loaded_model_name")
            if other_running:
                parts.append(self.tr("gpu_status_running_other", model=other_running))
            else:
                parts.append(self.tr("gpu_status_not_loaded"))
            parts.append(self.tr("context_on_start"))

        vram_free = gpu_info.get("vram_free_bytes")
        vram_total = gpu_info.get("vram_total_bytes")
        if vram_total is None and hasattr(self, "resource_monitor"):
            snap = getattr(self.resource_monitor, "latest", None)
            if snap and snap.vram_total_bytes:
                vram_total = snap.vram_total_bytes
                if snap.vram_used_bytes is not None:
                    vram_free = max(0, snap.vram_total_bytes - snap.vram_used_bytes)
        if vram_total:
            if vram_free is not None:
                ext_vram = gpu_info.get("external_vram_bytes")
                if isinstance(ext_vram, int) and ext_vram >= 512 * 1024**2:
                    parts.append(
                        self.tr(
                            "gpu_status_vram_contended",
                            free=f"{vram_free / (1024**3):.1f}",
                            total=f"{vram_total / (1024**3):.1f}",
                            external=f"{ext_vram / (1024**3):.1f}",
                        )
                    )
                else:
                    parts.append(
                        self.tr(
                            "gpu_status_vram",
                            free=f"{vram_free / (1024**3):.1f}",
                            total=f"{vram_total / (1024**3):.1f}",
                        )
                    )
            else:
                parts.append(
                    self.tr("gpu_status_vram_total", total=f"{vram_total / (1024**3):.1f}")
                )

        gpu_needs_reload = bool(
            applied_mode is not None
            and (
                applied_mode != cur_mode
                or (cur_mode == "manual" and req_l is not None and req_l != cur_layers)
            )
        )
        if gpu_needs_reload:
            parts.append(self.tr("context_reload"))
        self.chat_gpu_status.setText(" · ".join(parts))
        if applied_mode is not None:
            tone = "warn" if reduced_offload or not off_l else "ok"
            if off_l and tot_l:
                self._sync_chat_gpu_pill(f"GPU {off_l}/{tot_l}", tone, True)
            elif off_l:
                self._sync_chat_gpu_pill(f"GPU {off_l}", tone, True)
            else:
                self._sync_chat_gpu_pill("CPU", "warn", True)
        else:
            pill_tone = "warn" if cur_mode == "cpu" else ""
            short_mode = {"auto": "Auto", "max": "Max", "manual": f"{cur_layers}L", "cpu": "CPU"}
            label = "CPU" if cur_mode == "cpu" else f"GPU · {short_mode.get(cur_mode, cur_mode)}"
            self._sync_chat_gpu_pill(label, pill_tone, True)
        return gpu_needs_reload

    def save_model_gpu(self):
        if self.agent_panel.active:
            self.show_error("conversation_busy")
            return
        model = self._selected_chat_model()
        if not model or self._gpu_saving or self.active_job or model.get("backend") != "llama.cpp":
            return
        model_id = model["id"]
        mode = self.chat_gpu_mode.currentData()
        layers = self._normalize_gpu_layers(mode, self.chat_gpu_layers.value())
        base_dev = self._model_gpu_config(model).get("device", "auto")
        if mode == "cpu":
            dev = "cpu"
        elif base_dev == "cpu" or not base_dev:
            dev = "auto"
        else:
            dev = base_dev
        body = {"gpu_offload_mode": mode, "gpu_layers": layers, "device": dev}
        self._gpu_saving = True
        self.chat_gpu_save.setEnabled(False)
        self.chat_gpu_mode.setEnabled(False)
        self.chat_gpu_layers.setEnabled(False)

        def saved(record):
            self._gpu_saving = False
            self._gpu_dirty = False
            self.models = [record if item["id"] == model_id else item for item in self.models]
            self.model_contexts[model_id] = self._merge_optimistic_context(model_id, record)
            self._refresh_model_context()
            self._render_model_context()
            self.notify(self.tr("gpu_saved"))

        def failed(code):
            self._gpu_saving = False
            self._render_model_gpu()
            self.show_error(code)

        self.api.request(
            "PUT", TEXT + f"/models/{model_id}/gpu", body, success=saved, failure=failed
        )

    def _render_model_context(self):
        if not hasattr(self, "context_mode"):
            return
        model = self._selected_chat_model()
        busy = bool(
            self._context_saving
            or self._loading_model
            or self.active_job
            or self.agent_panel.active
        )
        self.context_mode.setEnabled(bool(model) and not busy)
        if hasattr(self, "context_preset"):
            self.context_preset.setEnabled(bool(model) and not busy)
        self.context_save.setEnabled(bool(model) and not busy)
        if not model:
            self.context_tokens.setEnabled(False)
            self.context_status.setText(self.tr("context_choose_model"))
            self._render_model_gpu()
            self._sync_reload_button(is_active=False, needs_reload=False, busy=busy)
            return
        saved = self.model_contexts.get(model["id"]) or context_settings(
            model, **self._context_params_kwargs(model)
        )
        applied = saved.get("applied_tokens")
        is_active = applied is not None
        if self._context_dirty:
            self._context_mode_changed()
            pending_parts = [self.tr("context_pending_unsaved")]
            if applied is not None:
                pending_parts.append(self.tr("context_applied", tokens=applied))
            elif saved.get("loaded_model_name"):
                pending_parts.append(
                    self.tr("context_running_other", model=saved["loaded_model_name"])
                )
            self.context_status.setText(" · ".join(pending_parts))
            gpu_needs_reload = self._render_model_gpu()
            ctx_needs_reload = applied is not None and applied != saved["effective_tokens"]
            self._sync_reload_button(
                is_active=is_active,
                needs_reload=ctx_needs_reload or gpu_needs_reload,
                busy=busy,
            )
            return
        self._populate_context_presets(saved["maximum"])
        self.context_mode.blockSignals(True)
        self.context_mode.setCurrentIndex(self.context_mode.findData(saved["mode"]))
        self.context_mode.blockSignals(False)
        self.context_tokens.blockSignals(True)
        self.context_tokens.setMaximum(saved["maximum"])
        self.context_tokens.setValue(saved["manual_tokens"])
        self.context_tokens.blockSignals(False)
        self.sync_context_slider()
        self._context_mode_changed()
        text = self.tr("context_configured", tokens=saved["effective_tokens"])
        ctx_needs_reload = False
        if applied is not None:
            text += " · " + self.tr("context_applied", tokens=applied)
            if applied != saved["effective_tokens"]:
                ctx_needs_reload = True
                text += " · " + self.tr("context_reload")
        elif saved.get("loaded_model_name"):
            text += " · " + self.tr("context_running_other", model=saved["loaded_model_name"])
        else:
            text += " · " + self.tr("context_on_start")
        if saved.get("mode") == "auto" and saved.get("auto_reason") == "safe_fallback":
            text += " · " + self.tr("context_auto_fallback")
        if saved.get("memory_warning"):
            text += " · " + self.tr("context_memory_warning")
        self.context_status.setText(text)
        gpu_needs_reload = self._render_model_gpu()
        self._sync_reload_button(
            is_active=is_active,
            needs_reload=ctx_needs_reload or gpu_needs_reload,
            busy=busy,
        )

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
            if self.model_combo.currentData() == model_id:
                self._render_model_context()

        query = urlencode(
            {k: v for k, v in self._context_params_kwargs().items() if isinstance(v, str) and v}
        )
        suffix = f"?{query}" if query else ""
        self.api.request("GET", TEXT + f"/models/{model_id}/context{suffix}", success=received)

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
            self.model_contexts[model_id] = self._merge_optimistic_context(model_id, record)
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
            gpu_cfg = self._model_gpu_config(model)
            gpu_cfg["gpu_layers"] = self._normalize_gpu_layers(
                gpu_cfg.get("gpu_offload_mode"), gpu_cfg.get("gpu_layers")
            )
            if (
                self._gpu_dirty
                and self.model_combo.currentData() == model["id"]
                and hasattr(self, "chat_gpu_mode")
                and model.get("backend") == "llama.cpp"
            ):
                sel_mode = self.chat_gpu_mode.currentData()
                gpu_cfg["gpu_offload_mode"] = sel_mode
                gpu_cfg["gpu_layers"] = self._normalize_gpu_layers(
                    sel_mode, self.chat_gpu_layers.value()
                )
                if sel_mode == "cpu":
                    gpu_cfg["device"] = "cpu"
                elif gpu_cfg.get("device") in (None, "", "cpu"):
                    gpu_cfg["device"] = "auto"
            parameters.update(gpu_cfg)
            saved = self.model_contexts.get(model["id"]) or context_settings(
                model,
                device=gpu_cfg.get("device"),
                gpu_offload_mode=gpu_cfg.get("gpu_offload_mode"),
            )
            if (
                self._context_dirty
                and self.model_combo.currentData() == model["id"]
                and hasattr(self, "context_mode")
            ):
                if self.context_mode.currentData() == "manual":
                    parameters["context_size"] = self.context_tokens.value()
                else:
                    parameters["context_size"] = saved.get(
                        "automatic_tokens",
                        context_settings(
                            model,
                            device=gpu_cfg.get("device"),
                            gpu_offload_mode=gpu_cfg.get("gpu_offload_mode"),
                        )["effective_tokens"],
                    )
            else:
                parameters["context_size"] = saved["effective_tokens"]
            if model["backend"] == "ollama":
                parameters.update(device="cpu", gpu_layers=0, gpu_offload_mode="cpu")
        return parameters

    def request_parameters(self):
        return self._parameters_for_model(self._selected_chat_model())

    def send_message(self):
        if self.agent_panel.active or self.agent_panel.compatibility_busy:
            return
        if (
            self.active_job
            or self._submitting
            or self._context_saving
            or self._gpu_saving
            or not self.is_connected
        ):
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
            self.stop_button.show()
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
        model_id = record.get("model_id")
        if model_id and (
            record.get("gpu_offloaded_layers") is not None
            or record.get("gpu_offload_mode") is not None
            or record.get("execution_device") is not None
        ):
            ctx_entry = self.model_contexts.setdefault(model_id, {})
            gpu_entry = ctx_entry.setdefault("gpu", {})
            if record.get("gpu_offload_mode") is not None:
                gpu_entry["applied_mode"] = record.get("gpu_offload_mode")
            if record.get("gpu_requested_layers") is not None:
                gpu_entry["applied_requested_layers"] = record.get("gpu_requested_layers")
            elif (record.get("parameters") or {}).get("gpu_layers") is not None:
                gpu_entry["applied_requested_layers"] = record["parameters"]["gpu_layers"]
            if record.get("gpu_offloaded_layers") is not None:
                gpu_entry["applied_offloaded_layers"] = record.get("gpu_offloaded_layers")
            if record.get("gpu_total_layers") is not None:
                gpu_entry["applied_total_layers"] = record.get("gpu_total_layers")
            if record.get("execution_device") is not None:
                gpu_entry["applied_device"] = record.get("execution_device")
            if record.get("gpu_offload_reason") is not None:
                gpu_entry["applied_reason"] = record.get("gpu_offload_reason")
            if record.get("fallback_reason") is not None:
                gpu_entry["fallback_reason"] = record.get("fallback_reason")
            ctx_entry["active"] = True
            if record.get("context_limit_tokens") is not None:
                ctx_entry["applied_tokens"] = record.get("context_limit_tokens")
            if self.model_combo.currentData() == model_id:
                self._render_model_context()
        self.render_messages()
        if state in TERMINAL:
            self.active_job = None
            self.api.close_stream()
            self._generation_idle()
            self.refresh_messages()
            self.refresh_models()
            err_code = record.get("error_code")
            if err_code:
                err_target = record.get("model_name")
                if err_code in {"model_directory_unauthorized", "path_not_allowed"} and model_id:
                    self._pending_authorize_model_id = model_id
                    rec = next((m for m in self.models if m.get("id") == model_id), None)
                    if rec and rec.get("location"):
                        self._pending_authorize_target = rec.get("location")
                        err_target = rec.get("location")
                self.show_error(err_code, component="chat_generation", target=err_target)

    def _generation_idle(self):
        self.send_button.setEnabled(True)
        if not getattr(getattr(self, "agent_panel", None), "active", None):
            self.stop_button.setEnabled(False)
            self.stop_button.hide()
            self.generation_status.setText(self.tr("ready"))
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
                "status": job.get("state"),
                "error_code": job.get("error_code"),
                "statistics": job,
                "generation_id": job["id"],
            }
            index = next(
                (i for i, m in enumerate(messages) if m.get("generation_id") == job["id"]), None
            )
            if index is not None:
                messages[index] = replacement
            elif job.get("content") or job.get("reasoning_content") or job.get("error_code"):
                messages.append(replacement)
        runs = getattr(getattr(self, "agent_panel", None), "runs", None) or []
        panel = getattr(self, "agent_panel", None)
        granted_folders = getattr(panel, "granted_folders", None) or []
        cancelled_grants = getattr(panel, "folder_grant_cancelled_runs", set())
        if runs:
            by_response = {}
            by_request = {}
            for run in runs:
                if run.get("continued_by"):
                    continue
                resp_id = run.get("response_message_id")
                if resp_id and resp_id not in by_response:
                    by_response[resp_id] = run
                req_id = run.get("request_message_id")
                if req_id and req_id not in by_request:
                    by_request[req_id] = run
            attached_grant_runs = set()
            for idx, msg in enumerate(messages):
                msg_id = msg.get("id")
                if msg.get("role") == "assistant":
                    if msg_id and msg_id in by_response:
                        msg["agent_run"] = by_response[msg_id]
                    elif idx > 0 and messages[idx - 1].get("role") == "user":
                        prev_id = messages[idx - 1].get("id")
                        prev_run = by_request.get(prev_id) if prev_id else None
                        if prev_run and prev_run.get("state") == "completed":
                            msg["agent_run"] = prev_run
                elif msg.get("role") == "user" and msg_id in by_request:
                    req_run = by_request[msg_id]
                    next_is_assistant = (
                        idx + 1 < len(messages) and messages[idx + 1].get("role") == "assistant"
                    )
                    next_has_run = next_is_assistant and (
                        messages[idx + 1].get("id") == req_run.get("response_message_id")
                        or req_run.get("state") == "completed"
                    )
                    if not next_has_run and (
                        not next_is_assistant
                        or req_run.get("state") != "completed"
                        or req_run.get("needs_folder_grant")
                    ):
                        msg["agent_run"] = req_run
                if msg.get("agent_run"):
                    run_obj = msg["agent_run"]
                    has_granted_folder = (
                        panel.grant_satisfies_run(run_obj, granted_folders)
                        if panel and hasattr(panel, "grant_satisfies_run")
                        else bool(granted_folders)
                    )
                    msg["has_granted_folder"] = has_granted_folder
                    msg["folder_grant_cancelled"] = run_obj.get("id") in cancelled_grants
                    if run_obj.get("needs_folder_grant"):
                        rid = run_obj.get("id")
                        if rid and rid in attached_grant_runs:
                            msg["suppress_folder_prompt"] = True
                        elif rid:
                            attached_grant_runs.add(rid)
        names_by_id = {m["id"]: m["name"] for m in self.models}
        for msg in messages:
            if msg.get("role") == "assistant" and not msg.get("model_name"):
                stats = msg.get("statistics") or {}
                inferred = stats.get("execution_model") or names_by_id.get(msg.get("model_id"))
                if inferred:
                    msg["model_name"] = inferred
        self.transcript.can_regenerate = bool(
            self.is_connected
            and self.model_combo.currentData()
            and not self.active_job
            and not self._submitting
            and not getattr(getattr(self, "agent_panel", None), "active", None)
        )
        self.transcript.set_messages(messages, self.tr)
        self._sync_last_request_context(runs, messages)

    def _model_name_for_message(self, msg: dict | None) -> str | None:
        if not isinstance(msg, dict):
            return None
        stats = msg.get("statistics") or {}
        if msg.get("model_name"):
            return str(msg["model_name"])
        if stats.get("execution_model"):
            return str(stats["execution_model"])
        mid = msg.get("model_id")
        if mid:
            return next((m["name"] for m in self.models if m["id"] == mid), None)
        return None

    @staticmethod
    def _message_matches_model(msg: dict, selected_model: dict | None) -> bool:
        if not selected_model:
            return True
        stats = msg.get("statistics") or {}
        msg_mid = msg.get("model_id")
        msg_mname = stats.get("execution_model") or msg.get("model_name")
        if msg_mid:
            return msg_mid == selected_model["id"]
        if msg_mname:
            return msg_mname == selected_model["name"]
        return True

    def _sync_last_request_context(self, runs=None, rendered_messages=None):
        if not hasattr(self, "context_usage"):
            return
        messages = rendered_messages if rendered_messages is not None else self.messages
        if runs is None:
            runs = list(getattr(getattr(self, "agent_panel", None), "runs", []) or [])
        current = self._selected_chat_model()
        latest_msg = next(
            (
                m
                for m in reversed(messages)
                if m.get("role") == "assistant" and self._message_matches_model(m, current)
            ),
            None,
        )
        any_assistant = next(
            (m for m in reversed(messages) if m.get("role") == "assistant"),
            None,
        )
        latest = (latest_msg.get("statistics") or {}) if latest_msg else {}
        if latest_msg is None and any_assistant is not None and current is not None:
            other_name = self._model_name_for_message(any_assistant) or self.tr("assistant")
            self.context_details.setText(self.tr("context_unavailable"))
            self.context_usage.setText(
                self.tr("context_last_model_other", model=current["name"], other=other_name)
            )
            self.context_meter.hide()
            self.context_usage.setToolTip("")
            return
        self.context_details.setText(
            statistics_text(latest, self.tr) or self.tr("context_unavailable")
        )
        used, limit = latest.get("context_used_tokens"), latest.get("context_limit_tokens")
        if used is None and runs and isinstance(runs[0].get("context"), dict):
            run_mid = runs[0].get("model_id")
            if not current or not run_mid or run_mid == current["id"]:
                used = runs[0]["context"].get("approx_tokens")
                limit = runs[0]["context"].get("limit")
        if used is not None and limit:
            percent = round(100 * used / limit)
            label_model = self._model_name_for_message(latest_msg)
            if label_model:
                usage_text = self.tr(
                    "context_last_for_model",
                    model=label_model,
                    used=used,
                    limit=limit,
                    percent=percent,
                )
            else:
                usage_text = self.tr("context_last", used=used, limit=limit, percent=percent)
            self.context_usage.setText(usage_text)
            self.context_meter.setValue(min(100, percent))
            self.context_meter.show()
        else:
            self.context_usage.setText(self.tr("context_unavailable"))
            self.context_meter.hide()
        self.context_usage.setToolTip("")
        device = latest.get("execution_device")
        if device:
            off_layers = latest.get("gpu_offloaded_layers") or 0
            tot_layers = latest.get("gpu_total_layers")
            if off_layers and tot_layers:
                actual = f"GPU {off_layers}/{tot_layers}"
            elif off_layers:
                actual = f"GPU {off_layers}"
            else:
                actual = "CPU"
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
        self.render_messages()

        def failed(code):
            self._submitting = False
            self.show_error(code)
            self.render_messages()

        def exported(document):
            messages = document["messages"]
            original_len = len(messages)
            target_index = None
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
            has_completed_answer = last_user is not None and any(
                m["role"] == "assistant" and m["content"].strip() for m in messages[last_user + 1 :]
            )
            trailing_failed = (
                last_user is not None
                and not has_completed_answer
                and any(
                    m["role"] == "assistant"
                    and m.get("status") in {"failed", "cancelled", "interrupted"}
                    for m in messages[last_user + 1 :]
                )
            )
            if (
                last_user is None
                or self.current_id != source
                or (not has_completed_answer and not trailing_failed)
            ):
                failed("no_answer")
                return
            content = messages[last_user]["content"]
            is_tail = target_index is None or target_index == original_len - 1
            if trailing_failed and is_tail:
                self._submitting = False
                self.last_job = None
                if (
                    len(self.messages) >= 2
                    and self.messages[-1].get("role") == "assistant"
                    and self.messages[-1].get("status") in {"failed", "cancelled", "interrupted"}
                    and not str(self.messages[-1].get("content") or "").strip()
                    and self.messages[-2].get("role") == "user"
                    and str(self.messages[-2].get("content") or "").strip() == content.strip()
                ):
                    self.messages = self.messages[:-2]
                self.composer.setPlainText(content)
                self.send_message()
                return
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
                self.model_combo.addItem(record["name"], record["id"])
            index = self.model_combo.findData(selected)
            self.model_combo.setCurrentIndex(max(index, 0))
            by_id = {record["id"]: record for record in records}
            for row in range(self.model_combo.count()):
                rec = by_id.get(self.model_combo.itemData(row))
                if rec:
                    self.model_combo.setItemData(
                        row, f"{rec['name']} · {rec['backend']}", Qt.ToolTipRole
                    )
            self.model_combo.blockSignals(False)
            self._sync_model_combo_tooltip()
            self._sync_model_combo_width()
            self.refresh_model_table()
            self._render_model_context()
            self._refresh_model_context()
            self._warn_if_selected_model_unauthorized()
            self._loaded("models")

        self.api.request("GET", TEXT + "/models", success=received)

    def scan_models(self):
        self.api.request(
            "POST",
            TEXT + "/models/scan",
            {},
            success=lambda _: self.refresh_models(),
        )

    def refresh_model_table(self):
        selected = self.selected_model()
        self.model_table.setHorizontalHeaderLabels(
            [
                self.tr(k)
                for k in ("model_name", "quant_arch_col", "size", "engine", "compatibility")
            ]
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
            quant_arch = (
                " · ".join(
                    str(value)
                    for value in (
                        record.get("quantization") or record.get("format"),
                        metadata.get("architecture"),
                    )
                    if value
                )
                or "—"
            )
            title = ("★ " if record["id"] in favorites else "") + record["name"]
            loaded_tok = self._loaded_models.get(record["id"])
            unauthorized = not self._is_model_record_authorized(record)
            status_text = self.tr(record["compatibility"])
            if unauthorized:
                status_text = f"{self.tr('model_directory_unauthorized_short')} · {status_text}"
            elif loaded_tok is not None:
                status_text = f"{self.tr('model_loaded_badge')} · {status_text}"
            tooltip_title = f"{title}\n{quant_arch}"
            for column, value in enumerate(
                (
                    title,
                    quant_arch,
                    human_size(record["size_bytes"]),
                    record["backend"],
                    status_text,
                )
            ):
                item = QTableWidgetItem(value)
                item.setToolTip(escape(tooltip_title if column == 0 else value))
                item.setData(Qt.UserRole, record["id"])
                if column == 4 and hasattr(self, "_tokens"):
                    if unauthorized:
                        item.setForeground(QColor(self._tokens.warning))
                    elif loaded_tok is not None:
                        item.setForeground(QColor(self._tokens.accent))
                    else:
                        compat_color = {
                            "compatible": self._tokens.success,
                            "tight": self._tokens.warning,
                            "incompatible": self._tokens.danger,
                        }.get(record.get("compatibility"))
                        if compat_color:
                            item.setForeground(QColor(compat_color))
                self.model_table.setItem(row, column, item)
            if selected and selected["id"] == record["id"]:
                selected_row = row
        self.model_table.verticalHeader().setDefaultSectionSize(self._scaled(42))
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
        unauthorized = bool(record and not self._is_model_record_authorized(record))
        if hasattr(self, "model_authorize_button"):
            self.model_authorize_button.setVisible(unauthorized and self.session.owned)
        self.load_button.setEnabled(
            bool(
                record
                and record["backend"] == "llama.cpp"
                and not self._loading_model
                and not unauthorized
            )
        )
        self.load_button.setToolTip(
            self.tr("model_directory_unauthorized")
            if unauthorized
            else (self.tr("ollama_managed") if record and record["backend"] == "ollama" else "")
        )
        self.favorite_button.setEnabled(bool(record))
        self.favorite_button.setText(
            self.tr(
                "favorite_remove"
                if record and record["id"] in self.config.favorite_models
                else "favorite_add"
            )
        )
        self.model_actions.setEnabled(bool(record))
        self.model_detail.setToolTip(escape(record["location"]) if record else "")
        if not record:
            self.model_detail.clear()
        if record:
            mem_info = self.tr("memory_estimate", size=human_size(record.get("size_bytes")))
            self.model_detail.setText(
                f"{record['name']} · {record['format']} · {record.get('quantization') or '—'} · "
                f"{mem_info}\n"
                f"{self.tr('license')}: {record.get('license') or self.tr('unknown')}"
            )
            details = self.model_detail.text()
            capabilities = record.get("capabilities") or []
            if capabilities:
                details += " · " + " · ".join(capabilities)
            if unauthorized:
                details += "\n" + self.tr("model_directory_unauthorized")
            self.model_detail.setText(details)
            if record["backend"] == "llama.cpp":

                def context_received(settings):
                    current = self.selected_model()
                    applied = settings.get("applied_tokens")
                    if applied is not None:
                        self._loaded_models[record["id"]] = applied
                    else:
                        self._loaded_models.pop(record["id"], None)
                    if self._closing or not current or current["id"] != record["id"]:
                        return
                    status = (
                        self.tr("model_running_context", tokens=applied)
                        if applied is not None
                        else (
                            self.tr("model_directory_unauthorized")
                            if not self._is_model_record_authorized(current)
                            else self.tr("model_not_loaded")
                        )
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

        existing = next(
            (
                r
                for r in self.models
                if r["backend"] == "llama.cpp" and r["location"] == str(candidate)
            ),
            None,
        )
        if (
            existing
            and QMessageBox.question(self, self.tr("confirm"), self.tr("refresh_model_confirm"))
            != QMessageBox.Yes
        ):
            return
        self.api.request(
            "POST",
            TEXT + "/models/import",
            {"path": str(candidate), "refresh_existing": bool(existing)},
            success=imported,
        )

    def sync_ollama(self):
        self.api.request(
            "POST",
            TEXT + "/models/sync-ollama",
            success=lambda _: (self.engine_filter.setCurrentText("ollama"), self.refresh_models()),
        )

    def _load_model_record(self, record: dict | None):
        if not record or self._loading_model:
            if not record:
                self.show_error("model_required")
            return
        self._loading_model = True
        self.load_button.setEnabled(False)
        if hasattr(self, "context_reload_btn"):
            self.context_reload_btn.setEnabled(False)
        self._render_model_context()
        self.notify(self.tr("loading"))

        def loaded(updated_record):
            self._loading_model = False
            self.load_button.setEnabled(True)
            if isinstance(updated_record, dict) and updated_record.get("id"):
                self.models = [
                    updated_record if m["id"] == updated_record["id"] else m for m in self.models
                ]
            self.notify(self.tr("loaded"))
            idx = self.model_combo.findData(record["id"])
            if idx >= 0 and self.model_combo.currentIndex() != idx:
                self.model_combo.setCurrentIndex(idx)
            self.refresh_models()
            self._refresh_model_context()

        def failure(code):
            self._loading_model = False
            self.load_button.setEnabled(True)
            self._render_model_context()
            self.show_error("llama_unavailable" if code == "engine_unavailable" else code)

        self.api.request(
            "POST",
            TEXT + f"/models/{record['id']}/load",
            self._parameters_for_model(record),
            success=loaded,
            failure=failure,
            timeout=130000,
        )

    def load_model(self):
        self._load_model_record(self.selected_model())

    def reload_selected_chat_model(self):
        if self.agent_panel.active or self.active_job:
            self.show_error("conversation_busy")
            return
        self._load_model_record(self._selected_chat_model())

    def unload_model(self):
        record = self.selected_model()
        if record:

            def unloaded(_):
                self._loaded_models.pop(record["id"], None)
                self.notify(self.tr("unloaded"))
                self._refresh_model_context()
                self.refresh_model_table()

            self.api.request(
                "POST",
                TEXT + f"/models/{record['id']}/unload",
                success=unloaded,
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

    def _transfer_queue_selected(self, row: int):
        if 0 <= row < self.download_list.count() and self.download_list.currentIndex() != row:
            self.download_list.setCurrentIndex(row)

    def refresh_downloads(self):
        if not self.is_connected or self._closing:
            return

        def received(records):
            current = self.download_list.currentData()
            self.downloads = records
            self.download_list.blockSignals(True)
            self.download_list.clear()
            if hasattr(self, "transfers_queue"):
                self.transfers_queue.blockSignals(True)
                self.transfers_queue.clear()
            for record in records:
                pct = f" · {record['percent']:.0f}%" if record.get("percent") is not None else ""
                label = f"{record['source']['filename']} · {self.tr(record['state'])}{pct}"
                self.download_list.addItem(label, record["id"])
                if hasattr(self, "transfers_queue"):
                    row_label = (
                        f"{record['source']['filename']}   —   {self.tr(record['state'])}{pct}"
                    )
                    if record.get("source", {}).get("repository"):
                        row_label = f"{record['source']['repository']} / {row_label}"
                    self.transfers_queue.addItem(row_label)
            index = self.download_list.findData(current)
            target_idx = max(index, 0)
            self.download_list.setCurrentIndex(target_idx)
            self.download_list.blockSignals(False)
            if hasattr(self, "transfers_queue"):
                if records:
                    self.transfers_queue.setCurrentRow(target_idx)
                self.transfers_queue.blockSignals(False)
            self._show_download_progress()

        self.api.request("GET", TEXT + "/downloads", success=received)

    def _show_download_progress(self, *_):
        record = self.selected_download()
        has_list = bool(self.downloads)
        self.transfers_empty.setVisible(not has_list)
        self.download_list.setVisible(has_list)
        self.download_progress.setVisible(record is not None)
        self.download_status.setVisible(record is not None)
        if hasattr(self, "transfers_queue"):
            show_q = has_list and self.transfers_queue.count() > 0
            self.transfers_queue.setVisible(show_q)
            self.transfer_queue_heading.setVisible(show_q)
            if show_q and 0 <= self.download_list.currentIndex() < self.transfers_queue.count():
                self.transfers_queue.blockSignals(True)
                self.transfers_queue.setCurrentRow(self.download_list.currentIndex())
                self.transfers_queue.blockSignals(False)
        percent = record.get("percent") if record else None
        self.download_progress.setRange(0, 0 if record and percent is None else 100)
        if percent is not None:
            self.download_progress.setValue(max(0, min(100, int(percent))))
        elif not record:
            self.download_progress.setValue(0)
        state = record.get("state") if record else None
        if hasattr(self, "transfer_state_badge"):
            self.transfer_state_badge.setVisible(record is not None and bool(state))
            if state:
                self.transfer_state_badge.setText(self.tr(state))
                tone = (
                    "ok"
                    if state == "completed"
                    else "error"
                    if state == "failed"
                    else "warn"
                    if state in {"cancelled", "interrupted", "queued"}
                    else "ok"
                )
                polish_property(self.transfer_state_badge, "tone", tone)
        self.cancel_download_button.setVisible(state in {"queued", "running"})
        self.resume_download_button.setVisible(state in {"failed", "cancelled", "interrupted"})
        self.import_download_button.setVisible(
            bool(record and state == "completed" and not record.get("model_id"))
        )
        if not record:
            self.download_status.clear()
            if hasattr(self, "transfer_error_banner"):
                self.transfer_error_banner.hide()
            return
        speed, eta = record.get("speed_bytes_per_second"), record.get("eta_seconds")
        details = []
        if percent is not None:
            details.append(f"{percent:.0f}%")
        if speed is not None:
            details.append(self.tr("download_speed", value=human_size(speed)))
        if eta is not None:
            details.append(self.tr("download_eta", seconds=int(eta)))
        err_msg = record.get("error_code") or record.get("import_error")
        if hasattr(self, "transfer_error_banner"):
            if err_msg:
                translated = self.tr.catalog.get(str(err_msg)) or str(err_msg)
                self.transfer_error_label.setText(
                    self.tr("transfer_error_prefix", error=translated)
                )
                self.transfer_error_banner.show()
            else:
                self.transfer_error_banner.hide()
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

    def _sync_offload_controls(self):
        layers = self.parameter_inputs["gpu_layers"]
        layers.setEnabled(self.gpu_offload_mode.currentData() == "manual")

    def execution_mode_changed(self):
        layers = self.parameter_inputs["gpu_layers"]
        self.gpu_offload_mode.blockSignals(True)
        try:
            if self.device.currentData() == "cpu":
                layers.setValue(0)
                self.gpu_offload_mode.setCurrentIndex(self.gpu_offload_mode.findData("cpu"))
            else:
                if layers.value() == 0:
                    layers.setValue(99)
                if self.gpu_offload_mode.currentData() == "cpu":
                    self.gpu_offload_mode.setCurrentIndex(self.gpu_offload_mode.findData("auto"))
        finally:
            self.gpu_offload_mode.blockSignals(False)
        self._sync_offload_controls()

    def offload_mode_changed(self):
        mode = self.gpu_offload_mode.currentData()
        layers = self.parameter_inputs["gpu_layers"]
        self.device.blockSignals(True)
        try:
            if mode == "cpu":
                self.device.setCurrentIndex(self.device.findData("cpu"))
                layers.setValue(0)
            else:
                if self.device.currentData() == "cpu":
                    self.device.setCurrentIndex(self.device.findData("auto"))
                if layers.value() == 0:
                    layers.setValue(99)
        finally:
            self.device.blockSignals(False)
        self._sync_offload_controls()

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
            gpu_offload_mode=self.gpu_offload_mode.currentData(),
            thinking=self.thinking.isChecked(),
        )
        if (
            self.config.parameters["device"] == "cpu"
            or self.config.parameters["gpu_offload_mode"] == "cpu"
        ):
            self.config.parameters["device"] = "cpu"
            self.config.parameters["gpu_offload_mode"] = "cpu"
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
            self._refresh_model_context()

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
            provenance = build_info()
            lines = [
                f"OmniCore {distribution_version()} · {platform.system()} · {platform.machine()}",
                f"{provenance['channel']} · {provenance.get('source_commit') or '—'} · "
                f"{provenance.get('built_at') or self.tr('source_checkout')}",
                f"Qt: {QApplication.platformName()}",
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
                        f"{human_size(gpu['free_bytes'])}/{human_size(gpu['total_bytes'])} · "
                        f"{self.tr('driver')}: {gpu.get('driver_version') or '—'}"
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
                self.diagnostic_snapshot = snapshot
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
                if hasattr(self, "_diag_tiles"):
                    avail_engines = [
                        r["info"]["id"] for r in records if r.get("info", {}).get("available")
                    ]
                    val, sub = self._diag_tiles["backend"]
                    val.setText(self.tr("ready" if avail_engines else "offline"))
                    sub.setText(", ".join(avail_engines) or self.tr("none"))
                    nv = next(
                        (g for r in records for g in r.get("nvidia_devices", [])),
                        None,
                    )
                    gpu_val, gpu_sub = self._diag_tiles["gpu"]
                    if nv:
                        gpu_val.setText(nv["name"])
                        gpu_sub.setText(
                            f"{human_size(nv['free_bytes'])} / {human_size(nv['total_bytes'])}"
                        )
                    elif devices:
                        gpu_val.setText(", ".join(devices))
                        gpu_sub.setText(llama.get("execution_device") or "CUDA")
                    else:
                        gpu_val.setText("CPU")
                        gpu_sub.setText(self.tr("none"))
                    cpu_val, cpu_sub = self._diag_tiles["cpu"]
                    cpu_val.setText(f"{hardware['cpu_architecture']} · {hardware['cpu_count']}")
                    cpu_sub.setText(
                        f"{human_size(hardware['ram_available_bytes'])} / "
                        f"{human_size(hardware['ram_total_bytes'])}"
                    )
                    st_val, st_sub = self._diag_tiles["storage"]
                    st_val.setText(human_size(hardware["disk_free_bytes"]))
                    st_sub.setText(
                        f"v{distribution_version()} · {provenance.get('channel') or 'source'}"
                    )

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
        polish_property(self.connection, "tone", "warn")
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
        self.resource_monitor.stop()
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
