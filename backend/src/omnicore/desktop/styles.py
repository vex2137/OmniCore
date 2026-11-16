"""Design System 2.0 stylesheet generator, crisp vector icons, and UI primitives."""

import os
import re
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QFrame

from omnicore.desktop.themes import ThemeTokens

_ARROW_CACHE: dict[tuple[str, str], str] = {}


def ensure_arrow_icon(direction: str, color: str) -> str:
    """Render a crisp directional arrow PNG cached in a user-private temp dir."""
    key = (direction, color)
    cached = _ARROW_CACHE.get(key)
    if cached and Path(cached).is_file():
        return cached
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    if direction == "up":
        painter.drawPolyline(
            QPolygonF([QPointF(5.5, 15.0), QPointF(12.0, 8.5), QPointF(18.5, 15.0)])
        )
    else:
        painter.drawPolyline(
            QPolygonF([QPointF(5.5, 9.0), QPointF(12.0, 15.5), QPointF(18.5, 9.0)])
        )
    painter.end()
    safe_color = re.sub(r"[^0-9a-fA-F]", "", color) or "fg"
    icon_dir = Path(tempfile.gettempdir()) / f"omnicore-ui-icons-{os.getuid()}"
    icon_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    icon_path = icon_dir / f"arrow-{direction}-{safe_color}.png"
    pixmap.save(str(icon_path), "PNG")
    _ARROW_CACHE[key] = str(icon_path)
    return str(icon_path)


