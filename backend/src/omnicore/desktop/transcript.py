"""Native message cards. Model output is untrusted, including Markdown resources."""

import json
import math
import re

from PySide6.QtCore import QEvent, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF, QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from omnicore.desktop.errors import describe_error
from omnicore.desktop.styles import app_icon, make_divider


def _stat_pixmap(kind, color, size=14):
    """Draw a crisp 2x vector icon for response statistics."""
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.transparent)
    pixmap.setDevicePixelRatio(2)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    if kind == "ttft":
        painter.drawEllipse(2, 2, size - 4, size - 4)
        painter.drawLine(QPointF(size / 2, size / 2), QPointF(size / 2, 4.2))
        painter.drawLine(QPointF(size / 2, size / 2), QPointF(size - 4.5, size / 2))
    elif kind == "speed":
        bolt = QPolygonF(
            [
                QPointF(size * 0.58, 1.8),
                QPointF(size * 0.28, size * 0.54),
                QPointF(size * 0.52, size * 0.54),
                QPointF(size * 0.42, size - 1.8),
                QPointF(size * 0.74, size * 0.44),
                QPointF(size * 0.50, size * 0.44),
            ]
        )
        painter.drawPolyline(bolt)
    elif kind == "tokens":
        diamond = QPolygonF(
            [
                QPointF(size / 2, 2.0),
                QPointF(size - 2.0, size / 2),
                QPointF(size / 2, size - 2.0),
                QPointF(2.0, size / 2),
            ]
        )
        painter.drawPolygon(diamond)
    elif kind == "duration":
        painter.drawEllipse(2.5, 3.0, size - 5.0, size - 5.0)
        painter.drawLine(QPointF(size / 2 - 2.0, 1.5), QPointF(size / 2 + 2.0, 1.5))
        painter.drawLine(QPointF(size / 2, size / 2 + 0.5), QPointF(size / 2 + 2.2, size / 2 - 1.8))
    painter.end()
    return pixmap


def _format_stat_rows(stats, tr):
    if not stats:
        return []
    sep = tr("decimal_separator")
    dash = "—"
    rows = []

    def fmt_val(val, unit="", digits=2):
        if val is None:
            return dash
        if isinstance(val, float):
            return f"{val:.{digits}f}".replace(".", sep) + (f" {unit}" if unit else "")
        return f"{val} {unit}".rstrip()

    in_tok = stats.get("input_tokens")
    out_tok = stats.get("output_tokens")
    tot_tok = stats.get("total_tokens")
    if tot_tok is None and isinstance(in_tok, int) and isinstance(out_tok, int):
        tot_tok = in_tok + out_tok

    if stats.get("execution_model"):
        rows.append((tr("stats_model"), str(stats["execution_model"])))
    for key, label, unit in (
        ("ttft_seconds", "ttft", "s"),
        ("tokens_per_second", "speed", "tok/s"),
        ("input_tokens", "input_tokens", ""),
        ("output_tokens", "output_tokens", ""),
    ):
        rows.append((tr(label), fmt_val(stats.get(key), unit)))
    if stats.get("prompt_processing_seconds") is not None:
        rows.append((tr("stats_prompt_time"), fmt_val(stats.get("prompt_processing_seconds"), "s")))
    rows.append((tr("stats_total_tokens"), fmt_val(tot_tok)))
    rows.append((tr("stats_inference_time"), fmt_val(stats.get("generation_seconds"), "s")))
    if stats.get("total_task_seconds") is not None:
        rows.append((tr("stats_total_task_time"), fmt_val(stats.get("total_task_seconds"), "s")))
    if stats.get("agent_steps") is not None or stats.get("tool_calls") is not None:
        rows.append((tr("stats_agent_steps"), fmt_val(stats.get("agent_steps"))))
        rows.append((tr("stats_tool_calls"), fmt_val(stats.get("tool_calls"))))
        rows.append((tr("stats_tool_time"), fmt_val(stats.get("tool_execution_seconds"), "s")))
    rows.append((tr("load_time"), fmt_val(stats.get("model_load_seconds"), "s")))
    dev = stats.get("execution_device")
    rows.append((tr("execution_device"), str(dev) if dev else dash))
    off_layers = stats.get("gpu_offloaded_layers")
    tot_layers = stats.get("gpu_total_layers")
    if off_layers is not None and tot_layers:
        layer_txt = f"{off_layers}/{tot_layers}"
    elif off_layers is not None:
        layer_txt = str(off_layers)
    else:
        layer_txt = dash
    if stats.get("gpu_offload_mode"):
        rows.append((tr("stats_offload_mode"), f"{stats['gpu_offload_mode']} ({layer_txt})"))
    else:
        rows.append((tr("offloaded_layers"), layer_txt))
    used, limit = stats.get("context_used_tokens"), stats.get("context_limit_tokens")
    if used is not None and limit:
        rows.append((tr("context_usage"), f"{used}/{limit} ({used / limit:.0%})"))
    else:
        rows.append((tr("context_usage"), dash))
    reason = stats.get("finish_reason")
    if reason:
        reason_txt = (
            tr("finish_" + reason) if reason in {"stop", "length", "cancelled", "error"} else reason
        )
    else:
        reason_txt = dash
    rows.append((tr("finish_reason"), reason_txt))
    if stats.get("fallback_reason"):
        rows.append((tr("stats_offload_mode"), tr("cpu_fallback")))
    return rows


