"""Draft-based global color editor; Cancel restores the exact preview snapshot."""
from __future__ import annotations

from dataclasses import replace
import uuid

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from uniti.app.theme_profiles import (
    BUILTIN_IDS, COLOR_ROLES, ThemeProfileState, packaged_profiles,
)
from uniti.ui.theme import (
    active_theme, build_profile_theme, build_theme, contrast_feedback,
    install_theme, profile_from_spec, system_theme_palette,
)


class ThemeEditor(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.app = QApplication.instance()
        if getattr(self.app, '_uniti_theme_editor', None) is not None:
            raise RuntimeError('A theme preview is already open')
        self.app._uniti_theme_editor = self
        self._snapshot = active_theme(self.app)
        self._system_palette = system_theme_palette(self.app)
        self._contrast = self._snapshot.contrast
        self._profiles = {p.id: p for p in owner._theme_state.profiles}
        self._baseline = dict(self._profiles)
        self._packaged = {p.id: p for p in packaged_profiles()}
        self._selected = owner._theme_state.active_id
        self.draft = None
        self.setWindowTitle('Edit Themes')
        self.resize(620, 510)
        layout = QVBoxLayout(self)
        self.profile_combo = QComboBox(self)
        self.profile_combo.setAccessibleName('Theme profile')
        layout.addWidget(self.profile_combo)
        self.readonly_label = QLabel(self)
        layout.addWidget(self.readonly_label)
        form = QFormLayout()
        self.name_edit = QLineEdit(self)
        self.name_edit.setMaxLength(64)
        self.name_edit.editingFinished.connect(self._rename)
        form.addRow('Name', self.name_edit)
        self.role_combo = QComboBox(self)
        for role in COLOR_ROLES:
            category, label = role.split('.')
            self.role_combo.addItem(category.title() + ': ' + label.replace('_', ' ').title(), role)
        self.role_combo.currentIndexChanged.connect(self._show_color)
        form.addRow('Color role', self.role_combo)
        row = QHBoxLayout()
        self.color_edit = QLineEdit(self)
        self.color_edit.setPlaceholderText('#RRGGBB')
        self.color_edit.setAccessibleName('Color hexadecimal value')
        self.color_edit.editingFinished.connect(self._edit_color)
        self.color_button = QPushButton('Choose Color…', self)
        self.color_button.clicked.connect(self._choose_color)
        row.addWidget(self.color_edit)
        row.addWidget(self.color_button)
        form.addRow('Color', row)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.clone_button = QPushButton('Clone', self)
        self.clone_button.clicked.connect(self.clone_profile)
        self.reset_button = QPushButton('Reset', self)
        self.reset_button.setToolTip('Restore this draft to its last applied colors, or its initial clone colors.')
        self.reset_button.clicked.connect(self.reset_profile)
        self.delete_button = QPushButton('Delete', self)
        self.delete_button.clicked.connect(self.delete_profile)
        for button in (self.clone_button, self.reset_button, self.delete_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.feedback_label = QLabel(self)
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setAccessibleName('Contrast feedback')
        layout.addWidget(self.feedback_label)
        self.error_label = QLabel(owner._theme_state.error or '', self)
        self.error_label.setWordWrap(True)
        self.error_label.setAccessibleName('Theme save status')
        layout.addWidget(self.error_label)
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply_changes)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.profile_combo.currentIndexChanged.connect(self._selection_changed)
        self._refresh_profiles()
        self.select_profile(self._selected)

    def _refresh_profiles(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for selected in BUILTIN_IDS:
            self.profile_combo.addItem(selected, selected)
        for profile in self._profiles.values():
            self.profile_combo.addItem(profile.name, profile.id)
        self.profile_combo.setCurrentIndex(self.profile_combo.findData(self._selected))
        self.profile_combo.blockSignals(False)

    def _selection_changed(self, index):
        selected = self.profile_combo.itemData(index)
        if selected:
            self.select_profile(selected)

    def select_profile(self, selected):
        if selected in self._profiles:
            profile = self._profiles[selected]
        elif selected in self._packaged:
            profile = self._packaged[selected]
        elif selected in ('System', 'Light', 'Dark'):
            spec = self._snapshot if selected == self._snapshot.mode else build_theme(self._system_palette, selected, self._contrast)
            base_mode = 'Dark' if spec.editor.base.lightnessF() < .5 else 'Light'
            profile = profile_from_spec(spec, selected, selected, base_mode)
        else:
            raise ValueError('Unknown profile')
        self._selected = selected
        self.draft = profile
        self._refresh_profiles()
        self._refresh_draft()
        self._preview()

    def _refresh_draft(self):
        readonly = self.draft.id in BUILTIN_IDS
        self.readonly_label.setText('Built-in theme — clone to edit its colors.' if readonly else 'Custom theme — changes preview in every window. Apply saves them.')
        self.name_edit.setText(self.draft.name)
        self.name_edit.setReadOnly(readonly)
        for control in (self.color_edit, self.color_button, self.reset_button, self.delete_button):
            control.setEnabled(not readonly)
        self.clone_button.setEnabled(len(self._profiles) < 32)
        self._show_color()

    def _show_color(self, *_):
        if self.draft is not None:
            self.color_edit.setText(self.draft.colors[self.role_combo.currentData()])

    def _preview(self):
        if self._selected in ('System', 'Light', 'Dark'):
            spec = (self._snapshot if self._selected == self._snapshot.mode
                    else build_theme(self._system_palette, self._selected, self._contrast))
        else:
            spec = build_profile_theme(self._snapshot.palette, self.draft, self._contrast)
        install_theme(self.app, spec)
        feedback = contrast_feedback(spec)
        failed = [(name, ratio, threshold) for name, ratio, threshold in feedback if ratio < threshold]
        editor_ratio = feedback[0][1]
        summary = f'{self._contrast} contrast — editor text {editor_ratio:.2f}:1. '
        if failed:
            summary += 'Below recommended contrast: ' + '; '.join(f'{n} {r:.2f}:1 (target {t:g}:1)' for n, r, t in failed)
        else:
            summary += 'Text, selection, controls and markers meet the displayed mode’s targets.'
        self.feedback_label.setText(summary)

    def clone_profile(self):
        if len(self._profiles) >= 32:
            self.error_label.setText('At most 32 custom profiles are supported.')
            return
        profile = profile_from_spec(active_theme(self.app), 'custom-' + uuid.uuid4().hex,
                                    (self.draft.name[:59] + ' Copy'), self.draft.base_mode)
        self._profiles[profile.id] = profile
        self._baseline[profile.id] = profile
        self.select_profile(profile.id)

    def _editable(self):
        if self.draft.id in BUILTIN_IDS:
            raise ValueError('Built-in profiles are read-only; clone first')

    def set_color(self, role, color):
        self._editable()
        colors = dict(self.draft.colors)
        colors[role] = color
        candidate = replace(self.draft, colors=colors)
        if self._contrast == 'High Contrast':
            spec = build_profile_theme(self._snapshot.palette, candidate, self._contrast, overlay=False)
            if any(r < t for _, r, t in contrast_feedback(spec)):
                self.feedback_label.setText('High Contrast: this color would violate the required contrast thresholds.')
                raise ValueError('Color violates High Contrast contrast thresholds')
        self.draft = candidate
        self._profiles[candidate.id] = candidate
        self._show_color()
        self._preview()

    def _edit_color(self):
        try:
            self.set_color(self.role_combo.currentData(), self.color_edit.text())
            self.error_label.clear()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            self._show_color()

    def _choose_color(self):
        color = QColorDialog.getColor(QColor(self.color_edit.text()), self, 'Choose theme color')
        if color.isValid():
            self.color_edit.setText(color.name())
            self._edit_color()

    def _rename(self):
        if self.draft.id in BUILTIN_IDS:
            return
        try:
            candidate = replace(self.draft, name=self.name_edit.text())
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        self.draft = candidate
        self._profiles[candidate.id] = candidate
        self._refresh_profiles()

    def reset_profile(self):
        self._editable()
        self._profiles[self.draft.id] = self._baseline[self.draft.id]
        self.select_profile(self.draft.id)

    def delete_profile(self):
        self._editable()
        fallback = 'Slate' if self.draft.base_mode == 'Dark' else 'Paper'
        del self._profiles[self.draft.id]
        self.select_profile(fallback)

    def apply_changes(self):
        state = ThemeProfileState(tuple(self._profiles.values()), self._selected)
        try:
            result = self.owner.commit_theme_state(state)
        except (OSError, ValueError) as exc:
            self.error_label.setText('Could not save theme: ' + str(exc))
            return False
        self._snapshot = active_theme(self.app)
        self._baseline = dict(self._profiles)
        self.error_label.setText('Applied.' if result is None or result.directory_synced else 'Applied; directory sync is unavailable on this filesystem.')
        return True

    def done(self, result):
        if getattr(self.app, '_uniti_theme_editor', None) is self:
            install_theme(self.app, self._snapshot)
            self.app._uniti_theme_editor = None
        super().done(result)
