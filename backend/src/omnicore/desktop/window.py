"""Native widgets for the existing API. Network and inference never block Qt."""

import math
import os
import platform
import re
import tempfile
import uuid
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QRectF,
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
    QPen,
    QPixmap,
    QShortcut,
    QTextDocument,
)
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
from omnicore.desktop.themes import contrast_ratio, palette, readable_accent
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


def sidebar_icon(kind, color, size=18):
    """Draw a crisp 2x vector icon for sidebar buttons."""
    dpr = 2
    px = max(12, size) * dpr
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), 1.8 * dpr, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    s = float(px)
    u = s / 18.0
    if kind in {"expand", "collapse"}:
        painter.drawRoundedRect(QRectF(2.5 * u, 3 * u, 13 * u, 12 * u), 2 * u, 2 * u)
        painter.drawLine(round(6.8 * u), round(3.5 * u), round(6.8 * u), round(14.5 * u))
        if kind == "expand":
            painter.drawLine(round(10 * u), round(7 * u), round(12.2 * u), round(9 * u))
            painter.drawLine(round(10 * u), round(11 * u), round(12.2 * u), round(9 * u))
        else:
            painter.drawLine(round(12 * u), round(7 * u), round(9.8 * u), round(9 * u))
            painter.drawLine(round(12 * u), round(11 * u), round(9.8 * u), round(9 * u))
    elif kind == "new_chat":
        painter.drawLine(round(9 * u), round(4 * u), round(9 * u), round(14 * u))
        painter.drawLine(round(4 * u), round(9 * u), round(14 * u), round(9 * u))
    elif kind == "conversations_nav":
        painter.drawRoundedRect(QRectF(2.5 * u, 3 * u, 13 * u, 9.5 * u), 2.5 * u, 2.5 * u)
        painter.drawLine(round(6 * u), round(12.5 * u), round(5 * u), round(15.2 * u))
        painter.drawLine(round(5 * u), round(15.2 * u), round(9 * u), round(12.5 * u))
    elif kind == "models":
        painter.drawRoundedRect(QRectF(3 * u, 3 * u, 5 * u, 5 * u), 1.2 * u, 1.2 * u)
        painter.drawRoundedRect(QRectF(10 * u, 3 * u, 5 * u, 5 * u), 1.2 * u, 1.2 * u)
        painter.drawRoundedRect(QRectF(3 * u, 10 * u, 5 * u, 5 * u), 1.2 * u, 1.2 * u)
        painter.drawRoundedRect(QRectF(10 * u, 10 * u, 5 * u, 5 * u), 1.2 * u, 1.2 * u)
    elif kind == "diagnostics":
        painter.drawLine(round(2.5 * u), round(9.5 * u), round(5.5 * u), round(9.5 * u))
        painter.drawLine(round(5.5 * u), round(9.5 * u), round(7.5 * u), round(4.5 * u))
        painter.drawLine(round(7.5 * u), round(4.5 * u), round(10.5 * u), round(13.5 * u))
        painter.drawLine(round(10.5 * u), round(13.5 * u), round(12.5 * u), round(9.5 * u))
        painter.drawLine(round(12.5 * u), round(9.5 * u), round(15.5 * u), round(9.5 * u))
    elif kind == "settings":
        painter.drawEllipse(QRectF(6.2 * u, 6.2 * u, 5.6 * u, 5.6 * u))
        spokes = (
            (0, -6),
            (0, 6),
            (-6, 0),
            (6, 0),
            (-4.2, -4.2),
            (4.2, 4.2),
            (-4.2, 4.2),
            (4.2, -4.2),
        )
        for dx, dy in spokes:
            painter.drawLine(
                round((9 + dx * 0.58) * u),
                round((9 + dy * 0.58) * u),
                round((9 + dx * 0.92) * u),
                round((9 + dy * 0.92) * u),
            )
    elif kind == "search":
        painter.drawEllipse(QRectF(3 * u, 3 * u, 8.5 * u, 8.5 * u))
        painter.drawLine(round(10.3 * u), round(10.3 * u), round(15 * u), round(15 * u))
    elif kind == "refresh":
        painter.drawArc(QRectF(3.2 * u, 3.2 * u, 11.6 * u, 11.6 * u), 35 * 16, 285 * 16)
        painter.drawLine(round(12.2 * u), round(3.0 * u), round(14.8 * u), round(5.2 * u))
        painter.drawLine(round(14.8 * u), round(5.2 * u), round(11.6 * u), round(6.6 * u))
    painter.end()
    pixmap.setDevicePixelRatio(dpr)
    return QIcon(pixmap)