def app_icon(kind: str, color: str, size: int = 18) -> QIcon:
    """Draw sharp geometric 2x HiDPI vector icons for OmniCore's desktop UI."""
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.transparent)
    pixmap.setDevicePixelRatio(2)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), max(1.5, size / 11), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    mid = size / 2
    if kind == "brand":
        outer = QPolygonF(
            [
                QPointF(mid, 1.8),
                QPointF(size - 2.0, mid),
                QPointF(mid, size - 1.8),
                QPointF(2.0, mid),
            ]
        )
        inner = QPolygonF(
            [
                QPointF(mid, 5.4),
                QPointF(size - 5.4, mid),
                QPointF(mid, size - 5.4),
                QPointF(5.4, mid),
            ]
        )
        painter.drawPolygon(outer)
        painter.drawPolygon(inner)
    elif kind == "new_chat":
        r = size * 0.34
        painter.drawLine(QPointF(mid, mid - r), QPointF(mid, mid + r))
        painter.drawLine(QPointF(mid - r, mid), QPointF(mid + r, mid))
    elif kind in {"chat", "conversations_nav"}:
        pad = 2.6
        painter.drawRoundedRect(pad, pad + 0.5, size - pad * 2, size - pad * 2.7, 3.2, 3.2)
        painter.drawLine(QPointF(mid - 3.5, mid - 1.2), QPointF(mid + 3.5, mid - 1.2))
        painter.drawLine(QPointF(mid - 3.5, mid + 1.4), QPointF(mid + 1.8, mid + 1.4))
    elif kind == "models":
        box = size * 0.24
        for x in (mid - box - 1.2, mid + 1.2):
            for y in (mid - box - 1.2, mid + 1.2):
                painter.drawRoundedRect(x, y, box, box, 1.6, 1.6)
    elif kind in {"settings", "sliders"}:
        for idx, offset in enumerate((-3.8, 0.0, 3.8)):
            y = mid + offset
            painter.drawLine(QPointF(2.8, y), QPointF(size - 2.8, y))
            knob_x = mid + (2.5 if idx == 1 else -2.5)
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(knob_x, y), 1.7, 1.7)
            painter.setBrush(Qt.NoBrush)
    elif kind == "diagnostics":
        painter.drawPolyline(
            QPolygonF(
                [
                    QPointF(2.5, mid + 0.8),
                    QPointF(mid - 2.5, mid + 0.8),
                    QPointF(mid - 0.8, 3.5),
                    QPointF(mid + 1.4, size - 3.5),
                    QPointF(mid + 3.0, mid + 0.8),
                    QPointF(size - 2.5, mid + 0.8),
                ]
            )
        )
    elif kind in {"collapse", "expand"}:
        pad = 2.5
        painter.drawRoundedRect(pad, pad + 0.5, size - pad * 2, size - pad * 2 - 1, 2.5, 2.5)
        split_x = pad + (size - pad * 2) * 0.34
        painter.drawLine(QPointF(split_x, pad + 1), QPointF(split_x, size - pad - 1))
        arrow_x = size * 0.66
        dx = -2.4 if kind == "collapse" else 2.4
        painter.drawPolyline(
            QPolygonF(
                [
                    QPointF(arrow_x - dx * 0.5, mid - 2.5),
                    QPointF(arrow_x + dx * 0.6, mid),
                    QPointF(arrow_x - dx * 0.5, mid + 2.5),
                ]
            )
        )
    elif kind == "search":
        radius = size * 0.25
        center = QPointF(size * 0.43, size * 0.43)
        painter.drawEllipse(center, radius, radius)
        edge = radius * 0.72
        painter.drawLine(
            QPointF(center.x() + edge, center.y() + edge),
            QPointF(size - 2.6, size - 2.6),
        )
    elif kind == "refresh":
        r = size * 0.31
        rect = QRectF(mid - r, mid - r, r * 2, r * 2)
        painter.drawArc(rect, 35 * 16, 285 * 16)
        painter.drawPolyline(
            QPolygonF(
                [
                    QPointF(size - 4.4, mid - 4.0),
                    QPointF(size - 2.4, mid - 1.3),
                    QPointF(size - 5.6, mid - 1.0),
                ]
            )
        )
    elif kind == "close":
        r = size * 0.26
        painter.drawLine(QPointF(mid - r, mid - r), QPointF(mid + r, mid + r))
        painter.drawLine(QPointF(mid + r, mid - r), QPointF(mid - r, mid + r))
    elif kind == "menu":
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        for dx in (-4.5, 0.0, 4.5):
            painter.drawEllipse(QPointF(mid + dx, mid), 1.4, 1.4)
    elif kind == "gpu":
        painter.drawRoundedRect(2.4, 4.0, size - 4.8, size - 8.0, 2.5, 2.5)
        painter.drawEllipse(QPointF(size * 0.39, mid), 2.1, 2.1)
        painter.drawEllipse(QPointF(size * 0.66, mid), 2.1, 2.1)
    elif kind == "folder":
        painter.drawPolyline(
            QPolygonF(
                [
                    QPointF(2.4, 5.0),
                    QPointF(mid - 1.0, 5.0),
                    QPointF(mid + 0.8, 7.0),
                    QPointF(size - 2.4, 7.0),
                    QPointF(size - 2.4, size - 3.6),
                    QPointF(2.4, size - 3.6),
                    QPointF(2.4, 5.0),
                ]
            )
        )
    elif kind == "copy":
        s = size * 0.48
        painter.drawRoundedRect(3.2, 5.2, s, s + 1.0, 1.8, 1.8)
        painter.drawPolyline(
            QPolygonF(
                [
                    QPointF(6.2, 5.2),
                    QPointF(6.2, 3.0),
                    QPointF(6.2 + s, 3.0),
                    QPointF(6.2 + s, 4.0 + s),
                    QPointF(3.2 + s, 4.0 + s),
                ]
            )
        )
    elif kind == "info":
        r = size * 0.36
        painter.drawEllipse(QPointF(mid, mid), r, r)
        painter.drawLine(QPointF(mid, mid - 0.6), QPointF(mid, mid + 3.0))
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(mid, mid - 2.9), 1.0, 1.0)
    elif kind == "send":
        painter.drawLine(QPointF(mid, size - 3.5), QPointF(mid, 3.8))
        painter.drawPolyline(
            QPolygonF(
                [
                    QPointF(mid - 3.6, 7.4),
                    QPointF(mid, 3.6),
                    QPointF(mid + 3.6, 7.4),
                ]
            )
        )
    elif kind == "stop":
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        r = size * 0.25
        painter.drawRoundedRect(QRectF(mid - r, mid - r, r * 2, r * 2), 2.0, 2.0)
    painter.end()
    return QIcon(pixmap)


def make_divider(object_name: str = "subtleDivider") -> QFrame:
    """Create a 1px hairline separator conforming to the design system."""
    line = QFrame()
    line.setObjectName(object_name)
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Plain)
    return line


