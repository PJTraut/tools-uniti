import os
from dataclasses import replace

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture
def window(tmp_path):
    from PySide6.QtWidgets import QApplication
    from uniti.app.settings import Settings, SettingsStore
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.theme import apply_theme
    app = QApplication.instance() or QApplication([])
    store = SettingsStore(tmp_path / 'settings.json')
    store.save(Settings(theme_mode='Dark', editor_zoom_percent=130))
    window = UNITIMainWindow(settings_store=store)
    yield window
    for widget in list(app.topLevelWidgets()):
        if widget.__class__.__name__ == 'ThemeEditor':
            widget.reject()
    window.close_all_documents(force=True)
    window.close()
    apply_theme(app, 'System')


def test_preview_new_window_cancel_restores_exact_state(window):
    from PySide6.QtWidgets import QApplication
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.theme import active_theme
    from uniti.ui.theme_editor import ThemeEditor
    app = QApplication.instance()
    before = active_theme(app)
    editor = ThemeEditor(window)
    editor.select_profile('Paper')
    assert app.palette().base().color().name() == '#fbf7ef'
    other = UNITIMainWindow(settings_store=window._settings_store)
    try:
        assert active_theme(app).mode == 'Paper'
        assert other.palette().base().color().name() == '#fbf7ef'
        editor.reject()
        app.processEvents()
        assert active_theme(app) == before
        assert other.palette().base().color() == before.palette.base().color()
        assert window._settings_store.load().theme_mode == 'Dark'
    finally:
        other.close_all_documents(force=True)
        other.close()


def test_clone_edit_apply_restart_and_unrelated_settings(window):
    from PySide6.QtWidgets import QApplication
    from uniti.ui.theme_editor import ThemeEditor
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.theme import active_theme
    editor = ThemeEditor(window)
    editor.select_profile('Paper')
    editor.clone_profile()
    custom_id = editor.draft.id
    editor.set_color('editor.base', '#fff1df')
    assert editor.apply_changes()
    editor.reject()
    state = window._theme_store.load()
    assert state.active_id == custom_id
    assert state.resolve().colors['editor.base'] == '#fff1df'
    assert window._settings_store.load().editor_zoom_percent == 130
    restarted = UNITIMainWindow(settings_store=window._settings_store)
    try:
        assert active_theme(QApplication.instance()).editor.base.name() == '#fff1df'
    finally:
        restarted.close_all_documents(force=True)
        restarted.close()


def test_failed_apply_stays_open_reports_error_and_cancel_restores(window, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from uniti.ui.theme_editor import ThemeEditor
    from uniti.ui.theme import active_theme
    from uniti.app import theme_profiles
    before = active_theme(QApplication.instance())
    editor = ThemeEditor(window)
    editor.select_profile('Slate')
    editor.clone_profile()
    def fail(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(theme_profiles, 'atomic_write_json', fail)
    assert not editor.apply_changes()
    assert 'disk full' in editor.error_label.text()
    assert window._theme_state.active_id == 'Dark'
    editor.reject()
    assert active_theme(QApplication.instance()) == before


def test_packaged_readonly_reset_and_delete_active_custom(window):
    from uniti.ui.theme_editor import ThemeEditor
    editor = ThemeEditor(window)
    editor.select_profile('Paper')
    with pytest.raises(ValueError, match='read-only'):
        editor.set_color('editor.base', '#ffffff')
    editor.clone_profile()
    custom_id = editor.draft.id
    original = editor.draft.colors['editor.base']
    editor.set_color('editor.base', '#ffffff')
    editor.reset_profile()
    assert editor.draft.colors['editor.base'] == original
    assert editor.apply_changes()
    editor.delete_profile()
    assert editor.apply_changes()
    state = window._theme_store.load()
    assert state.active_id == 'Paper'
    assert all(p.id != custom_id for p in state.profiles)
    editor.reject()


def test_high_contrast_rejects_invalid_draft_with_visible_feedback(window):
    from uniti.ui.theme_editor import ThemeEditor
    window.set_theme_contrast('High Contrast')
    editor = ThemeEditor(window)
    editor.select_profile('Paper')
    editor.clone_profile()
    with pytest.raises(ValueError, match='contrast'):
        editor.set_color('editor.text', editor.draft.colors['editor.base'])
    assert 'contrast' in editor.feedback_label.text().lower()
    editor.reject()


def test_system_preview_uses_original_platform_palette(window):
    from PySide6.QtWidgets import QApplication
    from uniti.ui.theme import apply_theme, active_theme
    from uniti.ui.theme_editor import ThemeEditor
    app = QApplication.instance()
    system = apply_theme(app, 'System')
    window.set_theme('Dark')
    editor = ThemeEditor(window)
    editor.select_profile('System')
    assert active_theme(app).palette == system.palette
    editor.reject()


def test_closing_owner_cancels_preview(window):
    from PySide6.QtWidgets import QApplication
    from uniti.ui.theme import active_theme, preview_active
    from uniti.ui.theme_editor import ThemeEditor
    app = QApplication.instance()
    before = active_theme(app)
    editor = ThemeEditor(window)
    editor.select_profile('Paper')
    window.close()
    assert not preview_active(app)
    assert active_theme(app) == before


def test_service_windows_views_and_find_replace_follow_preview(tmp_path):
    from uniti.app.recovery_manager import RecoveryManager
    from PySide6.QtWidgets import QApplication
    from uniti.app.service import UNITIService, QuitChoice
    from uniti.app.settings import SettingsStore
    from uniti.app.session_store import SessionStore
    from uniti.resources import ResourceManager
    from uniti.ui.theme_editor import ThemeEditor
    from uniti.ui.theme import active_theme
    app = QApplication.instance() or QApplication([])
    service = UNITIService(resource_manager=ResourceManager(max_workers=1),
                           settings_store=SettingsStore(tmp_path / 'settings.json'),
                           session_store=SessionStore(tmp_path / 'sessions'),
                           recovery_manager=RecoveryManager(tmp_path / 'recovery'))
    first = service.new_window()
    path = tmp_path / 'sample.txt'
    path.write_text('a b\tword\n')
    first.open_path(path)
    first.show_find()
    before = active_theme(app)
    editor = ThemeEditor(first)
    try:
        editor.select_profile('Slate')
        second = service.new_window()
        second_path = tmp_path / "other.txt"
        second_path.write_text("second window\n")
        second.open_path(second_path)
        app.processEvents()
        assert first._find_replace.palette().base().color().name() == '#202830'
        for window in (first, second):
            assert window.views[0].theme_tokens.base.name() == '#202830'
        editor.reject()
        app.processEvents()
        for window in (first, second):
            assert window.views[0].theme_tokens == before.editor
        assert first._find_replace.palette().base().color() == before.palette.base().color()
    finally:
        editor.reject()
        service.request_quit(lambda entry: QuitChoice.DISCARD)
