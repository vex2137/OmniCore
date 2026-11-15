"""A bounded, multiline native composer; Enter sends and Shift+Enter inserts a line."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPlainTextEdit


class Composer(QPlainTextEdit):
    submitted = Signal()
    focus_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.textChanged.connect(self.fit)
        self.fit()

    def fit(self):
        lines = max(1, self.document().documentLayout().documentSize().height())
        self.setFixedHeight(min(156, max(38, round(lines * self.fontMetrics().lineSpacing() + 14))))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focus_changed.emit(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.focus_changed.emit(False)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & (
            Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier
        ):
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)
