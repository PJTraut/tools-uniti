"""Environment Settings… (N31, 2026-11-05).

A dialog built from the environment's declarations
(`core.environments.settings`): one row per setting, grouped by section, a
choice as a drop-down, a number as a spin box, on/off as a check box, each
with its one-line description. **Restore Defaults** resets every row; OK
writes `settings.json` (only what differs from the defaults) and the change
applies at once.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from uniti.core.environments.settings import (
    CHOICE,
    FLAG,
    NUMBER,
    EnvironmentSetting,
    EnvironmentSettings,
    SettingValue,
    settings_path,
    store_environment_settings,
)


class EnvironmentSettingsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        environment_key: str,
        environment_label: str,
        settings: EnvironmentSettings,
        on_saved: Callable[[EnvironmentSettings], None] | None = None,
        on_manage_files: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{environment_label} Settings")
        self.environment_key = environment_key
        self.settings = settings
        path = settings_path(environment_key)
        self._on_saved = on_saved
        self.manage_files_button: QPushButton | None = None
        self.editors: dict[str, QWidget] = {}

        layout = QVBoxLayout(self)
        if not settings.declarations:
            empty = QLabel(f"{environment_label} has no settings.", self)
            layout.addWidget(empty)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            return

        sections: dict[str, QFormLayout] = {}
        for setting in settings.declarations:
            form = sections.get(setting.section)
            if form is None:
                box = QGroupBox(setting.section or environment_label, self)
                form = sections[setting.section] = QFormLayout(box)
                layout.addWidget(box)
            editor = self._editor(setting)
            editor.setToolTip(setting.description)
            self.editors[setting.key] = editor
            form.addRow(setting.label + ":", editor)
            if setting.description:
                hint = QLabel(setting.description, self)
                hint.setWordWrap(True)
                hint.setEnabled(False)  # greyed, as a hint
                form.addRow("", hint)
        self._show(settings)

        if path is None:
            note = QLabel("UNITI has no user data folder in this session, so changes last until it closes.", self)
            note.setWordWrap(True)
            layout.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        restore = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        restore.clicked.connect(lambda: self._show(self.settings.restored()))
        self.restore_button = restore
        if on_manage_files is not None:
            # N36: the environment's own files (Markdown: the CSS layers).
            manage = QPushButton("Manage Stylesheets…", self)
            manage.setToolTip("Open the configuration files: built-in, user and project CSS layers")
            manage.clicked.connect(on_manage_files)
            self.manage_files_button = manage
            buttons.addButton(manage, QDialogButtonBox.ButtonRole.ActionRole)
        layout.addWidget(buttons)

    def _editor(self, setting: EnvironmentSetting) -> QWidget:
        if setting.kind == CHOICE:
            combo = QComboBox(self)
            for value, label in setting.choices:
                combo.addItem(label, value)
            return combo
        if setting.kind == NUMBER:
            spin = QSpinBox(self)
            spin.setRange(setting.minimum, setting.maximum)
            return spin
        assert setting.kind == FLAG
        return QCheckBox(self)

    def _show(self, settings: EnvironmentSettings) -> None:
        for setting in settings.declarations:
            editor = self.editors[setting.key]
            value = settings.get(setting.key)
            if isinstance(editor, QComboBox):
                editor.setCurrentIndex(max(0, editor.findData(value)))
            elif isinstance(editor, QSpinBox):
                editor.setValue(int(value))
            elif isinstance(editor, QCheckBox):
                editor.setChecked(bool(value))

    def chosen_values(self) -> dict[str, SettingValue]:
        values: dict[str, SettingValue] = {}
        for key, editor in self.editors.items():
            if isinstance(editor, QComboBox):
                values[key] = editor.currentData()
            elif isinstance(editor, QSpinBox):
                values[key] = editor.value()
            elif isinstance(editor, QCheckBox):
                values[key] = editor.isChecked()
        return values

    def accept(self) -> None:
        chosen = self.settings.restored().with_values(self.chosen_values())
        try:
            store_environment_settings(self.environment_key, chosen)
        except OSError as exc:
            QMessageBox.warning(self, self.windowTitle(), f"Couldn't save the settings:\n{exc}")
            return
        self.settings = chosen
        if self._on_saved is not None:
            self._on_saved(chosen)
        super().accept()


__all__ = ["EnvironmentSettingsDialog"]
