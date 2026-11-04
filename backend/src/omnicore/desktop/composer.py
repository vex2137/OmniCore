"""A bounded, multiline native composer; Enter sends and Shift+Enter inserts a line."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPlainTextEdit


class Composer(QPlainTextEdit):
    submitted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.textChanged.connect(self.fit)
        self.fit()

    def fit(self):
        lines = max(1, self.document().documentLayout().documentSize().height())
        self.setFixedHeight(min(160, max(72, round(lines * self.fontMetrics().lineSpacing() + 30))))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & (
            Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier
        ):
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)
