"""Native message cards. Model output is untrusted, including Markdown resources."""

import json
import math
import re

from PySide6.QtCore import QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF, QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
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


def statistics_text(stats, tr):
    if not stats:
        return ""
    sep = tr("decimal_separator")
    unavailable = tr("unavailable")
    parts = []
    for key, label, unit in (
        ("ttft_seconds", "ttft", "s"),
        ("tokens_per_second", "speed", "tok/s"),
        ("input_tokens", "input_tokens", ""),
        ("output_tokens", "output_tokens", ""),
        ("generation_seconds", "duration", "s"),
        ("model_load_seconds", "load_time", "s"),
        ("execution_device", "execution_device", ""),
        ("gpu_offloaded_layers", "offloaded_layers", ""),
    ):
        value = stats.get(key)
        if value is None:
            rendered = unavailable
        elif isinstance(value, float):
            rendered = f"{value:.2f}".replace(".", sep) + (f" {unit}" if unit else "")
        else:
            rendered = f"{value} {unit}".rstrip()
        parts.append(f"{tr(label)}: {rendered}")
    used, limit = stats.get("context_used_tokens"), stats.get("context_limit_tokens")
    if used is not None and limit:
        parts.append(f"{tr('context_usage')}: {used}/{limit} ({used / limit:.0%})")
    else:
        parts.append(f"{tr('context_usage')}: {unavailable}")
    reason = stats.get("finish_reason")
    if reason:
        reason = (
            tr("finish_" + reason) if reason in {"stop", "length", "cancelled", "error"} else reason
        )
        parts.append(f"{tr('finish_reason')}: {reason}")
    else:
        parts.append(f"{tr('finish_reason')}: {unavailable}")
    if stats.get("fallback_reason"):
        parts.append(tr("cpu_fallback"))
    return " · ".join(parts)


class SafeMarkdown(QTextBrowser):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setObjectName("messageText")
        self.setFrameShape(QFrame.NoFrame)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.document().setMarkdown(
            text, QTextDocument.MarkdownDialectGitHub | QTextDocument.MarkdownNoHTML
        )
        self.document().documentLayout().documentSizeChanged.connect(self.fit)
        self.fit()

    def loadResource(self, resource_type, url):
        # No local files, remote image requests, data URLs or external styles from model text.
        return None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()

    def fit(self, *_):
        self.document().setTextWidth(max(80, self.viewport().width()))
        height = math.ceil(self.document().size().height()) + 18
        if self.height() != height:
            self.setFixedHeight(height)