def statistics_text(stats, tr):
    rows = _format_stat_rows(stats, tr)
    if not rows:
        return ""
    return " · ".join(f"{label}: {val}" for label, val in rows)


def statistics_details_text(stats, tr):
    rows = _format_stat_rows(stats, tr)
    if not rows:
        return ""
    return "\n".join(f"{label}: {val}" for label, val in rows)


class SafeMarkdown(QTextBrowser):
    def __init__(self, text, parent=None, compact_width=None):
        super().__init__(parent)
        self.setObjectName("messageText")
        self.setFrameShape(QFrame.NoFrame)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._compact_width = compact_width
        self.document().setDocumentMargin(2)
        self.document().setMarkdown(
            text, QTextDocument.MarkdownDialectGitHub | QTextDocument.MarkdownNoHTML
        )
        if compact_width:
            probe = self.document().clone(self)
            probe.setTextWidth(-1)
            self._ideal_width = min(compact_width, max(44, math.ceil(probe.size().width()) + 10))
            self.setMinimumWidth(44)
            self.setMaximumWidth(self._ideal_width)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        else:
            self._ideal_width = 0
            self.setMinimumWidth(0)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.document().documentLayout().documentSizeChanged.connect(self.fit)
        self.fit()

    def loadResource(self, resource_type, url):
        # No local files, remote image requests, data URLs or external styles from model text.
        return None

    def minimumSizeHint(self):
        return QSize(0, self.height() or 24)

    def sizeHint(self):
        base = super().sizeHint()
        if self._compact_width:
            return QSize(
                self._ideal_width,
                self.height() or base.height(),
            )
        return QSize(0, self.height() or base.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.StyleChange, QEvent.FontChange):
            self.fit()

    def fit(self, *_):
        avail = self.viewport().width()
        if self._compact_width:
            target_w = min(self._ideal_width, avail) if avail >= 40 else self._ideal_width
            pad = 6
        else:
            target_w = max(80, avail)
            pad = 10
        self.document().setTextWidth(target_w)
        height = math.ceil(self.document().size().height()) + pad
        if self.height() != height:
            self.setFixedHeight(height)
            parent = self.parentWidget()
            if parent is not None and parent.layout() is not None:
                parent.layout().invalidate()