def polish_property(widget, name: str, value) -> None:
    """Update a dynamic Qt property and re-polish its stylesheet match cleanly."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def build_stylesheet(t: ThemeTokens, arrows: dict[str, str], scale: float) -> str:
    """Render the complete Design System 2.0 stylesheet scaled proportionally."""
    down_icon = arrows["down"]
    down_muted = arrows["down_muted"]
    up_icon = arrows["up"]
    up_muted = arrows["up_muted"]

    raw = f"""
        QMainWindow, QDialog, QMessageBox, QMenu, QWidget {{
            background: {t.bg};
            color: {t.fg};
            font: 14px 'Sans Serif';
        }}
        QLabel {{
            background: transparent;
            color: {t.fg};
        }}
        QLabel#title {{
            font-size: 17px;
            font-weight: 650;
            padding: 0;
            color: {t.fg};
        }}
        QLabel#sectionTitle {{
            font-size: 15px;
            font-weight: 650;
            color: {t.fg};
        }}
        QLabel#chatTitle {{
            font-size: 15px;
            font-weight: 600;
            color: {t.fg};
        }}
        QLabel#mutedMeta {{
            color: {t.muted};
            font-size: 12px;
        }}
        QLabel#composerMeta {{
            color: {t.muted};
            font-size: 11px;
        }}
        QLabel#subtleHint {{
            color: {t.fg_secondary};
            font-size: 13px;
        }}

        /* --- Unified App Topbar & Status Pills --- */
        QFrame#appTopbar {{
            background: {t.bg};
            border-bottom: 1px solid {t.border_subtle};
        }}
        QFrame#modeSwitch {{
            background: {t.field};
            border: 1px solid {t.border};
            border-radius: 9px;
        }}
        QPushButton#modeSegBtn {{
            background: transparent;
            border: 1px solid transparent;
            border-radius: 7px;
            padding: 3px 8px;
            font-size: 12px;
            font-weight: 550;
            color: {t.fg_secondary};
        }}
        QPushButton#modeSegBtn:hover {{
            color: {t.fg};
        }}
        QPushButton#modeSegBtn:checked {{
            background: {t.accent_tint};
            border-color: {t.accent_border};
            color: {t.accent};
            font-weight: 650;
        }}
        QFrame#rightDrawer {{
            background: {t.sidebar};
            border-left: 1px solid {t.border_subtle};
        }}
        QFrame#rightDrawer QFrame#contextCard {{
            background: transparent;
            border: none;
        }}
        QFrame#rightDrawer QPushButton {{
            padding: 5px 8px;
        }}
        QFrame#rightDrawer QComboBox {{
            padding: 4px 20px 4px 7px;
        }}
        QFrame#rightDrawer QSpinBox {{
            padding: 4px 16px 4px 6px;
        }}
        QScrollArea#drawerScroll, QWidget#drawerBody {{
            background: transparent;
            border: none;
        }}
        QLabel#statusPill {{
            padding: 3px 9px;
            border-radius: 9px;
            font-size: 11px;
            font-weight: 600;
            background: {t.field};
            color: {t.accent};
            border: 1px solid {t.border_subtle};
        }}
        QLabel#statusPill[tone="ok"] {{
            background: {t.success_tint};
            color: {t.success};
            border-color: {t.success};
        }}
        QLabel#statusPill[tone="warn"] {{
            background: {t.warning_tint};
            color: {t.warning};
            border-color: {t.warning};
        }}
        QLabel#statusPill[tone="error"] {{
            background: {t.danger_tint};
            color: {t.danger};
            border-color: {t.danger};
        }}
        QPushButton#resourceMonitorBtn {{
            background: {t.panel};
            color: {t.fg_secondary};
            border: 1px solid {t.border_subtle};
            border-radius: 9px;
            padding: 4px 10px;
            font-size: 11px;
            font-weight: 550;
        }}
        QPushButton#resourceMonitorBtn:hover {{
            color: {t.fg};
            background: {t.field};
            border-color: {t.border_strong};
        }}
        QPushButton#resourceMonitorBtn:checked {{
            color: {t.accent};
            background: {t.accent_tint};
            border-color: {t.accent_border};
        }}

        /* --- Sidebar Navigation & History --- */
        QFrame#sidebar {{
            background: {t.sidebar};
            border-right: 1px solid {t.border_subtle};
        }}
        QLabel#brand {{
            font-size: 13px;
            font-weight: 700;
            color: {t.fg};
            padding-left: 1px;
        }}
        QLabel#brandMark {{
            background: transparent;
            padding: 0;
        }}
        QFrame#sidebar QWidget#historyPanel,
        QWidget#historyPanel,
        QWidget#compactSpacer {{
            background: transparent;
        }}
        QFrame#subtleDivider, QFrame#contextDivider {{
            background: {t.border_subtle};
            border: none;
            max-height: 1px;
            min-height: 1px;
            margin: 2px 0;
        }}
        QPushButton#sidebarToggle {{
            background: transparent;
            border: 1px solid transparent;
            border-radius: 8px;
            padding: 0;
            color: {t.muted};
        }}
        QPushButton#sidebarToggle:hover {{
            background: {t.field};
            border-color: {t.border};
            color: {t.fg};
        }}
        QPushButton#nav {{
            text-align: left;
            padding: 8px 10px;
            border: 1px solid transparent;
            border-radius: 9px;
            background: transparent;
            color: {t.fg_secondary};
            font-weight: 500;
        }}
        QPushButton#nav:hover {{
            background: {t.field};
            border-color: {t.border_subtle};
            color: {t.fg};
        }}
        QPushButton#nav:checked {{
            color: {t.accent};
            background: {t.accent_tint};
            border-color: {t.accent_border};
            font-weight: 600;
        }}
        QPushButton#nav[iconOnly="true"],
        QFrame#sidebar[compact="true"] QPushButton#nav,
        QFrame#sidebar[compact="true"] QPushButton#primary,
        QFrame#sidebar[compact="true"] QPushButton#sidebarToggle {{
            padding: 0;
            border-radius: 9px;
            text-align: center;
        }}
        QFrame#sidebar[compact="true"] QPushButton#nav:checked {{
            background: {t.accent_tint};
            border-color: {t.accent_border};
        }}
        QFrame#sidebar QPushButton#primary {{
            padding: 6px 4px;
            border-radius: 9px;
        }}
        QPushButton#historySearchTrigger {{
            background: {t.field};
            border: 1px solid {t.border};
            border-radius: 8px;
            padding: 0 8px;
            color: {t.muted};
            text-align: left;
            font-weight: 450;
            font-size: 12px;
        }}
        QPushButton#historySearchTrigger:hover {{
            border-color: {t.accent_border};
            color: {t.fg};
            background: {t.hover};
        }}
        QPushButton#historyHeaderButton {{
            background: {t.field};
            border: 1px solid {t.border};
            border-radius: 8px;
            padding: 0;
            color: {t.fg_secondary};
        }}
        QPushButton#historyHeaderButton:hover {{
            background: {t.hover};
            border-color: {t.accent};
            color: {t.fg};
        }}
        QLineEdit#historySearch {{
            background: {t.field};
            border: 1px solid {t.accent_border};
            border-radius: 8px;
            padding: 4px 10px;
            min-height: 0;
            color: {t.fg};
            font-size: 13px;
        }}
        QListWidget#conversations, QListWidget#conversations > QWidget {{
            background: {t.sidebar};
            border: none;
            border-radius: 0px;
            padding: 0;
            outline: none;
        }}
        QListWidget#conversations::item {{
            color: transparent;
            padding: 0;
            border-radius: 8px;
            margin: 1px 0;
            background: transparent;
        }}
        QListWidget#conversations::item:selected {{
            color: transparent;
            background: transparent;
        }}
        QWidget#historyGroupRow {{
            background: {t.sidebar};
            border-radius: 6px;
        }}
        QWidget#historyTitleRow {{
            background: transparent;
            border: none;
            border-radius: 8px;
        }}
        QWidget#historyTitleRow:hover {{
            background: {t.field};
        }}
        QWidget#historyTitleRow[selected="true"] {{
            background: {t.accent_tint};
        }}
        QLabel#historyItemTitle {{
            background: transparent;
            color: {t.fg_secondary};
            font-size: 13px;
        }}
        QLabel#historyItemTitle[selected="true"] {{
            color: {t.accent};
            font-weight: 600;
        }}
        QPushButton#historyHeading {{
            background: transparent;
            border: none;
            border-radius: 6px;
            padding: 4px 6px;
            text-align: left;
            font-size: 11px;
            font-weight: 650;
            color: {t.muted};
        }}
        QPushButton#historyHeading:hover {{
            color: {t.fg};
        }}
        QPushButton#historyHeading:focus {{
            border: 2px solid {t.accent};
        }}

        /* --- Cards, Banners & Notice Boxes --- */
        QFrame#surfaceCard, QFrame#contextCard, QFrame#agentCard,
        QFrame#settingsCard, QFrame#chatHeaderCard, QFrame#onboardingCard {{
            background: {t.panel};
            border: 1px solid {t.border};
            border-radius: 12px;
        }}
        QFrame#sectionGroup, QFrame#metricTile {{
            background: {t.panel};
            border: 1px solid {t.border_subtle};
            border-radius: 10px;
        }}
        QFrame#modelInspector {{
            background: {t.panel};
            border: 1px solid {t.border_subtle};
            border-radius: 10px;
        }}
        QFrame#toolbarStrip {{
            background: transparent;
            border: none;
            border-bottom: 1px solid {t.border_subtle};
        }}
        QFrame#engineCallout {{
            background: {t.field};
            border: 1px solid {t.border_subtle};
            border-radius: 8px;
        }}
        QFrame#errorBanner {{
            background: {t.danger_tint};
            border: 1px solid {t.danger};
            border-radius: 8px;
        }}
        QCheckBox {{
            spacing: 8px;
            color: {t.fg};
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 1px solid {t.border_strong};
            background: {t.panel};
        }}
        QCheckBox::indicator:hover {{
            border-color: {t.accent};
        }}
        QCheckBox::indicator:checked {{
            border: 3px solid {t.panel};
            background: {t.accent};
        }}
        QLabel#metricTitle {{
            color: {t.muted};
            font-size: 11px;
            font-weight: 600;
        }}
        QLabel#metricValue {{
            color: {t.fg};
            font-size: 15px;
            font-weight: 700;
        }}
        QLabel#metricSub {{
            color: {t.muted};
            font-size: 12px;
        }}
        QPushButton#sectionPill {{
            background: transparent;
            border: 1px solid transparent;
            border-radius: 8px;
            padding: 5px 11px;
            color: {t.muted};
            font-size: 12px;
            font-weight: 600;
        }}
        QPushButton#sectionPill:hover {{
            background: {t.hover};
            color: {t.fg};
        }}
        QPushButton#sectionPill:checked {{
            background: {t.accent_tint};
            border-color: {t.accent_border};
            color: {t.accent};
        }}
        QFrame#composerBox {{
            background: {t.panel};
            border: 1px solid {t.border};
            border-radius: 18px;
        }}
        QFrame#composerBox[focused="true"] {{
            border: 1.5px solid {t.accent};
        }}
        QFrame#composerBox QPlainTextEdit#composer,
        QFrame#composerBox QPlainTextEdit#composer:focus {{
            background: transparent;
            border: none;
            padding: 2px 4px;
        }}
        QPushButton#composerSendBtn {{
            background: {t.accent_button};
            color: {t.accent_text};
            border: none;
            border-radius: 17px;
            min-width: 0;
            min-height: 0;
            padding: 0;
        }}
        QPushButton#composerSendBtn:hover {{
            background: {t.accent_hover};
        }}
        QPushButton#composerSendBtn:disabled {{
            background: {t.field};
            color: {t.muted};
        }}
        QPushButton#composerStopBtn {{
            background: {t.danger_tint};
            color: {t.danger};
            border: 1px solid {t.danger};
            border-radius: 17px;
            min-width: 0;
            min-height: 0;
            padding: 0;
        }}
        QPushButton#composerStopBtn:hover {{
            background: {t.danger};
            color: #ffffff;
        }}
        QFrame#agentInlineBanner {{
            background: {t.panel};
            border: 1px solid {t.accent_border};
            border-radius: 10px;
        }}
        QFrame#noticeCard {{
            background: {t.elevated};
            border: 1px solid {t.border};
            border-left: 3px solid {t.accent};
            border-radius: 9px;
            padding: 4px;
        }}
        QFrame#noticeCard[kind="error"] {{
            border-left: 3px solid {t.danger};
            background: {t.danger_tint};
        }}
        QLabel#notice {{
            background: transparent;
            border: none;
            padding: 0;
            color: {t.fg};
        }}
        QFrame#errorCard {{
            background: {t.panel};
            border: 1px solid {t.border};
            border-left: 3px solid {t.danger};
            border-radius: 9px;
            padding: 8px 10px;
        }}
        QFrame#errorDetailsBox, QFrame#messageStatsDetails, QFrame#resourceDetails {{
            background: {t.panel};
            border: 1px solid {t.border};
            border-radius: 9px;
            padding: 8px 12px;
        }}
        QLabel#agentRunError {{
            color: {t.fg};
            font-weight: 600;
        }}

        /* --- Buttons --- */
        QPushButton {{
            background: {t.field};
            color: {t.fg};
            border: 1px solid {t.border};
            border-radius: 8px;
            padding: 7px 14px;
            font-weight: 550;
        }}
        QPushButton:hover {{
            background: {t.hover};
            border-color: {t.accent_border};
        }}
        QPushButton:pressed {{
            background: {t.border};
        }}
        QPushButton:disabled {{
            color: {t.muted};
            background: {t.panel};
            border-color: {t.border_subtle};
        }}
        QPushButton#primary {{
            background: {t.accent_button};
            color: {t.accent_text};
            border: 1px solid {t.accent_button};
            font-weight: 600;
        }}
        QPushButton#primary:hover {{
            background: {t.accent_hover};
            border-color: {t.accent_hover};
        }}
        QPushButton#primary:disabled {{
            background: {t.field};
            color: {t.muted};
            border-color: {t.border};
        }}
        QPushButton#dangerButton {{
            background: {t.danger_tint};
            color: {t.danger};
            border: 1px solid {t.danger};
            font-weight: 600;
        }}
        QPushButton#dangerButton:hover {{
            background: {t.danger};
            color: #ffffff;
        }}
        QPushButton#dangerButton:disabled {{
            background: {t.panel};
            color: {t.muted};
            border-color: {t.border_subtle};
        }}
        QPushButton#ghostButton {{
            background: transparent;
            border: 1px solid transparent;
            color: {t.fg_secondary};
            padding: 6px 10px;
        }}
        QPushButton#ghostButton:hover {{
            background: {t.field};
            border-color: {t.border};
            color: {t.fg};
        }}
        QPushButton#iconButton {{
            background: {t.field};
            border: 1px solid {t.border};
            border-radius: 8px;
            padding: 0;
            color: {t.fg_secondary};
        }}
        QPushButton#iconButton:hover {{
            background: {t.hover};
            border-color: {t.accent};
            color: {t.fg};
        }}
        QPushButton#iconButton:checked {{
            background: {t.accent_tint};
            border-color: {t.accent_border};
            color: {t.accent};
        }}
        QPushButton#compactToggle, QPushButton#errorDetailsToggle {{
            background: {t.panel};
            border: 1px solid {t.border};
            border-radius: 7px;
            padding: 4px 10px;
            font-size: 12px;
            color: {t.muted};
        }}
        QPushButton#compactToggle:hover, QPushButton#compactToggle:checked,
        QPushButton#errorDetailsToggle:hover, QPushButton#errorDetailsToggle:checked {{
            color: {t.accent};
            background: {t.accent_tint};
            border-color: {t.accent_border};
        }}
        QToolButton {{
            background: {t.field};
            border: 1px solid {t.border};
            border-radius: 7px;
            padding: 4px 8px;
        }}
        QToolButton:hover {{
            border-color: {t.accent};
            background: {t.hover};
        }}
        QToolButton:focus {{
            border: 2px solid {t.accent};
        }}
        QToolButton:disabled {{
            color: {t.muted};
        }}
        QToolButton#noticeClose {{
            background: transparent;
            border: none;
            color: {t.muted};
            padding: 2px 6px;
            font-size: 15px;
        }}
        QToolButton#noticeClose:hover {{
            color: {t.fg};
        }}
        QFrame#cardActionsBar {{
            background: {t.panel};
            border: 1px solid {t.border_subtle};
            border-radius: 9px;
            padding: 1px;
        }}
        QToolButton#cardAction {{
            background: transparent;
            border: 1px solid transparent;
            border-radius: 6px;
            padding: 3px;
        }}
        QToolButton#cardAction:hover {{
            background: {t.field};
            border-color: {t.border};
        }}
        QToolButton#cardAction:focus {{
            background: {t.field};
            border: 1.5px solid {t.accent};
        }}
        QToolButton#cardAction:checked {{
            background: {t.accent_tint};
            border-color: {t.accent_border};
        }}

        /* --- Inputs, Combos & SpinBoxes --- */
        QComboBox#agentMode {{
            border-color: {t.accent_border};
            background: {t.accent_tint};
            color: {t.accent};
            font-weight: 600;
        }}
        QComboBox#agentMode::drop-down {{
            border-left-color: {t.accent_border};
        }}
        QLineEdit, QPlainTextEdit, QTextBrowser, QListWidget, QTableWidget, QColorDialog {{
            background: {t.panel};
            color: {t.fg};
            border: 1px solid {t.border};
            border-radius: 8px;
            padding: 7px 10px;
            selection-background-color: {t.accent_button};
            selection-color: {t.accent_text};
        }}
        QComboBox, QSpinBox, QDoubleSpinBox {{
            background: {t.field};
            color: {t.fg};
            border: 1px solid {t.border};
            border-radius: 8px;
            min-height: 20px;
            selection-background-color: {t.accent_button};
            selection-color: {t.accent_text};
        }}
        QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
            border-color: {t.border_strong};
        }}
        QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
            background: {t.panel};
            color: {t.muted};
            border-color: {t.border_subtle};
        }}
        QComboBox {{
            padding: 6px 32px 6px 10px;
        }}
        QComboBox::drop-down {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 26px;
            border: none;
            border-left: 1px solid {t.border};
            border-top-right-radius: 8px;
            border-bottom-right-radius: 8px;
            background: transparent;
        }}
        QComboBox::drop-down:hover {{
            background: {t.hover};
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
            background: {t.panel};
            border: 1px solid {t.border};
            border-radius: 8px;
        }}
        QComboBox QAbstractItemView, QListView {{
            background: {t.panel};
            color: {t.fg};
            border: 1px solid {t.border};
            border-radius: 8px;
            padding: 4px;
            selection-background-color: {t.accent_tint};
            selection-color: {t.accent};
            outline: none;
        }}
        QComboBox QAbstractItemView::item, QListView::item {{
            padding: 6px 10px;
            min-height: 22px;
            background: transparent;
            color: {t.fg};
            border-radius: 6px;
        }}
        QComboBox QAbstractItemView::item:hover,
        QComboBox QAbstractItemView::item:selected,
        QListView::item:hover,
        QListView::item:selected {{
            background: {t.accent_tint};
            color: {t.accent};
        }}
        QSpinBox, QDoubleSpinBox {{
            padding: 6px 28px 6px 10px;
        }}
        QSpinBox::up-button, QDoubleSpinBox::up-button {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 22px;
            border: none;
            border-left: 1px solid {t.border};
            border-bottom: 1px solid {t.border};
            border-top-right-radius: 8px;
            background: transparent;
        }}
        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: 22px;
            border: none;
            border-left: 1px solid {t.border};
            border-bottom-right-radius: 8px;
            background: transparent;
        }}
        QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
        QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
            background: {t.hover};
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
            border: 2px solid {t.accent};
        }}

        /* --- Conversation Transcript --- */
        QFrame#assistantTurn, QFrame#userTurn {{
            background: transparent;
            border: none;
        }}
        QToolButton#assistantAvatar {{
            background: {t.accent_tint};
            border: 1px solid {t.accent_border};
            border-radius: 11px;
            padding: 0;
        }}
        QToolButton#emptyBadge {{
            background: {t.accent_tint};
            border: 1px solid {t.accent_border};
            border-radius: 22px;
            padding: 0;
        }}
        QFrame#userBubble {{
            background: {t.elevated};
            border: 1px solid {t.border_subtle};
            border-radius: 16px;
        }}
        QWidget#emptyCanvas {{
            background: transparent;
        }}
        QLabel#emptyTitle {{
            background: transparent;
            color: {t.fg};
            font-size: 20px;
            font-weight: 650;
        }}
        QLabel#emptyState {{
            background: transparent;
            border: none;
            padding: 4px 12px;
            color: {t.muted};
            font-size: 13px;
        }}
        QFrame#drawerSection {{
            background: transparent;
            border: none;
        }}
        QLabel#drawerHeading {{
            color: {t.fg};
            font-size: 12px;
            font-weight: 650;
        }}
        QTextBrowser#messageText {{
            background: transparent;
            border: none;
            padding: 0;
        }}
        QLabel#messageAuthor {{
            color: {t.accent};
            font-weight: 700;
            font-size: 12px;
        }}
        QLabel#messageStats {{
            color: {t.muted};
            font-size: 11px;
        }}
        QFrame#codeContainer {{
            background: {t.bg};
            border: 1px solid {t.border};
            border-radius: 10px;
        }}
        QPlainTextEdit#codeBlock {{
            font-family: monospace;
            background: transparent;
            border: none;
            padding: 8px 10px;
        }}
        QPushButton#agentStepPill {{
            background: {t.field};
            color: {t.fg_secondary};
            border: 1px solid {t.border};
            border-radius: 8px;
            padding: 6px 10px;
            font-size: 12px;
            text-align: left;
        }}
        QPushButton#agentStepPill:hover {{
            border-color: {t.accent};
            color: {t.fg};
        }}
        QPushButton#agentStepPill:checked {{
            background: {t.accent_tint};
            border-color: {t.accent_border};
            color: {t.accent};
        }}
        QFrame#agentStepDetails {{
            background: {t.bg};
            border: 1px solid {t.border};
            border-radius: 8px;
        }}

        /* --- Tables, Tabs, Progress & Chrome --- */
        QListWidget::item {{
            padding: 9px 10px;
            border-radius: 7px;
        }}
        QListWidget::item:selected, QTableWidget::item:selected {{
            background: {t.accent_tint};
            color: {t.accent};
        }}
        QTableWidget {{
            background: {t.panel};
            border: 1px solid {t.border_subtle};
            border-radius: 10px;
            gridline-color: transparent;
            alternate-background-color: {t.elevated};
        }}
        QTableWidget::item {{
            padding: 6px 10px;
            border-bottom: 1px solid {t.border_subtle};
        }}
        QHeaderView::section {{
            background: {t.panel};
            color: {t.muted};
            border: none;
            border-bottom: 1px solid {t.border};
            padding: 8px 10px;
            font-weight: 600;
            font-size: 12px;
        }}
        QTabWidget::pane {{
            border: none;
        }}
        QTabBar {{
            border-bottom: 1px solid {t.border_subtle};
        }}
        QTabBar::tab {{
            padding: 8px 16px;
            background: transparent;
            color: {t.muted};
            border-bottom: 2px solid transparent;
            font-weight: 550;
        }}
        QTabBar::tab:hover {{
            color: {t.fg};
        }}
        QTabBar::tab:selected {{
            color: {t.accent};
            border-bottom-color: {t.accent};
            font-weight: 650;
        }}
        QScrollArea {{
            border: none;
            background: transparent;
        }}
        QScrollBar:vertical {{
            width: 8px;
            background: transparent;
        }}
        QScrollBar::handle:vertical {{
            background: {t.border};
            border-radius: 4px;
            min-height: 32px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {t.border_strong};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar:horizontal {{
            height: 8px;
            background: transparent;
        }}
        QScrollBar::handle:horizontal {{
            background: {t.border};
            border-radius: 4px;
            min-width: 32px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {t.border_strong};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0;
        }}
        QProgressBar {{
            border: 1px solid {t.border};
            background: {t.field};
            border-radius: 7px;
            text-align: center;
            min-height: 20px;
        }}
        QProgressBar#contextMeter {{
            min-height: 6px;
            max-height: 8px;
            border-radius: 3px;
            border: none;
        }}
        QProgressBar::chunk {{
            background: {t.accent_button};
            border-radius: 6px;
        }}
        QStatusBar {{
            color: {t.muted};
            border-top: 1px solid {t.border_subtle};
        }}
        QSplitter::handle {{
            background: {t.border_subtle};
            width: 1px;
        }}
        QSplitter#mainShell::handle {{
            background: transparent;
        }}
        QToolTip {{
            background: {t.elevated};
            color: {t.fg};
            border: 1px solid {t.border};
            border-radius: 6px;
            padding: 5px 8px;
        }}
        QMenu {{
            background: {t.panel};
            color: {t.fg};
            border: 1px solid {t.border};
            border-radius: 9px;
            padding: 4px;
        }}
        QMenu::item {{
            padding: 6px 14px;
            border-radius: 6px;
        }}
        QMenu::item:disabled {{
            color: {t.muted};
        }}
        QMenu::item:selected {{
            background: {t.accent_tint};
            color: {t.accent};
        }}
    """
    return re.sub(
        r"(?P<size>\d+)px",
        lambda m: (
            m.group(0) if int(m["size"]) <= 3 else f"{max(1, round(int(m['size']) * scale))}px"
        ),
        raw,
    )
