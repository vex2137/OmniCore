"""Native message cards. Model output is untrusted, including Markdown resources."""

import math
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


def statistics_text(stats, tr):
    if not stats:
        return ""
    parts = []
    for key, label, unit in (
        ("tokens_per_second", "speed", "tok/s"),
        ("input_tokens", "input_tokens", ""),
        ("output_tokens", "output_tokens", ""),
        ("ttft_seconds", "ttft", "s"),
        ("first_answer_seconds", "first_answer", "s"),
        ("generation_seconds", "duration", "s"),
        ("model_load_seconds", "load_time", "s"),
    ):
        value = stats.get(key)
        if value is not None:
            number = f"{value:.2f}" if isinstance(value, float) else str(value)
            parts.append(f"{tr(label)}: {number} {unit}".rstrip())
    used, limit = stats.get("context_used_tokens"), stats.get("context_limit_tokens")
    if used is not None and limit:
        parts.append(f"{tr('context_usage')}: {used}/{limit} ({used / limit:.0%})")
    if stats.get("finish_reason"):
        reason = stats["finish_reason"]
        reason = (
            tr("finish_" + reason) if reason in {"stop", "length", "cancelled", "error"} else reason
        )
        parts.append(f"{tr('finish_reason')}: {reason}")
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
    def __init__(self, message, tr, parent=None):
        super().__init__(parent)
        self.setObjectName("userBubble" if message["role"] == "user" else "assistantBubble")
        self.message = message
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
        copy = QPushButton(tr("copy"))
        copy.setAccessibleName(tr("copy"))
        copy.clicked.connect(lambda: QApplication.clipboard().setText(message["content"]))
        copy.setEnabled(bool(message["content"]))
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
        self._body(message["content"], tr)
        details = statistics_text(message.get("statistics"), tr)
        if details:
            label = QLabel(details)
            label.setObjectName("messageStats")
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.layout_.addWidget(label)

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
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setObjectName("transcript")
        container = QWidget()
        self.column = QVBoxLayout(container)
        self.column.setContentsMargins(6, 10, 6, 10)
        self.column.setSpacing(16)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.column.addWidget(self.hint)
        self.column.addStretch()
        self.setWidget(container)
        self.cards, self.messages, self.locale = [], [], None
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setSingleShot(True)
        self.scroll_timer.timeout.connect(self.scroll_bottom)

    def scroll_bottom(self):
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def set_messages(self, messages, tr):
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 40
        locale = tr("copy")
        self.hint.setText(tr("chat_hint"))
        self.hint.setVisible(not messages)
        for index, message in enumerate(messages):
            if (
                index < len(self.cards)
                and self.locale == locale
                and self.cards[index].message == message
            ):
                continue
            card = MessageCard(message, tr)
            if index < len(self.cards):
                old = self.cards[index]
                self.column.replaceWidget(old, card)
                old.deleteLater()
                self.cards[index] = card
            else:
                self.column.insertWidget(self.column.count() - 1, card)
                self.cards.append(card)
        while len(self.cards) > len(messages):
            card = self.cards.pop()
            self.column.removeWidget(card)
            card.deleteLater()
        self.messages, self.locale = messages, locale
        if at_bottom:
            self.scroll_timer.start(0)

    def toPlainText(self):
        return "\n\n".join(message["content"] for message in self.messages)