class MessageCard(QFrame):
    authorize_directory_requested = Signal(object)

    def __init__(
        self,
        message,
        tr,
        parent=None,
        regenerate=None,
        can_regenerate=False,
        grant_folder=None,
        continue_run=None,
    ):
        super().__init__(parent)
        is_user = message["role"] == "user"
        self.setObjectName("userTurn" if is_user else "assistantTurn")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.message = message
        self.can_regenerate = can_regenerate
        self._can_regenerate = bool(can_regenerate and regenerate)
        self._regenerate_cb = regenerate
        self._grant_folder = grant_folder
        self._continue_run = continue_run
        self._compact_bubble = is_user
        self._hover_effects = []
        self._action_buttons = []
        self._info_button = None

        copy_label = tr("copy") if not is_user else tr("copy_message")
        copy = QToolButton()
        self.icon_action(copy, "edit-copy", QStyle.SP_FileDialogContentsView, copy_label)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(message["content"]))
        copy.setEnabled(bool(message["content"]))
        self._register_action_button(copy)

        self.agent_step_buttons = []
        self.agent_step_details = []
        self.agent_error_label = None
        self.error_card = None
        self.authorize_dir_button = None
        self.error_retry_button = None
        self.error_details_toggle = None
        self.error_details_frame = None
        self.error_details_label = None
        self.agent_folder_box = None
        self.agent_folder_label = None
        self.agent_grant_button = None
        self.agent_continue_button = None
        self.stats_details_frame = None
        self.stats_details_label = None

        if is_user:
            outer = QHBoxLayout(self)
            outer.setContentsMargins(0, 4, 0, 4)
            outer.setSpacing(8)
            outer.addStretch(1)
            user_actions = QFrame(self)
            user_actions.setObjectName("cardActionsBar")
            ua_layout = QHBoxLayout(user_actions)
            ua_layout.setContentsMargins(2, 2, 2, 2)
            ua_layout.setSpacing(2)
            ua_layout.addWidget(copy)
            self._attach_actions_hover(user_actions)
            outer.addWidget(user_actions, 0, Qt.AlignVCenter)
            bubble = QFrame(self)
            bubble.setObjectName("userBubble")
            bubble.setMaximumWidth(600)
            bubble.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            self.bubble = bubble
            self.layout_ = QVBoxLayout(bubble)
            self.layout_.setContentsMargins(14, 9, 14, 9)
            self.layout_.setSpacing(6)
            outer.addWidget(bubble, 0, Qt.AlignRight)
        else:
            self.layout_ = QVBoxLayout(self)
            self.layout_.setContentsMargins(0, 6, 0, 8)
            self.layout_.setSpacing(8)
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(8)
            avatar = QToolButton()
            avatar.setObjectName("assistantAvatar")
            avatar.setFocusPolicy(Qt.NoFocus)
            avatar.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            avatar.setFixedSize(22, 22)
            avatar.setIcon(app_icon("brand", self._accent_color_hex(), 12))
            avatar.setIconSize(QSize(12, 12))
            header.addWidget(avatar)
            stats = message.get("statistics") or {}
            name = message.get("model_name") or stats.get("execution_model") or tr("assistant")
            title = QLabel(name)
            title.setTextFormat(Qt.PlainText)
            title.setWordWrap(True)
            title.setMinimumWidth(0)
            title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            title.setObjectName("messageAuthor")
            header.addWidget(title, 1)
            self._header_layout = header
            self.layout_.addLayout(header)

        if message.get("reasoning_content"):
            reasoning = QPlainTextEdit(message["reasoning_content"])
            reasoning.setReadOnly(True)
            reasoning.setMaximumHeight(130)
            reasoning.hide()
            toggle = QPushButton(tr("reasoning"))
            toggle.setObjectName("compactToggle")
            toggle.setCheckable(True)
            toggle.toggled.connect(reasoning.setVisible)
            self.layout_.addWidget(toggle, 0, Qt.AlignLeft)
            self.layout_.addWidget(reasoning)

        if not is_user and message.get("agent_run"):
            self._render_agent_activity(message["agent_run"], tr)
        self._body(message["content"], tr)
        if is_user and message.get("agent_run"):
            self._render_agent_activity(message["agent_run"], tr)
        if (message.get("status") == "failed" or message.get("error_code")) and not self.error_card:
            err_code = message.get("error_code") or "generation_failed"
            self._render_error_card(err_code, tr, component="chat_generation")
        if message.get("agent_run"):
            self._render_agent_folder_prompt(message["agent_run"], tr)
        raw_stats = message.get("statistics")
        if not raw_stats and isinstance(message.get("agent_run"), dict):
            raw_stats = message["agent_run"].get("statistics")
        details = statistics_text(raw_stats, tr)
        multiline_details = statistics_details_text(raw_stats, tr)
        if details:
            stats = raw_stats or {}
            stats_row = QHBoxLayout()
            stats_row.setContentsMargins(0, 2, 0, 0)
            stats_row.setSpacing(6)
            stat_color = self.palette().color(self.palette().ColorRole.PlaceholderText).name()
            first = True
            for icon_kind, key, label_key, suffix in (
                ("ttft", "ttft_seconds", "ttft", "s TTFT"),
                ("speed", "tokens_per_second", "speed", "tok/s"),
                ("tokens", "output_tokens", "output_tokens", tr("tokens_short")),
                ("duration", "generation_seconds", "duration", "s"),
            ):
                value = stats.get(key)
                if value is None:
                    continue
                if not first:
                    sep_lbl = QLabel("·")
                    sep_lbl.setObjectName("messageStats")
                    stats_row.addWidget(sep_lbl)
                first = False
                icon_lbl = QLabel()
                icon_lbl.setPixmap(_stat_pixmap(icon_kind, stat_color, 14))
                icon_lbl.setFixedSize(14, 14)
                icon_lbl.setToolTip(tr(label_key))
                number = f"{value:.2f}" if isinstance(value, float) else str(value)
                number = number.replace(".", tr("decimal_separator"))
                val_lbl = QLabel(f"{number} {suffix}")
                val_lbl.setToolTip(f"{tr(label_key)}\n{details}")
                val_lbl.setObjectName("messageStats")
                val_lbl.setTextFormat(Qt.PlainText)
                val_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                stats_row.addWidget(icon_lbl)
                stats_row.addWidget(val_lbl)
            if stats.get("gpu_offloaded_layers") is not None and stats.get("execution_device"):
                if not first:
                    sep_lbl = QLabel("·")
                    sep_lbl.setObjectName("messageStats")
                    stats_row.addWidget(sep_lbl)
                first = False
                off = stats["gpu_offloaded_layers"]
                tot = stats.get("gpu_total_layers")
                layer_badge = f"GPU {off}/{tot}" if tot else (f"GPU {off}" if off else "CPU")
                dev_lbl = QLabel(layer_badge)
                dev_lbl.setToolTip(details)
                dev_lbl.setObjectName("messageStats")
                dev_lbl.setTextFormat(Qt.PlainText)
                stats_row.addWidget(dev_lbl)
            stats_row.addStretch()
            self.layout_.addLayout(stats_row)

        if not is_user or details:
            actions_bar = QFrame()
            actions_bar.setObjectName("cardActionsBar")
            actions = QHBoxLayout(actions_bar)
            actions.setContentsMargins(3, 2, 3, 2)
            actions.setSpacing(2)
            if not is_user:
                actions.addWidget(copy)
                retry = QToolButton()
                self.icon_action(retry, "view-refresh", QStyle.SP_BrowserReload, tr("regenerate"))
                retry.setToolTip(tr("regenerate_branch"))
                status = message.get("status", "completed")
                retry.setEnabled(
                    can_regenerate
                    and (
                        (bool(message.get("content")) and status == "completed")
                        or status in {"failed", "interrupted", "cancelled"}
                    )
                )
                if regenerate:
                    retry.clicked.connect(lambda: regenerate(message))
                self._register_action_button(retry)
                actions.addWidget(retry)
            info = QToolButton()
            self.icon_action(
                info, "dialog-information", QStyle.SP_MessageBoxInformation, tr("context_details")
            )
            info.setEnabled(bool(details))
            info.setCheckable(True)
            self._info_button = info
            self._register_action_button(info)
            stats_frame = QFrame()
            stats_frame.setObjectName("messageStatsDetails")
            sf_layout = QVBoxLayout(stats_frame)
            sf_layout.setContentsMargins(10, 8, 10, 8)
            sf_layout.setSpacing(2)
            full_stats = QLabel(multiline_details or details)
            full_stats.setObjectName("messageStats")
            full_stats.setTextFormat(Qt.PlainText)
            full_stats.setWordWrap(True)
            full_stats.setTextInteractionFlags(Qt.TextSelectableByMouse)
            sf_layout.addWidget(full_stats)
            stats_frame.hide()
            info.toggled.connect(stats_frame.setVisible)
            info.toggled.connect(lambda _on: self._sync_actions_opacity(self.underMouse()))
            self.stats_details_frame = stats_frame
            self.stats_details_label = full_stats
            actions.addWidget(info)
            self._attach_actions_hover(actions_bar)
            if not is_user:
                self._header_layout.addWidget(actions_bar)
            else:
                self.layout_.addWidget(actions_bar, 0, Qt.AlignRight)
            self.layout_.addWidget(stats_frame)

    def _accent_color_hex(self):
        return self.palette().color(self.palette().ColorRole.HighlightedText).name()

    def _register_action_button(self, button):
        button.setFocusPolicy(Qt.StrongFocus)
        button.installEventFilter(self)
        self._action_buttons.append(button)

    def eventFilter(self, watched, event):
        if watched in self._action_buttons and event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self._sync_actions_opacity(self.underMouse())
        return super().eventFilter(watched, event)

    def _attach_actions_hover(self, widget):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        self._hover_effects.append(effect)
        self._sync_actions_opacity(False)

    def _sync_actions_opacity(self, hovered):
        pinned = self._info_button is not None and self._info_button.isChecked()
        focused = any(btn.hasFocus() for btn in self._action_buttons)
        opacity = 1.0 if (hovered or pinned or focused) else 0.62
        for effect in self._hover_effects:
            effect.setOpacity(opacity)

    def enterEvent(self, event):
        super().enterEvent(event)
        self._sync_actions_opacity(True)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._sync_actions_opacity(False)

    def icon_action(self, button, name, fallback, label):
        kind_map = {
            "edit-copy": "copy",
            "view-refresh": "refresh",
            "dialog-information": "info",
        }
        button.setObjectName("cardAction")
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.StrongFocus)
        button.setAccessibleName(label)
        color = self.palette().color(self.palette().ColorRole.WindowText).name()
        kind = kind_map.get(name)
        button.setIcon(app_icon(kind, color, 15) if kind else self.style().standardIcon(fallback))
        button.setIconSize(QSize(15, 15))
        button.setFixedSize(26, 26)
        button.setToolTip(label)
        button.setAccessibleName(label)

    def _render_agent_activity(self, run, tr):
        if not isinstance(run, dict):
            return
        steps = run.get("steps") or []
        limit = run.get("step_limit") or max(len(steps), 8)
        is_pl = tr("you") == "Ty"
        step_word = "Krok" if is_pl else "Step"
        for idx, step in enumerate(steps, 1):
            state = step.get("state", "completed")
            state_label = tr("agent_" + state)
            duration = step.get("duration_ms", 0)
            tool_name = step.get("tool", "")
            pill = QPushButton(
                f"{step_word} {idx}/{limit} · {tool_name} · {state_label} · {duration} ms"
            )
            pill.setObjectName("agentStepPill")
            pill.setCheckable(True)
            pill.setChecked(False)
            details_frame = QFrame()
            details_frame.setObjectName("agentStepDetails")
            d_layout = QVBoxLayout(details_frame)
            d_layout.setContentsMargins(10, 6, 10, 6)
            d_layout.setSpacing(2)
            lines = [
                f"{tr('agent_tool')}: {tool_name}",
                f"{tr('agent_state')}: {state_label} · {duration} ms",
            ]
            summary = step.get("summary")
            if summary and summary != tool_name:
                lines.append(f"{'Cel' if is_pl else 'Target'}: {summary}")
            res_summary = step.get("result_summary")
            if res_summary:
                preview = json.dumps(res_summary, ensure_ascii=False)
                if len(preview) > 240:
                    preview = preview[:237] + "..."
                lines.append(f"{'Wynik' if is_pl else 'Result'}: {preview}")
            err_code = step.get("error_code")
            if err_code:
                lines.append(f"{'Błąd' if is_pl else 'Error'}: {tr(err_code)} ({err_code})")
            if tool_name == "write_text" or step.get("proposal_id"):
                if state == "completed":
                    approval_txt = "Zatwierdzono zapis" if is_pl else "Write approved"
                elif state == "cancelled":
                    approval_txt = "Odrzucono zapis" if is_pl else "Write rejected"
                else:
                    approval_txt = "Oczekuje na zatwierdzenie" if is_pl else "Awaiting approval"
                lines.append(approval_txt)
            info_lbl = QLabel("\n".join(lines))
            info_lbl.setTextFormat(Qt.PlainText)
            info_lbl.setWordWrap(True)
            info_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            d_layout.addWidget(info_lbl)
            details_frame.hide()
            pill.toggled.connect(details_frame.setVisible)
            self.layout_.addWidget(pill)
            self.layout_.addWidget(details_frame)
            self.agent_step_buttons.append(pill)
            self.agent_step_details.append(details_frame)
        if run.get("state") in {"failed", "cancelled", "interrupted"}:
            err_code = run.get("error_code") or ("agent_" + run["state"])
            comp = None
            target = None
            err_details = run.get("error_details") or []
            if err_details and isinstance(err_details[0], dict):
                comp = err_details[0].get("component")
                target = err_details[0].get("target")
            if not comp:
                for step in reversed(steps):
                    if step.get("error_code") == err_code:
                        comp = step.get("error_component") or step.get("tool")
                        break
            self._render_error_card(err_code, tr, component=comp, target=target)

    def _render_error_card(self, code, tr, *, component=None, target=None):
        info = describe_error(code, tr, component=component, target=target)
        card = QFrame()
        card.setObjectName("errorCard")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(12, 10, 12, 10)
        c_layout.setSpacing(6)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        err_lbl = QLabel(info["title"])
        err_lbl.setObjectName("agentRunError")
        err_lbl.setTextFormat(Qt.PlainText)
        err_lbl.setWordWrap(True)
        top.addWidget(err_lbl, 1)
        if info["code"] in {"model_directory_unauthorized", "path_not_allowed"}:
            auth_btn = QPushButton(tr("authorize_model_directory"))
            auth_btn.setObjectName("primary")
            auth_btn.setCursor(Qt.PointingHandCursor)
            auth_btn.clicked.connect(lambda: self.authorize_directory_requested.emit(self.message))
            top.addWidget(auth_btn)
            self.authorize_dir_button = auth_btn
        if component == "chat_generation" and self._can_regenerate:
            retry_btn = QPushButton(tr("retry_generation"))
            retry_btn.setObjectName("compactToggle")
            retry_btn.setCursor(Qt.PointingHandCursor)
            retry_btn.clicked.connect(lambda: self._regenerate_cb(self.message))
            top.addWidget(retry_btn)
            self.error_retry_button = retry_btn
        toggle = QPushButton(tr("error_details_toggle"))
        toggle.setObjectName("compactToggle")
        toggle.setCheckable(True)
        top.addWidget(toggle)
        c_layout.addLayout(top)
        details_frame = QFrame()
        details_frame.setObjectName("errorDetailsBox")
        d_layout = QVBoxLayout(details_frame)
        d_layout.setContentsMargins(10, 6, 10, 6)
        d_layout.setSpacing(3)
        details_text = "\n".join(
            [
                f"{tr('error_code_label')}: {info['code']}",
                f"{tr('error_component_label')}: {info['component']}",
                f"{tr('error_cause_label')}: {info['cause']}",
                f"{tr('error_solution_label')}: {info['solution']}",
            ]
        )
        details_lbl = QLabel(details_text)
        details_lbl.setObjectName("messageStats")
        details_lbl.setTextFormat(Qt.PlainText)
        details_lbl.setWordWrap(True)
        details_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        d_layout.addWidget(details_lbl)
        details_frame.hide()
        toggle.toggled.connect(details_frame.setVisible)
        c_layout.addWidget(details_frame)
        self.layout_.addWidget(card)
        self.agent_error_label = err_lbl
        self.error_card = card
        self.error_details_toggle = toggle
        self.error_details_frame = details_frame
        self.error_details_label = details_lbl

    def _render_agent_folder_prompt(self, run, tr):
        if (
            not isinstance(run, dict)
            or not run.get("needs_folder_grant")
            or run.get("continued_by")
            or self.message.get("suppress_folder_prompt")
        ):
            return
        has_folder = bool(self.message.get("has_granted_folder"))
        cancelled_grant = bool(self.message.get("folder_grant_cancelled"))
        box = QFrame()
        box.setObjectName("agentStepDetails")
        b_layout = QVBoxLayout(box)
        b_layout.setContentsMargins(10, 8, 10, 8)
        b_layout.setSpacing(6)
        if has_folder:
            notice_text = tr("agent_folder_ready_notice")
        elif cancelled_grant:
            notice_text = tr("agent_folder_cancelled")
        elif run.get("expand_grant"):
            notice_text = tr("agent_folder_expand_notice")
        else:
            notice_text = tr("agent_needs_folder_notice")
        target = run.get("requested_folder_path") or run.get("suggested_folder_name")
        if target and not has_folder and not cancelled_grant:
            notice_text = f"{notice_text} ({target})"
        lbl = QLabel(notice_text)
        lbl.setTextFormat(Qt.PlainText)
        lbl.setWordWrap(True)
        b_layout.addWidget(lbl)
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)
        grant_btn = QPushButton(tr("agent_folder"))
        grant_btn.setEnabled(self.can_regenerate)
        if self._grant_folder:
            grant_btn.clicked.connect(lambda: self._grant_folder(run))
        btn_row.addWidget(grant_btn)
        cont_btn = QPushButton(tr("agent_continue_task"))
        cont_btn.setProperty("primary", True)
        cont_btn.setVisible(has_folder)
        cont_btn.setEnabled(has_folder and self.can_regenerate)
        if self._continue_run:
            cont_btn.clicked.connect(lambda: self._continue_run(run))
        btn_row.addWidget(cont_btn)
        btn_row.addStretch()
        b_layout.addLayout(btn_row)
        self.layout_.addWidget(box)
        self.agent_folder_box = box
        self.agent_folder_label = lbl
        self.agent_grant_button = grant_btn
        self.agent_continue_button = cont_btn

    def _body(self, content, tr):
        # Treat fenced code as plain text, with a separate native clipboard action.
        lines, prose, code, fence = content.splitlines(keepends=True), [], [], None
        body_parent = getattr(self, "bubble", self)
        compact_w = 560 if self._compact_bubble else None

        def flush_prose():
            if prose:
                self.layout_.addWidget(
                    SafeMarkdown("".join(prose), body_parent, compact_width=compact_w)
                )
                prose.clear()

        def flush_code():
            text = "".join(code).rstrip("\n")
            container = QFrame(body_parent)
            container.setObjectName("codeContainer")
            c_layout = QVBoxLayout(container)
            c_layout.setSizeConstraint(QVBoxLayout.SetMinimumSize)
            c_layout.setContentsMargins(0, 0, 0, 0)
            c_layout.setSpacing(0)
            top = QHBoxLayout()
            top.setContentsMargins(12, 6, 8, 6)
            top.setSpacing(8)
            lang = (fence or "").strip() or "code"
            lang_lbl = QLabel(lang.lstrip("`~").strip() or "code")
            lang_lbl.setObjectName("mutedMeta")
            lang_lbl.setTextFormat(Qt.PlainText)
            button = QPushButton(tr("copy_code"))
            button.setObjectName("compactToggle")
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda: QApplication.clipboard().setText(text))
            top.addWidget(lang_lbl)
            top.addStretch(1)
            top.addWidget(button)
            c_layout.addLayout(top)
            c_layout.addWidget(make_divider("subtleDivider"))
            box = QPlainTextEdit(text)
            box.setReadOnly(True)
            box.setObjectName("codeBlock")
            box.setLineWrapMode(QPlainTextEdit.NoWrap)
            line_h = max(21, box.fontMetrics().lineSpacing() + 4)
            box.setFixedHeight(min(280, max(60, len(code) * line_h + 22)))
            c_layout.addWidget(box)
            self.layout_.addWidget(container)
            code.clear()

        for line in lines:
            match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\n"))
            if fence:
                if (
                    match
                    and match[1][0] == fence[0]
                    and len(match[1]) >= len(fence)
                    and not match[2].strip()
                ):
                    flush_code()
                    fence = None
                else:
                    code.append(line)
            elif match:
                flush_prose()
                fence = match[1]
            else:
                prose.append(line)
        if fence:
            flush_code()
        flush_prose()


