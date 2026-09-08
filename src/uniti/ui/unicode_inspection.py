"""Application-wide held-modifier state; never consumes input events."""

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from uniti.app.inspection_shortcut import (
    DEFAULT_INSPECTION_MODIFIERS,
    normalize_inspection_modifiers,
)

_MODIFIERS = {
    "Ctrl": Qt.KeyboardModifier.ControlModifier,
    "Alt": Qt.KeyboardModifier.AltModifier,
    "Shift": Qt.KeyboardModifier.ShiftModifier,
    "Meta": Qt.KeyboardModifier.MetaModifier,
}
_KEYS = {
    Qt.Key.Key_Control: _MODIFIERS["Ctrl"],
    Qt.Key.Key_Alt: _MODIFIERS["Alt"],
    Qt.Key.Key_Shift: _MODIFIERS["Shift"],
    Qt.Key.Key_Meta: _MODIFIERS["Meta"],
}
_MASK = _MODIFIERS["Ctrl"] | _MODIFIERS["Alt"] | _MODIFIERS["Shift"] | _MODIFIERS["Meta"]


class UnicodeInspection(QObject):
    changed = Signal()

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.active = False
        self.modifiers = DEFAULT_INSPECTION_MODIFIERS
        self._required = _MODIFIERS["Ctrl"] | _MODIFIERS["Alt"]
        app.installEventFilter(self)

    def set_modifiers(self, value: str) -> None:
        selected = normalize_inspection_modifiers(value)
        if selected == self.modifiers:
            return
        self.modifiers = selected
        self._required = Qt.KeyboardModifier.NoModifier
        for name in self.modifiers.split("+"):
            self._required |= _MODIFIERS.get(name, Qt.KeyboardModifier.NoModifier)
        self._set_active(False)

    def _set_active(self, active: bool) -> None:
        if self.active != active:
            self.active = active
            self.changed.emit()

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            modifiers = event.modifiers() & _MASK
            changed = _KEYS.get(event.key(), Qt.KeyboardModifier.NoModifier)
            if kind == QEvent.Type.KeyPress:
                modifiers |= changed
            else:
                modifiers &= ~changed
            self._set_active(bool(self.modifiers) and modifiers == self._required)
        elif kind == QEvent.Type.ApplicationDeactivate:
            self._set_active(False)
        elif kind == QEvent.Type.ApplicationStateChange:
            if QApplication.applicationState() != Qt.ApplicationState.ApplicationActive:
                self._set_active(False)
        return False


def unicode_inspection(app: QApplication) -> UnicodeInspection:
    controller = getattr(app, "_uniti_unicode_inspection", None)
    if controller is None:
        controller = UnicodeInspection(app)
        app._uniti_unicode_inspection = controller
    return controller