def ensure_arrow_icon(direction: str, color: str) -> str:
    """Return path to a crisp 2x antialiased chevron PNG for QSS subcontrols."""
    safe_color = re.sub(r"[^a-zA-Z0-9]", "", color.lower()) or "fg"
    cache_dir = Path(tempfile.gettempdir()) / "omnicore-ui-icons"
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"chevron-{direction}-{safe_color}.png"
    if not target.exists():
        size = 24
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(color), 3.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        if direction == "up":
            painter.drawLine(6, 15, 12, 9)
            painter.drawLine(12, 9, 18, 15)
        else:
            painter.drawLine(6, 9, 12, 15)
            painter.drawLine(12, 15, 18, 9)
        painter.end()
        pixmap.save(str(target), "PNG")
    return target.as_posix()


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
        available = max(24, text_rect.width() - 6)
        option.currentText = self.fontMetrics().elidedText(
            self.currentText(), Qt.ElideMiddle, available
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
        self._context_generation = 0
        self.engines = []
        self.is_connected = False
        self._connection_key = "connecting"
        self._closing = False
        self._allow_close = False
        self._pending_import = None
        self._health_pending = set()
        self._backend_pid = None
        self._last_error_meta = None
        self._theme_colors = ("#ecf1f9", "#8b80f9", "#000000")
        self.resource_monitor = ResourceMonitor(self._resource_root_pids, interval_seconds=2.0)
        self.resource_monitor.updated.connect(self._apply_resource_snapshot)
        if hasattr(session, "ready"):
            session.ready.connect(self._sync_backend_pid)
        if hasattr(session, "stopped"):
            session.stopped.connect(self._sync_backend_pid)
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
        self.width_save_timer.timeout.connect(self._fill_conversations)
        self.shell.splitterMoved.connect(self.sidebar_dragged)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.side_layout = QVBoxLayout(self.sidebar)
        self.side_layout.setContentsMargins(8, 12, 8, 12)
        self.brand = QLabel("◈  OmniCore")
        self.brand.setObjectName("brand")
        self.sidebar_header = QHBoxLayout()
        self.sidebar_header.setContentsMargins(0, 0, 0, 0)
        self.sidebar_header.addWidget(self.brand, 1)
        self.side_layout.addLayout(self.sidebar_header)
        self.sidebar_toggle = QPushButton()
        self.sidebar_toggle.setObjectName("sidebarToggle")
        self.sidebar_toggle.setCursor(Qt.PointingHandCursor)
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)
        self.sidebar_toggle.setFixedSize(32, 32)
        self.sidebar_header.addWidget(self.sidebar_toggle)
        self.nav = []
        for index, key in enumerate(("chat", "models", "settings", "diagnostics")):
            button = self.button(key, lambda checked=False, i=index: self.navigate(i))
            button.setCheckable(True)
            button.setObjectName("nav")
            self.nav.append(button)
        self._history_search_open = False
        self.conversations_row = QHBoxLayout()
        self.conversations_row.setContentsMargins(0, 0, 0, 0)
        self.conversations_row.setSpacing(4)
        self.conversations_row.addWidget(self.nav[0], 1)
        self.history_search = QLineEdit()
        self.history_search.setMaxLength(256)
        self.history_search.setClearButtonEnabled(True)
        self.history_search.installEventFilter(self)
        self.history_search.hide()
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.refresh_conversations)
        self.history_search.textChanged.connect(lambda _: self.search_timer.start())
        self.history_search_close = QPushButton("✕")
        self.history_search_close.setObjectName("historyHeaderButton")
        self.history_search_close.clicked.connect(self.close_history_search)
        self.history_search_close.hide()
        self.conversations_row.addWidget(self.history_search, 1)
        self.conversations_row.addWidget(self.history_search_close)
        self.side_layout.addLayout(self.conversations_row)
        self.side_layout.addWidget(self.nav[1])
        self.shell.addWidget(self.sidebar)
        main = QWidget()
        self.body_layout = QVBoxLayout(main)
        body = self.body_layout
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
        self.resource_monitor_btn = QPushButton(
            format_resource_summary(ResourceSnapshot(), self.tr)
        )
        self.resource_monitor_btn.setObjectName("resourceMonitorBtn")
        self.resource_monitor_btn.setCheckable(True)
        self.resource_monitor_btn.setCursor(Qt.PointingHandCursor)
        self.resource_monitor_btn.setToolTip(self.tr("resources_tooltip"))
        self.resource_monitor_btn.setAccessibleName(self.tr("resources_label"))
        self.resource_monitor_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        body.addLayout(header)
        resource_row = QHBoxLayout()
        resource_row.setContentsMargins(0, 0, 0, 0)
        resource_row.addWidget(self.resource_monitor_btn)
        resource_row.addStretch(1)
        body.addLayout(resource_row)
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
        body.addWidget(self.resource_details_frame)

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
        body.addWidget(self.notice_card)
        self._sync_backend_pid()
        self.resource_monitor.start()
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
        self.compact_spacer.setObjectName("compactSpacer")
        self.compact_spacer.setStyleSheet("background: transparent;")
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
        left.setSpacing(6)
        self.history_toolbar = QHBoxLayout()
        self.history_toolbar.setContentsMargins(0, 0, 0, 2)
        self.history_toolbar.setSpacing(6)
        self.history_search_toggle = QPushButton()
        self.history_search_toggle.setObjectName("historySearchTrigger")
        self.history_search_toggle.setCursor(Qt.PointingHandCursor)
        self.history_search_toggle.clicked.connect(self.open_history_search)
        self.history_refresh = QPushButton()
        self.history_refresh.setObjectName("historyHeaderButton")
        self.history_refresh.setCursor(Qt.PointingHandCursor)
        self.history_refresh.clicked.connect(self.refresh_shared_history)
        self.history_menu_btn = QPushButton("⋯")
        self.history_menu_btn.setObjectName("historyHeaderButton")
        self.history_menu_btn.setCursor(Qt.PointingHandCursor)
        self.history_menu_btn.clicked.connect(self.open_history_menu)
        self.history_toolbar.addWidget(self.history_search_toggle, 1)
        self.history_toolbar.addWidget(self.history_refresh)
        self.history_toolbar.addWidget(self.history_menu_btn)
        left.addLayout(self.history_toolbar)
        self.sidebar_width = QSpinBox()
        self.sidebar_width.setRange(200, 360)
        self.sidebar_width.setValue(self.config.sidebar_width)
        self.sidebar_width.setSuffix(" px")
        self.sidebar_width.valueChanged.connect(self.resize_sidebar)
        self.new_button = self.button("new_chat", self.new_conversation, primary=True)
        left.addWidget(self.new_button)
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
        chat.setSpacing(10)
        self.chat_title = QLabel(self.tr("new_chat"))
        self.chat_title.setObjectName("chatTitle")
        self.chat_title.setTextFormat(Qt.PlainText)
        self.chat_title.setMinimumWidth(80)
        self.chat_title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.model_combo = ModelComboBox()
        self.model_combo.setMinimumWidth(180)
        self.model_combo.setMaximumWidth(560)
        self.model_combo.setMinimumContentsLength(18)
        self.model_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.model_combo.currentIndexChanged.connect(self.model_selected)
        self.chat_header = self.row(self.chat_title, self.model_combo)
        self.chat_header.setStretch(0, 1)
        self.context_button = QPushButton("⚙")
        self.context_button.setFixedWidth(34)
        self.context_button.setCheckable(True)
        self.chat_refresh = QPushButton("↻")
        self.chat_refresh.setFixedWidth(34)
        self.chat_refresh.clicked.connect(self.refresh_models)
        self.chat_header.addWidget(self.context_button)
        self.chat_header.addWidget(self.chat_refresh)
        chat.addLayout(self.chat_header)
        self.context_controls = QFrame()
        self.context_controls.setObjectName("contextCard")
        context_layout = QVBoxLayout(self.context_controls)
        context_layout.setContentsMargins(12, 10, 12, 10)
        context_layout.setSpacing(6)
        self.context_controls.hide()
        self.context_button.toggled.connect(lambda _checked=False: self._sync_mode_settings())
        chat.addWidget(self.context_controls)
        self.context_label = self.label("context_label")
        self.context_preset = QComboBox()
        self.context_preset.setAccessibleName(self.tr("context_configure"))
        self._populate_context_presets(1_000_000)
        self.context_preset.currentIndexChanged.connect(self._context_preset_changed)
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
        self.context_tokens.valueChanged.connect(self._sync_context_preset)
        self.context_save = self.button("context_save", self.save_model_context)
        context_layout.addLayout(
            self.row(
                self.context_label,
                self.context_preset,
                self.context_mode,
                self.context_tokens,
                self.context_save,
            )
        )
        self.context_status = QLabel()
        self.context_status.setWordWrap(True)
        self.context_slider = QSlider(Qt.Horizontal)
        self.context_slider.setRange(0, 1000)
        self.context_slider.setAccessibleName(self.tr("context_configure"))
        self.context_slider.valueChanged.connect(self.context_slider_changed)
        self.context_tokens.valueChanged.connect(self.sync_context_slider)
        context_layout.addWidget(self.context_slider)
        context_layout.addWidget(self.context_status)
        self.agent_panel = AgentPanel(self)
        self.agent_panel.setMaximumWidth(840)
        self.chat_header.insertWidget(2, self.agent_panel.mode)
        self.agent_panel.mode.currentIndexChanged.connect(
            lambda _index=0: self._sync_mode_settings()
        )
        agent_row = QHBoxLayout()
        agent_row.setContentsMargins(0, 0, 0, 0)
        agent_row.addStretch(1)
        agent_row.addWidget(self.agent_panel, 100)
        agent_row.addStretch(1)
        chat.addLayout(agent_row)
        self.transcript = ChatTranscript()
        self.transcript.regenerate_requested.connect(self.regenerate_answer)
        self.transcript.grant_folder_requested.connect(self.agent_panel.grant_folder)
        self.transcript.continue_run_requested.connect(self.agent_panel.continue_run)
        chat.addWidget(self.transcript, 1)
        self.composer_wrap = QWidget()
        self.composer_wrap.setMaximumWidth(840)
        wrap_layout = QVBoxLayout(self.composer_wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.setSpacing(6)
        self.composer_box = QFrame()
        self.composer_box.setObjectName("composerBox")
        box_layout = QVBoxLayout(self.composer_box)
        box_layout.setContentsMargins(10, 8, 10, 8)
        box_layout.setSpacing(6)
        self.composer = Composer()
        self.composer.submitted.connect(self.send_message)
        self.composer.setObjectName("composer")
        box_layout.addWidget(self.composer)
        self.generation_status = self.label("ready")
        self.generation_status.setObjectName("mutedMeta")
        self.generation_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
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
        self.send_button = self.button("send", self.send_message, primary=True)
        self.stop_button = self.button("stop", self.stop_generation)
        self.stop_button.setEnabled(False)
        self.stop_button.hide()
        self.stop_button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.send_button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(4, 0, 4, 0)
        meta_row.setSpacing(8)
        meta_row.addWidget(self.context_usage, 1)
        meta_row.addWidget(self.context_meter)
        meta_row.addWidget(self.context_toggle)
        actions = QHBoxLayout()
        actions.setContentsMargins(4, 0, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(self.generation_status, 1)
        actions.addWidget(self.stop_button)
        actions.addWidget(self.send_button)
        box_layout.addLayout(actions)
        wrap_layout.addWidget(self.composer_box)
        wrap_layout.addLayout(meta_row)
        wrap_layout.addWidget(self.context_details)
        composer_row = QHBoxLayout()
        composer_row.setContentsMargins(0, 0, 0, 0)
        composer_row.addStretch(1)
        composer_row.addWidget(self.composer_wrap, 100)
        composer_row.addStretch(1)
        chat.addLayout(composer_row)
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
        self.scan_button = self.button("scan_models", self.scan_models)
        local.addLayout(
            self.row(
                self.button("import_gguf", self.choose_gguf, primary=True),
                self.scan_button,
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
        local.addLayout(
            self.row(self.model_search, self.engine_filter, self.model_sort, self.favorites_only)
        )
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
        outer = QWidget()
        outer_layout = QHBoxLayout(outer)
        outer_layout.setContentsMargins(0, 8, 0, 24)
        outer_layout.addStretch(1)
        self.settings_container = QWidget()
        self.settings_container.setMaximumWidth(850)
        outer_layout.addWidget(self.settings_container, 10)
        outer_layout.addStretch(1)
        container_layout = QVBoxLayout(self.settings_container)
        container_layout.setContentsMargins(0, 8, 0, 8)
        container_layout.setSpacing(14)

        def make_card():
            card = QFrame()
            card.setObjectName("settingsCard")
            card_form = QFormLayout(card)
            card_form.setContentsMargins(20, 18, 20, 18)
            card_form.setHorizontalSpacing(18)
            card_form.setVerticalSpacing(14)
            card_form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
            container_layout.addWidget(card)
            return card_form

        def compact_row(*widgets):
            box = QHBoxLayout()
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(10)
            for w in widgets:
                box.addWidget(w)
            box.addStretch(1)
            return box

        appearance_form = make_card()
        self.language = QComboBox()
        self.language.addItem("Polski", "pl-PL")
        self.language.addItem("English", "en-US")
        self.language.setCurrentIndex(self.language.findData(self.config.locale))
        self.language.currentIndexChanged.connect(self.preview_language)
        appearance_form.addRow(self.label("language"), self.language)
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
        appearance_form.addRow(self.label("theme"), self.theme)
        self.ui_scale = QSpinBox()
        self.ui_scale.setRange(80, 150)
        self.ui_scale.setSingleStep(10)
        self.ui_scale.setSuffix(" %")
        self.ui_scale.setValue(self.config.ui_scale)
        self.ui_scale.valueChanged.connect(self.change_ui_scale)
        appearance_form.addRow(self.label("ui_scale"), self.ui_scale)
        appearance_form.addRow(self.label("sidebar_width"), self.sidebar_width)
        self.accent_button = self.button("accent", self.choose_accent)
        appearance_form.addRow(
            compact_row(self.accent_button, self.button("accent_default", self.reset_accent))
        )

        engine_form = make_card()
        self.device = QComboBox()
        for key in ("auto", "cpu", "cuda"):
            self.device.addItem(self.tr("mode_" + key), key)
        selected = self.config.parameters.get("device", "auto")
        if selected not in {"auto", "cpu", "cuda"}:
            self.device.addItem(selected, selected)
        self.device.setCurrentIndex(self.device.findData(selected))
        engine_form.addRow(self.label("execution_mode"), self.device)
        self.gpu_offload_mode = QComboBox()
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
        self.engine_summary = self.label("detecting_engines")
        engine_form.addRow(self.engine_summary)
        self.advanced_toggle = self.button("advanced_settings", lambda: None)
        self.advanced_toggle.setCheckable(True)
        engine_form.addRow(
            compact_row(
                self.button("detect_engines", self.refresh_diagnostics),
                self.advanced_toggle,
            )
        )

        self.advanced_settings = QFrame()
        self.advanced_settings.setObjectName("settingsCard")
        self.advanced_toggle.toggled.connect(self.advanced_settings.setVisible)
        container_layout.addWidget(self.advanced_settings)
        self.advanced_settings.hide()
        form = QFormLayout(self.advanced_settings)
        form.setContentsMargins(20, 18, 20, 18)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(14)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.roots = QListWidget()
        self.roots.setMaximumHeight(100)
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
        form.addRow(self.label("cuda_hint"))
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
            box.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            form.addRow(self.label(key), box)
            self.parameter_inputs[key] = box
        self.device.currentIndexChanged.connect(self.execution_mode_changed)
        self.gpu_offload_mode.currentIndexChanged.connect(self.offload_mode_changed)
        self._sync_offload_controls()
        self.thinking = QCheckBox(self.tr("thinking"))
        self.thinking.setChecked(self.config.parameters.get("thinking", False))
        self._texts.append((self.thinking, "thinking"))
        form.addRow(self.thinking)
        self.system_prompt = QPlainTextEdit(self.config.parameters.get("system_prompt", ""))
        self.system_prompt.setMaximumHeight(100)
        form.addRow(self.label("system_prompt"), self.system_prompt)

        footer_form = make_card()
        footer_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        footer_form.addRow(self.label("settings_hint"))
        footer_form.addRow(compact_row(self.button("save", self.save_settings, primary=True)))
        self.about = QLabel()
        self.about.setWordWrap(True)
        self.about.setTextInteractionFlags(Qt.TextSelectableByMouse)
        footer_form.addRow(self.about)
        self.updates = UpdatePanel(self.config, self.tr, self)
        footer_form.addRow(self.updates)
        container_layout.addStretch(1)
        scroll.setWidget(outer)
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
        if (
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

    def _sync_mode_settings(self):
        agent_mode = self.agent_panel.mode.currentData() == "agent"
        open_settings = self.context_button.isChecked()
        self.context_controls.setVisible(open_settings)
        self.agent_panel.settings_toggle.blockSignals(True)
        self.agent_panel.settings_toggle.setChecked(open_settings and agent_mode)
        self.agent_panel.settings_toggle.blockSignals(False)
        self.agent_panel.visibility()
        tip = (
            self.agent_panel.settings_toggle.text() if agent_mode else self.tr("context_configure")
        )
        self.context_button.setToolTip(tip)
        self.context_button.setAccessibleName(tip)

    def sidebar_dragged(self, position, index):
        if self.config.sidebar_compact:
            return
        self.config.sidebar_width = max(200, min(360, self.sidebar.width()))
        self._apply_sidebar()
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

    def _apply_scaled_metrics(self):
        icon_btn = self._scaled(34)
        icon_font = self._scaled(16)
        icon_style = f"padding: 0; text-align: center; font-size: {icon_font}px;"
        for widget in (
            self.history_search_toggle,
            self.history_refresh,
            self.history_menu_btn,
            self.history_search_close,
            self.context_button,
            self.chat_refresh,
        ):
            widget.setFixedSize(icon_btn, icon_btn)
            widget.setStyleSheet(icon_style)
        self.agent_panel.mode.setFixedWidth(self._scaled(108))
        self.agent_panel.mode.setFixedHeight(self._scaled(34))
        self.model_combo.setFixedHeight(self._scaled(34))
        self.model_actions.setFixedSize(self._scaled(32), self._scaled(32))
        self._sync_model_combo_width()
        self.composer_wrap.setMaximumWidth(self._scaled(840))
        self.agent_panel.setMaximumWidth(self._scaled(840))
        self.settings_container.setMaximumWidth(self._scaled(850))
        self.context_meter.setMaximumWidth(self._scaled(90))
        self.body_layout.setContentsMargins(
            self._scaled(24), self._scaled(16), self._scaled(24), self._scaled(16)
        )

    def _sync_model_combo_width(self):
        if not hasattr(self, "model_combo"):
            return
        compact_w = self._scaled(60)
        expanded_w = self._scaled(getattr(self.config, "sidebar_width", 260))
        sidebar_w = compact_w if self.config.sidebar_compact else expanded_w
        pane_w = max(self._scaled(420), self.width() - sidebar_w - self._scaled(56))
        reserved = self._scaled(108 + 34 + 34 + 150)
        available = max(self._scaled(160), pane_w - reserved)
        max_cap = min(self._scaled(640), available)
        fm = self.model_combo.fontMetrics()
        widest_item = max(
            (
                fm.horizontalAdvance(self.model_combo.itemText(i))
                for i in range(self.model_combo.count())
            ),
            default=0,
        )
        needed = widest_item + self._scaled(54) if widest_item > 0 else self._scaled(240)
        min_w = min(self._scaled(180), max_cap)
        target_max = max(min_w, min(max_cap, needed))
        self.model_combo.setMinimumWidth(min_w)
        self.model_combo.setMaximumWidth(target_max)

    def _sync_model_combo_tooltip(self):
        if hasattr(self, "model_combo"):
            self.model_combo.setToolTip(self.model_combo.currentText() or "")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_model_combo_width()

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
        if hasattr(self, "resource_monitor_btn"):
            self.resource_monitor_btn.setText(format_resource_summary(snap, self.tr))
            self.resource_monitor_btn.setToolTip(self.tr("resources_tooltip"))
            self.resource_monitor_btn.setAccessibleName(self.tr("resources_label"))
            self.resource_monitor_btn.updateGeometry()
        if hasattr(self, "resource_details_label"):
            self.resource_details_label.setText(format_resource_details(snap, self.tr))

    def _apply_resource_snapshot(self, snapshot):
        if self._closing or not isinstance(snapshot, ResourceSnapshot):
            return
        self._render_resource_widgets(snapshot)

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
        self.notice_details_toggle.setChecked(False)
        self.notice_details_toggle.hide()
        self.notice_details_frame.hide()
        self.notice.hide()
        self.notice_card.hide()

    def _apply_sidebar(self):
        compact = self.config.sidebar_compact
        compact_width = self._scaled(60)
        btn_size = self._scaled(38)
        icon_px = self._scaled(19 if compact else 14)
        fg, accent, accent_text = self._theme_colors
        margin_h = max(4, (compact_width - 1 - btn_size) // 2) if compact else self._scaled(8)
        margin_v = self._scaled(10 if compact else 12)
        self.side_layout.setContentsMargins(margin_h, margin_v, margin_h, margin_v)
        self.side_layout.setSpacing(self._scaled(6))
        self.sidebar.setProperty("compact", compact)
        self.sidebar.style().unpolish(self.sidebar)
        self.sidebar.style().polish(self.sidebar)
        self.sidebar_header.setSpacing(0 if compact else self._scaled(6))
        self.side_layout.setAlignment(
            self.sidebar_header, Qt.AlignHCenter if compact else Qt.Alignment()
        )
        toggle_size = btn_size if compact else self._scaled(32)
        toggle_icon = self._scaled(19 if compact else 16)
        header_btn = self._scaled(30)
        header_icon = self._scaled(15)
        row_gap = self._scaled(6)
        sidebar_w = compact_width if compact else max(200, min(360, self.config.sidebar_width))
        self.history_toolbar.setSpacing(row_gap)
        self.history_toolbar.setContentsMargins(0, 0, 0, self._scaled(4))
        self.history_search_toggle.setIcon(sidebar_icon("search", fg, header_icon))
        self.history_search_toggle.setIconSize(QSize(header_icon, header_icon))
        self.history_refresh.setFixedSize(header_btn, header_btn)
        self.history_refresh.setText("")
        self.history_refresh.setIcon(sidebar_icon("refresh", fg, header_icon))
        self.history_refresh.setIconSize(QSize(header_icon, header_icon))
        self.history_menu_btn.setFixedSize(header_btn, header_btn)
        self.history_search_close.setFixedSize(header_btn, header_btn)
        if not compact:
            toolbar_avail = max(
                header_btn, sidebar_w - 2 * margin_h - 2 * header_btn - 2 * row_gap - 2
            )
            self.history_search_toggle.setMinimumSize(0, 0)
            self.history_search_toggle.setMaximumSize(16777215, header_btn)
            self.history_search_toggle.setFixedHeight(header_btn)
            self.history_search_toggle.setText(self.tr("search_short"))
            self.history_search_toggle.ensurePolished()
            if self.history_search_toggle.minimumSizeHint().width() > toolbar_avail:
                self.history_search_toggle.setText("")
                self.history_search_toggle.setFixedSize(header_btn, header_btn)
            else:
                self.history_search_toggle.setMinimumWidth(header_btn)
        search_open = not compact and self._history_search_open
        self.nav[0].setVisible(compact or not search_open)
        self.history_search_toggle.setVisible(not compact and not search_open)
        self.history_refresh.setVisible(not compact)
        self.history_menu_btn.setVisible(not compact)
        self.history_search.setVisible(search_open)
        self.history_search_close.setVisible(search_open)
        self.conversations_row.setSpacing(0 if compact else self._scaled(4))
        self.conversations_row.setAlignment(Qt.AlignHCenter if compact else Qt.Alignment())
        self.sidebar_toggle.setFixedSize(toggle_size, toggle_size)
        self.sidebar_toggle.setStyleSheet("")
        self.sidebar_toggle.setText("")
        self.sidebar_toggle.setIcon(
            sidebar_icon("expand" if compact else "collapse", fg, toggle_icon)
        )
        self.sidebar_toggle.setIconSize(QSize(toggle_icon, toggle_icon))
        self._sync_model_combo_width()
        self.sidebar.setSizePolicy(
            QSizePolicy.Fixed if compact else QSizePolicy.Preferred, QSizePolicy.Expanding
        )
        self.sidebar.setMinimumWidth(compact_width if compact else 200)
        self.sidebar.setMaximumWidth(compact_width if compact else 360)
        if self.shell.count() > 1:
            handle_w = 1 if compact else 4
            self.shell.setHandleWidth(handle_w)
            width = compact_width if compact else max(200, min(360, self.config.sidebar_width))
            self.shell.setSizes([width, max(1, self.width() - width - handle_w)])
            self.shell.handle(1).setEnabled(not compact)
        self.brand.setVisible(not compact)
        self.sidebar_toggle.setToolTip(self.tr("sidebar_expand" if compact else "sidebar_collapse"))
        self.sidebar_width.setToolTip(self.tr("sidebar_width"))
        self.history_search_toggle.setToolTip(self.tr("search_history"))
        self.history_search_toggle.setAccessibleName(self.tr("search_history"))
        self.history_search_close.setToolTip(self.tr("cancel"))
        self.history_search_close.setAccessibleName(self.tr("cancel"))
        self.history_refresh.setToolTip(self.tr("refresh"))
        self.history_refresh.setAccessibleName(self.tr("refresh"))
        self.history_menu_btn.setToolTip(self.tr("history_menu"))
        self.history_menu_btn.setAccessibleName(self.tr("history_menu"))
        self.history_panel.setVisible(not compact)
        self.compact_spacer.setVisible(compact)
        for button, key in zip(
            (self.new_button, *self.nav),
            ("new_chat", "conversations_nav", "models", "settings", "diagnostics"),
            strict=True,
        ):
            icon_color = accent_text if key == "new_chat" else accent if button.isChecked() else fg
            button.setIcon(sidebar_icon(key, icon_color, icon_px))
            button.setIconSize(QSize(icon_px, icon_px))
            button.setToolTip(self.tr(key))
            button.setAccessibleName(self.tr(key))
            if compact:
                button.setFixedSize(btn_size, btn_size)
                button.setStyleSheet("")
                button.setText("")
                if button is not self.nav[0]:
                    self.side_layout.setAlignment(button, Qt.AlignHCenter)
            else:
                button.setMinimumSize(0, 0)
                button.setMaximumSize(16777215, 16777215)
                button.setStyleSheet("")
                if button is not self.nav[0]:
                    self.side_layout.setAlignment(button, Qt.Alignment())
                button.ensurePolished()
                if button is self.nav[0]:
                    avail_nav0 = max(48, sidebar_w - 2 * margin_h - 4)
                    label_text = self.tr(key)
                    button.setText(label_text)
                    hint_w = button.minimumSizeHint().width()
                    if hint_w > avail_nav0:
                        text_budget = max(
                            16,
                            button.fontMetrics().horizontalAdvance(label_text)
                            - (hint_w - avail_nav0)
                            - 2,
                        )
                        button.setText(
                            button.fontMetrics().elidedText(label_text, Qt.ElideRight, text_budget)
                        )
                else:
                    button.setText(
                        sidebar_text(
                            self.tr(key),
                            button.fontMetrics(),
                            max(48, sidebar_w - self._scaled(48)),
                        )
                    )

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        self.page_title.setText(self.tr(("chat", "models", "settings", "diagnostics")[index]))
        for i, button in enumerate(self.nav):
            button.setChecked(i == index)
        self._apply_sidebar()
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
        self._update_chat_title()
        self.composer.setPlaceholderText(self.tr("composer"))
        self.history_search.setPlaceholderText(self.tr("search_history"))
        self.context_mode.setItemText(0, self.tr("context_auto"))
        self.context_mode.setItemText(1, self.tr("context_manual"))
        if hasattr(self, "context_preset"):
            self._populate_context_presets(self.context_tokens.maximum())
        self._render_model_context()
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
        down_icon = ensure_arrow_icon("down", fg)
        down_muted = ensure_arrow_icon("down", muted)
        up_icon = ensure_arrow_icon("up", fg)
        up_muted = ensure_arrow_icon("up", muted)
        from PySide6.QtGui import QPalette

        qt_palette = QPalette()
        for role, hex_color in (
            (QPalette.Window, bg),
            (QPalette.WindowText, fg),
            (QPalette.Base, panel),
            (QPalette.AlternateBase, field),
            (QPalette.Text, fg),
            (QPalette.Button, field),
            (QPalette.ButtonText, fg),
            (QPalette.Highlight, field),
            (QPalette.HighlightedText, accent),
            (QPalette.ToolTipBase, panel),
            (QPalette.ToolTipText, fg),
            (QPalette.PlaceholderText, muted),
        ):
            qt_palette.setColor(role, QColor(hex_color))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            qt_palette.setColor(QPalette.Disabled, role, QColor(muted))
        QApplication.instance().setPalette(qt_palette)
        stylesheet = f"""
            QMainWindow,
            QDialog, QMessageBox, QMenu, QWidget {{ background: {bg};
                color: {fg};
                font: 14px 'Sans Serif';
                }}
            QFrame#sidebar {{ background: {panel};
                border-right: 1px solid {border};
                }}
            QLabel {{ background: transparent;
                }}
            QLabel#brand {{ font-size: 20px;
                font-weight: 700;
                color: {accent};
                }}
            QWidget#compactSpacer {{ background: transparent;
                }}
            QLabel#title {{ font-size: 24px;
                font-weight: 650;
                padding: 2px 0;
                }}
            QLabel#chatTitle {{ font-size: 16px;
                font-weight: 600;
                }}
            QLabel#mutedMeta {{ color: {muted};
                font-size: 12px;
                }}
            QFrame#contextCard, QFrame#agentCard, QFrame#settingsCard {{ background: {panel};
                border: 1px solid {border};
                border-radius: 12px;
                }}
            QFrame#composerBox {{ background: {panel};
                border: 1px solid {border};
                border-radius: 14px;
                }}
            QFrame#composerBox QPlainTextEdit#composer {{ background: transparent;
                border: none;
                padding: 2px 4px;
                }}
            QPushButton#compactToggle {{ background: transparent;
                border: 1px solid {border};
                border-radius: 7px;
                padding: 4px 10px;
                font-size: 12px;
                color: {muted};
                }}
            QPushButton#compactToggle:hover, QPushButton#compactToggle:checked {{
                color: {accent};
                border-color: {accent};
                }}
            QLabel#badge {{ color: {accent};
                padding: 8px 12px;
                background: {field};
                border-radius: 12px;
                }}
            QFrame#noticeCard {{ background: {field};
                border: 1px solid {border};
                border-left: 3px solid {accent};
                border-radius: 8px;
                padding: 4px;
                }}
            QFrame#noticeCard[kind="error"] {{
                border-left: 3px solid #d9534f;
                }}
            QLabel#notice {{ background: transparent;
                border: none;
                padding: 0px;
                color: {fg};
                }}
            QPushButton#errorDetailsToggle, QPushButton#resourceMonitorBtn {{
                background: {panel};
                color: {muted};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 4px 10px;
                font-size: {self._scaled(12)}px;
                }}
            QPushButton#errorDetailsToggle:hover, QPushButton#resourceMonitorBtn:hover {{
                color: {fg};
                border-color: {accent};
                }}
            QPushButton#errorDetailsToggle:checked, QPushButton#resourceMonitorBtn:checked {{
                color: {fg};
                border-color: {accent};
                background: {field};
                }}
            QToolButton#noticeClose {{
                background: transparent;
                border: none;
                color: {muted};
                padding: 2px 6px;
                font-size: {self._scaled(14)}px;
                }}
            QToolButton#noticeClose:hover {{
                color: {fg};
                }}
            QFrame#errorCard {{
                background: {panel};
                border: 1px solid {border};
                border-left: 3px solid #d9534f;
                border-radius: 8px;
                padding: 8px 10px;
                }}
            QFrame#errorDetailsBox, QFrame#messageStatsDetails, QFrame#resourceDetails {{
                background: {panel};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 6px 10px;
                }}
            QLabel#agentRunError {{
                color: {fg};
                font-weight: 600;
                }}
            QPushButton {{ background: {field};
                border: 1px solid {border};
                border-radius: 9px;
                padding: 10px 14px;
                font-weight: 550;
                }}
            QWidget#historyGroupRow {{ background: {panel}; border-radius: 6px; }}
            QWidget#historyTitleRow {{ background: {panel}; border-radius: 6px; }}
            QWidget#historyTitleRow[selected="true"] {{ background: {field}; }}
            QPushButton#historyHeaderButton {{
                background: transparent; border: 1px solid {border};
                border-radius: 8px; padding: 0; color: {muted}; }}
            QPushButton#historyHeaderButton:hover {{ background: {field}; border-color: {accent};
                color: {fg}; }}
            QPushButton#historySearchTrigger {{
                background: {field}; border: 1px solid {border}; border-radius: 8px;
                padding: 4px 10px; color: {muted}; text-align: left; font-weight: 450; }}
            QPushButton#historySearchTrigger:hover {{ border-color: {accent}; color: {fg}; }}
            QLabel#historyItemTitle {{ background: transparent; color: {fg}; }}
            QLabel#historyItemTitle[selected="true"] {{ color: {accent}; }}
            QPushButton#historyHeading {{ background: transparent; border: none;
                border-radius: 5px; padding: 4px 6px; text-align: left; font-size: 11px;
                font-weight: 600; color: {muted}; }}
            QPushButton#historyHeading:hover {{ color: {fg}; }}
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
            QFrame#sidebar QPushButton#primary {{ padding: 9px 6px; }}
            QPushButton#sidebarToggle {{ background: transparent;
                border: 1px solid transparent;
                border-radius: 9px;
                padding: 0;
                }}
            QPushButton#sidebarToggle:hover {{ background: {field};
                border-color: {border};
                }}
            QPushButton#nav {{ text-align: left;
                padding: 10px 6px;
                border: 1px solid transparent;
                border-radius: 9px;
                background: transparent;
                }}
            QPushButton#nav:hover {{ background: {field};
                border-color: {border};
                }}
            QPushButton#nav:checked {{ color: {accent};
                background: {field};
                border-color: {border};
                }}
            QFrame#sidebar[compact="true"] QPushButton#nav,
            QFrame#sidebar[compact="true"] QPushButton#primary,
            QFrame#sidebar[compact="true"] QPushButton#sidebarToggle {{ padding: 0;
                border-radius: 9px;
                text-align: center;
                }}
            QFrame#sidebar[compact="true"] QPushButton#nav:checked {{ border-color: {accent};
                }}
            QComboBox#agentMode {{ border-color: {accent};
                font-weight: 600;
                }}
            QLineEdit, QPlainTextEdit, QTextBrowser, QListWidget, QTableWidget,
            QColorDialog {{
                background: {panel};
                border: 1px solid {border};
                border-radius: 9px;
                padding: 8px;
                selection-background-color: {accent};
                }}
            QComboBox, QSpinBox, QDoubleSpinBox {{
                background: {panel};
                color: {fg};
                border: 1px solid {border};
                border-radius: 9px;
                min-height: 20px;
                selection-background-color: {accent};
                selection-color: {accent_text};
                }}
            QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
                background: {field};
                color: {muted};
                }}
            QComboBox {{
                padding: 6px 32px 6px 10px;
                }}
            QComboBox::drop-down {{
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 26px;
                border: none;
                border-left: 1px solid {border};
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
                background: transparent;
                }}
            QComboBox::drop-down:hover {{
                background: {field};
                }}
            QComboBox::down-arrow {{
                image: url("{down_icon}");
                width: 12px;
                height: 12px;
                }}
            QComboBox::down-arrow:disabled {{
                image: url("{down_muted}");
                }}
            QComboBoxPrivateContainer {{
                background: {panel};
                border: 1px solid {border};
                border-radius: 8px;
                }}
            QComboBox QAbstractItemView, QListView {{
                background: {panel};
                color: {fg};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 4px;
                selection-background-color: {field};
                selection-color: {accent};
                outline: none;
                }}
            QComboBox QAbstractItemView::item, QListView::item {{
                padding: 6px 10px;
                min-height: 22px;
                background: transparent;
                color: {fg};
                border-radius: 5px;
                }}
            QComboBox QAbstractItemView::item:hover,
            QComboBox QAbstractItemView::item:selected,
            QListView::item:hover,
            QListView::item:selected {{
                background: {field};
                color: {accent};
                }}
            QSpinBox, QDoubleSpinBox {{
                padding: 6px 28px 6px 10px;
                }}
            QSpinBox::up-button, QDoubleSpinBox::up-button {{
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 22px;
                border: none;
                border-left: 1px solid {border};
                border-bottom: 1px solid {border};
                border-top-right-radius: 8px;
                background: transparent;
                }}
            QSpinBox::down-button, QDoubleSpinBox::down-button {{
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 22px;
                border: none;
                border-left: 1px solid {border};
                border-bottom-right-radius: 8px;
                background: transparent;
                }}
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
                background: {field};
                }}
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
                image: url("{up_icon}");
                width: 10px;
                height: 10px;
                }}
            QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {{
                image: url("{up_muted}");
                }}
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
                image: url("{down_icon}");
                width: 10px;
                height: 10px;
                }}
            QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {{
                image: url("{down_muted}");
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
            QListWidget#conversations {{ background: {panel};
                border: none;
                padding: 0;
                outline: none;
                }}
            QListWidget#conversations::item {{ padding: 0;
                border-radius: 6px;
                margin: 0;
                background: transparent;
                }}
            QListWidget#conversations::item:selected {{ background: transparent; }}
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
            QScrollBar:horizontal {{ height: 10px;
                background: {bg};
                }}
            QScrollBar::handle:horizontal {{ background: {border};
                border-radius: 5px;
                min-width: 32px;
                }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0;
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
                border-radius: 6px;
                padding: 4px 8px;
                }}
            QMenu {{ background: {panel};
                color: {fg};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 4px;
                }}
            QMenu::item {{ padding: 6px 14px;
                border-radius: 6px;
                }}
            QMenu::item:disabled {{ color: {muted};
                }}
            QMenu::item:selected {{ background: {field};
                color: {accent};
                }}
        """
        # Only logical font/control sizes: Qt applies the screen DPR once. Never multiply by
        # devicePixelRatio or modify QT_SCALE_FACTOR / the platform's DPI policy.
        scale = self.config.ui_scale / 100
        stylesheet = re.sub(
            r"(?P<size>\d+)px",
            lambda m: (
                m.group(0) if int(m["size"]) <= 3 else f"{max(1, round(int(m['size']) * scale))}px"
            ),
            stylesheet,
        )
        self._theme_colors = (fg, accent, accent_text)
        self.setStyleSheet(stylesheet)
        self._apply_scaled_metrics()
        self._apply_sidebar()
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
        self._last_error_meta = None
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
        heading_width = max(48, avail_w - self._scaled(20))
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
                    row_h = max(row.minimumSizeHint().height(), row.sizeHint().height())
                    item.setSizeHint(QSize(0, row_h))
                    self.conversation_list.setItemWidget(item, row)
                else:
                    title_row = self._build_history_title_row(title, selected, elide_width)
                    item.setSizeHint(QSize(0, title_row.height()))
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

    def model_selected(self):
        self._sync_model_combo_tooltip()
        self._sync_model_combo_width()
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

    def _context_params_kwargs(self):
        params = self.config.parameters if isinstance(self.config.parameters, dict) else {}
        return {
            "device": params.get("device"),
            "gpu_offload_mode": params.get("gpu_offload_mode"),
        }

    def _render_model_context(self):
        if not hasattr(self, "context_mode"):
            return
        model = self._selected_chat_model()
        busy = bool(self._context_saving or self.active_job or self.agent_panel.active)
        self.context_mode.setEnabled(bool(model) and not busy)
        if hasattr(self, "context_preset"):
            self.context_preset.setEnabled(bool(model) and not busy)
        self.context_save.setEnabled(bool(model) and not busy)
        if not model:
            self.context_tokens.setEnabled(False)
            self.context_status.setText(self.tr("context_choose_model"))
            return
        if self._context_dirty:
            self._context_mode_changed()
            return
        saved = self.model_contexts.get(model["id"]) or context_settings(
            model, **self._context_params_kwargs()
        )
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
        applied = saved.get("applied_tokens")
        text = self.tr("context_configured", tokens=saved["effective_tokens"])
        if applied is not None:
            text += " · " + self.tr("context_applied", tokens=applied)
            if applied != saved["effective_tokens"]:
                text += " · " + self.tr("context_reload")
        else:
            text += " · " + self.tr("context_on_start")
        if saved.get("mode") == "auto" and saved.get("auto_reason") == "safe_fallback":
            text += " · " + self.tr("context_auto_fallback")
        if saved.get("memory_warning"):
            text += " · " + self.tr("context_memory_warning")
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
            self.model_contexts[model_id] = context_settings(
                record, **self._context_params_kwargs()
            )
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
            saved = self.model_contexts.get(model["id"]) or context_settings(
                model, **self._context_params_kwargs()
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
                        context_settings(model, **self._context_params_kwargs())[
                            "effective_tokens"
                        ],
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
                    if (
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
        self.transcript.can_regenerate = bool(
            self.is_connected
            and self.model_combo.currentData()
            and not self.active_job
            and not self._submitting
            and not getattr(getattr(self, "agent_panel", None), "active", None)
        )
        self.transcript.set_messages(messages, self.tr)
        latest = next(
            (m.get("statistics") or {} for m in reversed(messages) if m["role"] == "assistant"), {}
        )
        self.context_details.setText(
            statistics_text(latest, self.tr) or self.tr("context_unavailable")
        )
        used, limit = latest.get("context_used_tokens"), latest.get("context_limit_tokens")
        if used is None and runs and isinstance(runs[0].get("context"), dict):
            used = runs[0]["context"].get("approx_tokens")
            limit = runs[0]["context"].get("limit")
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
            for row in range(self.model_combo.count()):
                if self.model_combo.itemData(row):
                    self.model_combo.setItemData(
                        row, self.model_combo.itemText(row), Qt.ToolTipRole
                    )
            self.model_combo.blockSignals(False)
            self._sync_model_combo_tooltip()
            self._sync_model_combo_width()
            self.refresh_model_table()
            self._render_model_context()
            self._refresh_model_context()
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