class ChatTranscript(QScrollArea):
    regenerate_requested = Signal(object)
    authorize_directory_requested = Signal(object)
    grant_folder_requested = Signal(object)
    continue_run_requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setObjectName("transcript")
        self.setAlignment(Qt.AlignHCenter)
        container = QWidget()
        container.setObjectName("transcriptColumn")
        container.setMinimumWidth(0)
        container.setMaximumWidth(980)
        self.column = QVBoxLayout(container)
        self.column.setContentsMargins(16, 12, 16, 28)
        self.column.setSpacing(12)
        self.limit = 60
        self.more = QPushButton()
        self.more.setObjectName("compactToggle")
        self.more.clicked.connect(self.expand_history)
        self.column.addWidget(self.more, 0, Qt.AlignHCenter)

        self.empty_top_spacer = QWidget()
        self.empty_top_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.column.addWidget(self.empty_top_spacer, 1)

        self.empty_box = QWidget()
        self.empty_box.setObjectName("emptyCanvas")
        self.empty_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        empty_layout = QVBoxLayout(self.empty_box)
        empty_layout.setContentsMargins(40, 24, 40, 24)
        empty_layout.setSpacing(10)
        self.empty_badge = QToolButton()
        self.empty_badge.setObjectName("emptyBadge")
        self.empty_badge.setFocusPolicy(Qt.NoFocus)
        self.empty_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.empty_badge.setFixedSize(44, 44)
        self.empty_badge.setIcon(
            app_icon(
                "brand", self.palette().color(self.palette().ColorRole.HighlightedText).name(), 22
            )
        )
        self.empty_badge.setIconSize(QSize(22, 22))
        empty_layout.addWidget(self.empty_badge, 0, Qt.AlignHCenter)
        self.empty_title = QLabel()
        self.empty_title.setObjectName("emptyTitle")
        self.empty_title.setAlignment(Qt.AlignCenter)
        self.empty_title.setWordWrap(True)
        self.empty_title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        empty_layout.addWidget(self.empty_title)
        self.hint = QLabel()
        self.hint.setObjectName("emptyState")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        empty_layout.addWidget(self.hint)
        self.empty_slot = QVBoxLayout()
        self.empty_slot.setContentsMargins(0, 8, 0, 0)
        self.empty_slot.setSpacing(6)
        empty_layout.addLayout(self.empty_slot)
        self.column.addWidget(self.empty_box, 0)

        self.column.addStretch(1)
        self.setWidget(container)
        self.cards, self.messages, self.locale = [], [], None
        self.can_regenerate = False
        self._previous_can_regenerate = None
        self._pin_to_bottom = True
        self._auto_scrolling = False
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setSingleShot(True)
        self.scroll_timer.timeout.connect(self.scroll_bottom)
        bar = self.verticalScrollBar()
        bar.rangeChanged.connect(self._on_scroll_range_changed)
        bar.valueChanged.connect(self._on_scroll_value_changed)

    def _on_scroll_range_changed(self, _minimum: int, maximum: int):
        if self._pin_to_bottom and maximum > 0:
            self._auto_scrolling = True
            try:
                self.verticalScrollBar().setValue(maximum)
            finally:
                self._auto_scrolling = False

    def _on_scroll_value_changed(self, value: int):
        if self._auto_scrolling:
            return
        bar = self.verticalScrollBar()
        self._pin_to_bottom = value >= max(0, bar.maximum() - 40)

    def resizeEvent(self, event):
        was_pinned = self._pin_to_bottom
        super().resizeEvent(event)
        if was_pinned:
            self.scroll_timer.start(0)

    def scroll_bottom(self):
        bar = self.verticalScrollBar()
        self._auto_scrolling = True
        try:
            bar.setValue(bar.maximum())
        finally:
            self._auto_scrolling = False

    def expand_history(self):
        self.limit += 60
        self.set_messages(self.messages, self.translator)

    def sync_empty_state(self, tr, brand_hex=None):
        self.empty_title.setText(tr("empty_chat_title"))
        self.hint.setText(tr("chat_hint"))
        if brand_hex:
            self.empty_badge.setIcon(app_icon("brand", brand_hex, 22))
            self.empty_badge.setIconSize(QSize(22, 22))

    def set_messages(self, messages, tr):
        self.translator = tr
        if self.messages and messages and self.messages[0].get("id") != messages[0].get("id"):
            self.limit = 60
        visible = messages[-self.limit :]
        self.more.setText(tr("older_messages", count=max(0, len(messages) - self.limit)))
        self.more.setVisible(len(messages) > self.limit)
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= max(0, bar.maximum() - 40)
        conv_changed = bool(
            messages and (not self.messages or self.messages[0].get("id") != messages[0].get("id"))
        )
        self._pin_to_bottom = bool(at_bottom or conv_changed or len(messages) > len(self.messages))
        locale = tr("copy")
        self.empty_title.setText(tr("empty_chat_title"))
        self.hint.setText(tr("chat_hint"))
        self.hint.setVisible(not messages)
        self.empty_top_spacer.setVisible(not messages)
        self.empty_box.setVisible(not messages)
        for index, message in enumerate(visible):
            if (
                index < len(self.cards)
                and self.locale == locale
                and self.cards[index].message == message
                and self._previous_can_regenerate == self.can_regenerate
            ):
                continue
            card = MessageCard(
                message,
                tr,
                regenerate=self.regenerate_requested.emit,
                can_regenerate=self.can_regenerate,
                grant_folder=self.grant_folder_requested.emit,
                continue_run=self.continue_run_requested.emit,
            )
            card.authorize_directory_requested.connect(self.authorize_directory_requested.emit)
            if index < len(self.cards):
                old = self.cards[index]
                self.column.replaceWidget(old, card)
                old.setParent(None)
                old.deleteLater()
                self.cards[index] = card
            else:
                self.column.insertWidget(self.column.count() - 1, card)
                self.cards.append(card)
        while len(self.cards) > len(visible):
            card = self.cards.pop()
            self.column.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self.messages, self.locale = messages, locale
        self._previous_can_regenerate = self.can_regenerate
        if self.widget() and self.widget().layout():
            self.widget().layout().activate()
        if at_bottom:
            self.scroll_timer.start(0)

    def toPlainText(self):
        return "\n\n".join(message["content"] for message in self.messages)