class MessageCard(QFrame):
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
        self.setObjectName("userBubble" if message["role"] == "user" else "assistantBubble")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.message = message
        self.can_regenerate = can_regenerate
        self._grant_folder = grant_folder
        self._continue_run = continue_run
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(18, 10, 18, 16)
        header = QHBoxLayout()
        name = (
            tr("you") if message["role"] == "user" else message.get("model_name") or tr("assistant")
        )
        title = QLabel(name)
        title.setTextFormat(Qt.PlainText)
        title.setWordWrap(True)
        title.setObjectName("messageAuthor")
        header.addWidget(title, 1)
        copy_label = tr("copy") if message["role"] == "assistant" else tr("copy_message")
        copy = QToolButton()
        self.icon_action(copy, "edit-copy", QStyle.SP_FileDialogContentsView, copy_label)
        copy.setAccessibleName(copy_label)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(message["content"]))
        copy.setEnabled(bool(message["content"]))
        if message["role"] != "assistant":
            header.addWidget(copy)
        self.layout_.addLayout(header)
        if message.get("reasoning_content"):
            reasoning = QPlainTextEdit(message["reasoning_content"])
            reasoning.setReadOnly(True)
            reasoning.setMaximumHeight(130)
            reasoning.hide()
            toggle = QPushButton(tr("reasoning"))
            toggle.setCheckable(True)
            toggle.toggled.connect(reasoning.setVisible)
            self.layout_.addWidget(toggle)
            self.layout_.addWidget(reasoning)
        self.agent_step_buttons = []
        self.agent_step_details = []
        self.agent_error_label = None
        self.agent_folder_box = None
        self.agent_folder_label = None
        self.agent_grant_button = None
        self.agent_continue_button = None
        if message["role"] == "assistant" and message.get("agent_run"):
            self._render_agent_activity(message["agent_run"], tr)
        self._body(message["content"], tr)
        if message["role"] == "user" and message.get("agent_run"):
            self._render_agent_activity(message["agent_run"], tr)
        if message.get("agent_run"):
            self._render_agent_folder_prompt(message["agent_run"], tr)
        details = statistics_text(message.get("statistics"), tr)
        if details:
            stats = message.get("statistics") or {}
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
            stats_row.addStretch()
            self.layout_.addLayout(stats_row)

        if message["role"] == "assistant":
            actions = QHBoxLayout()
            actions.addWidget(copy)
            retry = QToolButton()
            self.icon_action(retry, "view-refresh", QStyle.SP_BrowserReload, tr("regenerate"))
            retry.setToolTip(tr("regenerate_branch"))
            retry.setEnabled(
                can_regenerate
                and bool(message.get("content"))
                and message.get("status", "completed") == "completed"
            )
            if regenerate:
                retry.clicked.connect(lambda: regenerate(message))
            actions.addWidget(retry)
            info = QToolButton()
            self.icon_action(
                info, "dialog-information", QStyle.SP_MessageBoxInformation, tr("context_details")
            )
            info.setEnabled(bool(details))
            info.setCheckable(True)
            full_stats = QLabel(details)
            full_stats.setTextFormat(Qt.PlainText)
            full_stats.setWordWrap(True)
            full_stats.setTextInteractionFlags(Qt.TextSelectableByMouse)
            full_stats.hide()
            info.toggled.connect(full_stats.setVisible)
            actions.addWidget(info)
            actions.addStretch()
            self.layout_.addLayout(actions)
            self.layout_.addWidget(full_stats)

    def icon_action(self, button, name, fallback, label):
        button.setIcon(QIcon.fromTheme(name, self.style().standardIcon(fallback)))
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(32, 32)
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
            err_lbl = QLabel(tr(err_code))
            err_lbl.setObjectName("agentRunError")
            err_lbl.setTextFormat(Qt.PlainText)
            err_lbl.setWordWrap(True)
            self.layout_.addWidget(err_lbl)
            self.agent_error_label = err_lbl

    def _render_agent_folder_prompt(self, run, tr):
        if (
            not isinstance(run, dict)
            or not run.get("needs_folder_grant")
            or run.get("continued_by")
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

        def flush_prose():
            if prose:
                self.layout_.addWidget(SafeMarkdown("".join(prose), self))
                prose.clear()

        def flush_code():
            text = "".join(code).rstrip("\n")
            box = QPlainTextEdit(text)
            box.setReadOnly(True)
            box.setObjectName("codeBlock")
            box.setLineWrapMode(QPlainTextEdit.NoWrap)
            box.setFixedHeight(min(280, max(60, len(code) * 21 + 22)))
            button = QPushButton(tr("copy_code"))
            button.clicked.connect(lambda: QApplication.clipboard().setText(text))
            self.layout_.addWidget(button, alignment=Qt.AlignRight)
            self.layout_.addWidget(box)
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
    grant_folder_requested = Signal(object)
    continue_run_requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setObjectName("transcript")
        self.setAlignment(Qt.AlignHCenter)
        container = QWidget()
        container.setObjectName("transcriptColumn")
        container.setMaximumWidth(840)
        self.column = QVBoxLayout(container)
        self.column.setContentsMargins(12, 12, 12, 12)
        self.column.setSpacing(14)
        self.limit = 60
        self.more = QPushButton()
        self.more.clicked.connect(self.expand_history)
        self.column.addWidget(self.more)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.column.addWidget(self.hint)
        self.column.addStretch()
        self.setWidget(container)
        self.cards, self.messages, self.locale = [], [], None
        self.can_regenerate = False
        self._previous_can_regenerate = None
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setSingleShot(True)
        self.scroll_timer.timeout.connect(self.scroll_bottom)

    def scroll_bottom(self):
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def expand_history(self):
        self.limit += 60
        self.set_messages(self.messages, self.translator)

    def set_messages(self, messages, tr):
        self.translator = tr
        if self.messages and messages and self.messages[0].get("id") != messages[0].get("id"):
            self.limit = 60
        visible = messages[-self.limit :]
        self.more.setText(tr("older_messages", count=max(0, len(messages) - self.limit)))
        self.more.setVisible(len(messages) > self.limit)
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 40
        locale = tr("copy")
        self.hint.setText(tr("chat_hint"))
        self.hint.setVisible(not messages)
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
        if at_bottom:
            self.scroll_timer.start(0)

    def toPlainText(self):
        return "\n\n".join(message["content"] for message in self.messages)
