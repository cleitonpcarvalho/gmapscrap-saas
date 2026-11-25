from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit


class NicheInput(QLineEdit):
    """Editable registry picker; opening the field always shows the full list."""

    def show_suggestions(self, *, all_items=False):
        completer = self.completer()
        if not completer or not self.isEnabled() or not self.hasFocus():
            return
        completer.setCompletionPrefix("" if all_items else self.text())
        if completer.completionCount():
            completer.complete()
        else:
            completer.popup().hide()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if event.reason() != Qt.FocusReason.PopupFocusReason:
            self.show_suggestions(all_items=True)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.show_suggestions(all_items=True)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Down and not self.completer().popup().isVisible():
            self.show_suggestions(all_items=True)
            return
        super().keyPressEvent(event)
