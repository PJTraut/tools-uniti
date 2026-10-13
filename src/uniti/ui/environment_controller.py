"""Per-environment menu, commands and Plain Text fallback for the main window (ADR-0014).

The environment of the active document owns one top-level menu, titled after
it (e.g. **USFM**): that environment's functions/tools as separated blocks,
then **Plain Text Mode**, then **File Type Environments…**. The menu is
rebuilt whenever the active view changes, so it always shows exactly the
active document's capabilities.

Plain Text Mode is "plain text within the environment": the view renders as
Plain Text and every environment command is off, but the document keeps its
environment identity (the menu still names it, and one click turns the
environment back on). It is per view, like the other BF-075 view settings,
and every environment except Plain Text itself offers it. A failed
activation (`ActiveEnvironment.failed`) lands in the same state
automatically and says so in the menu.

Each document can also be pinned to an environment other than its
extension's (**Environment for This Document**, persisted in the session),
and the cross-environment command slots (`environment.format`,
`environment.validate`, `environment.go_to`, …, plus
`environment.plain_mode`) are registered commands with rebindable shortcuts:
each runs the active environment's command of the same local id and is
disabled where that environment has none.

Commands are Qt-free (`core/environment_commands.py`); this controller only
asks for a prompt argument when a command wants one and applies the
declarative result. A command that raises is reported, never propagated —
an environment must never break the editor (ADR-0013 decision 6).
"""

from __future__ import annotations

import logging
import weakref
from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QInputDialog, QMenu, QMenuBar, QMessageBox

from uniti.app.file_environment_manager import ActiveEnvironment
from uniti.core.environment import EnvironmentContext
from uniti.core.environment_commands import (
    CommandResult,
    EnvironmentCommand,
    NavigateTo,
    ReplaceDocumentText,
    ShowFindings,
    ShowMessage,
    ShowStyleInspector,
    ShowUndefinedMarkup,
    SaveTextFile,
    UNDEFINED_MARKUP_COMMAND,
    environment_commands,
)
from uniti.core.environments.catalog import (
    ENVIRONMENTS,
    ENVIRONMENTS_BY_KEY,
    PLAIN_ENVIRONMENT_KEY,
    PROJECT_ENVIRONMENTS,
    EnvironmentDescriptor,
    descriptor_for_key,
    environment_available,
)
from uniti.core.syntax_profiles import PLAIN_TEXT, PROFILES_BY_KEY, SyntaxProfile
from uniti.ui.rich_view import PLAIN_TEXT_LABEL

if TYPE_CHECKING:
    from uniti.core.document import Document
    from uniti.ui.environment_findings_dialog import EnvironmentFindingsDialog
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.text_view import UNITITextView

logger = logging.getLogger("uniti.environment.ui")


class EnvironmentController:
    def __init__(self, window: "UNITIMainWindow") -> None:
        self._window = window
        # Per-document environment pins for windows with no service (the
        # service-owned path stores them on `DocumentEntry`).
        self._standalone_overrides: weakref.WeakKeyDictionary[Document, str] = (
            weakref.WeakKeyDictionary()
        )
        self._slot_actions: dict[str, QAction] = {}
        self._host_actions: dict[str, QAction] = {}
        self._findings_dialog: EnvironmentFindingsDialog | None = None
        self._style_inspector = None
        self.menu: QMenu | None = None
        self.command_actions: dict[str, QAction] = {}
        self.view_actions: dict[str | None, QAction] = {}
        self._owned_command_actions: list[QAction] = []
        self.plain_mode_action: QAction | None = None
        self.assignment_action: QAction | None = None
        self.move_to_window_action: QAction | None = None
        self.rename_window_action: QAction | None = None
        self.configuration_action: QAction | None = None
        self.configuration_dialog = None
        self.undefined_dialogs: dict[str, object] = {}  # view id -> report
        self.versification_menu: QMenu | None = None
        self.versification_actions: dict[str | None, QAction] = {}
        self._standalone_versifications: weakref.WeakKeyDictionary[Document, str] = weakref.WeakKeyDictionary()

    # --- resolution -------------------------------------------------------

    def _entry_for(self, document: "Document"):
        service = self._window._service
        if service is None:
            return None
        entry = service.documents.find_path(document.path)
        return entry if entry is not None and entry.document is document else None

    def extension_environment_key(self, document: "Document") -> str:
        """The environment the document's extension gives it, or Plain Text
        when that environment needs a project the file isn't in (T1)."""

        return self._window._file_environment_manager.resolve_path_key(
            document.path, self._window._settings.syntax_extension_overrides
        )

    def environment_override_for(self, document: "Document") -> str | None:
        entry = self._entry_for(document)
        if entry is not None:
            return entry.environment_override
        return self._standalone_overrides.get(document)

    def environment_key_for(self, document: "Document") -> str:
        """The document's pinned environment, else its extension's.

        Computed from the current extension mapping every time (rather than
        trusting the key stored at adoption), and synced back onto the
        registry entry so service-level readers see the same answer.
        """

        override = self.environment_override_for(document)
        if override in ENVIRONMENTS_BY_KEY and environment_available(override, document.path):
            key = override
        else:
            # No pin, or one to an environment the file can't live in (a
            # restored USFM pin on a file outside a project, T1).
            key = self.extension_environment_key(document)
        entry = self._entry_for(document)
        if entry is not None and entry.environment_key != key:
            self._window._service.documents.set_environment_key(entry.document_id, key)
        return key

    def set_document_environment(
        self, environment_key: str | None, view: "UNITITextView | None" = None, *, move: bool = True
    ) -> None:
        """Pin the active document to `environment_key`; `None` follows its extension.

        The file then lives in its environment (ADR-0017): with `move`, a
        file pinned to an environment moves into that environment's window
        for its group, and a file in an environment window that no longer
        matches its environment moves out to the right one.
        """

        view = view if view is not None else self._window.current_view
        if view is None:
            return
        if environment_key is not None and environment_key not in ENVIRONMENTS_BY_KEY:
            raise ValueError(f"unknown environment: {environment_key!r}")
        document = view.document
        if environment_key is not None and not environment_available(environment_key, document.path):
            label = descriptor_for_key(environment_key).label
            self._window.statusBar().showMessage(
                f"{document.path.name} isn't in a Paratext project, so it can't be {label}", 6000
            )
            self._sync_document_environment_menu(view)
            return
        entry = self._entry_for(document)
        previous = self.environment_key_for(document)
        if entry is not None:
            self._window._service.documents.set_environment_override(entry.document_id, environment_key)
        elif environment_key is None:
            self._standalone_overrides.pop(document, None)
        else:
            self._standalone_overrides[document] = environment_key
        key = self.environment_key_for(document)
        if entry is not None and key != previous and entry.group_id is not None:
            # Groups belong to an environment (round 3 T2): another
            # environment's group of the same id is a different group.
            self._window._service.documents.set_group(entry.document_id, None)
            recent = self._window._recent_files_store
            if recent is not None:
                recent.record_group(str(entry.canonical_path), None)
            self._window._refresh_group_indicator(view.view_id)
        self._window._refresh_all_syntax_profiles()
        self._window._environment_state_changed(view)
        window = self._window
        if not move or window._service is None or window.view_for_id(view.view_id) is not view:
            return
        in_environment_window = window.environment_window is not None
        if environment_key is not None or (in_environment_window and window.environment_window[0] != key):
            if not in_environment_window or window.environment_window[0] != key:
                window.move_to_environment_window(view)

    def active_for(self, document: "Document") -> ActiveEnvironment:
        return self._window._file_environment_manager.active_for(
            document, self.environment_key_for(document)
        )

    def descriptor_for(self, document: "Document") -> EnvironmentDescriptor:
        return descriptor_for_key(self.environment_key_for(document))

    def is_plain_mode(self, view: "UNITITextView") -> bool:
        """Whether `view` is in Plain Text Mode (chosen, or a failed activation)."""

        return view.environment_plain_mode or self.active_for(view.document).failed

    def default_profile_for(self, document: "Document") -> SyntaxProfile:
        """The profile a new view of `document` renders with."""

        if self.active_for(document).failed:
            return PLAIN_TEXT
        return self.descriptor_for(document).profile

    def effective_profile(
        self, view: "UNITITextView", choice_key: str | None = None, *, use_view_choice: bool = True
    ) -> SyntaxProfile:
        """Plain Text Mode, else the per-view override, else the environment's profile."""

        if self.is_plain_mode(view):
            return PLAIN_TEXT
        key = view.syntax_choice_key if use_view_choice else choice_key
        if key is not None:
            return PROFILES_BY_KEY.get(key, PLAIN_TEXT)
        return self.descriptor_for(view.document).profile

    def commands_for(self, view: "UNITITextView | None") -> tuple[EnvironmentCommand, ...]:
        if view is None:
            return ()
        return environment_commands(self.active_for(view.document).environment)

    def command_available(self, command_id: str, view: "UNITITextView | None" = None) -> bool:
        view = view if view is not None else self._window.current_view
        if view is None or not view.isEnabled() or self.is_plain_mode(view):
            return False
        return any(command.command_id == command_id for command in self.commands_for(view))

    def offers_host_feature(self, view: "UNITITextView | None", feature: str) -> bool:
        if view is None or self.is_plain_mode(view):
            return False
        return any(command.host_feature == feature for command in self.commands_for(view))

    # --- Plain Text Mode --------------------------------------------------

    def set_plain_mode(self, enabled: bool, view: "UNITITextView | None" = None) -> None:
        view = view if view is not None else self._window.current_view
        if view is None:
            return
        view.environment_plain_mode = bool(enabled)
        view.set_syntax_profile(self.effective_profile(view))
        self._window._environment_state_changed(view)

    def toggle_plain_mode(self) -> None:
        view = self._window.current_view
        if view is not None and not self.active_for(view.document).failed:
            self.set_plain_mode(not view.environment_plain_mode, view)

    def forget_view(self, view_id: str) -> None:
        """A view closed; Plain Text Mode lives on the view, so nothing to drop."""

    # --- menu ---------------------------------------------------------------

    def register_host_action(self, feature: str, action: QAction) -> None:
        self._host_actions[feature] = action

    def register_slot_actions(self, actions: dict[str, QAction], plain_mode_action: QAction) -> None:
        """Window-owned, shortcut-bearing actions for cross-environment slots
        (local command id -> action) and Plain Text Mode."""

        self._slot_actions = dict(actions)
        self.plain_mode_action = plain_mode_action

    def build_menu(self, menu_bar: QMenuBar) -> QMenu:
        window = self._window
        self.menu = menu_bar.addMenu("Environment")
        # Fixed entries are window-owned and persistent: `QMenu.clear()` on
        # rebuild then only detaches them, so rebuilding from inside one of
        # their own handlers (toggling Plain Text Mode, saving the
        # assignment editor) never deletes the action that is mid-signal.
        self._no_document_action = QAction("No document open", window)
        self._no_document_action.setEnabled(False)
        self._no_tools_action = QAction("No environment tools for plain text", window)
        self._no_tools_action.setEnabled(False)
        self._failed_action = QAction("", window)
        self._failed_action.setEnabled(False)
        if self.plain_mode_action is None:
            self.plain_mode_action = QAction("Plain Text Mode", window)
            self.plain_mode_action.setCheckable(True)
            self.plain_mode_action.triggered.connect(lambda _checked=False: self.toggle_plain_mode())
        # An exclusive picker, so a submenu (like Whitespace/Tab Width).
        self.document_environment_menu = QMenu("Environment for This Document", window)
        group = QActionGroup(window)
        group.setExclusive(True)
        self.document_environment_actions: dict[str | None, QAction] = {}
        by_extension = QAction("By Extension", window)
        by_extension.setCheckable(True)
        by_extension.triggered.connect(lambda _checked=False: self.set_document_environment(None))
        group.addAction(by_extension)
        self.document_environment_menu.addAction(by_extension)
        self.document_environment_menu.addSeparator()
        self.document_environment_actions[None] = by_extension
        for descriptor in ENVIRONMENTS:
            action = QAction(descriptor.label, window)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, key=descriptor.key: self.set_document_environment(key)
            )
            group.addAction(action)
            self.document_environment_menu.addAction(action)
            self.document_environment_actions[descriptor.key] = action
        self.assignment_action = QAction("File Type Environments…", window)
        self.assignment_action.triggered.connect(
            lambda _checked=False: window.show_environment_assignment_editor()
        )
        self.refresh()
        return self.menu

    def refresh(self) -> None:
        """Retitle and rebuild the environment menu for the active view."""

        menu = self.menu
        if menu is None:
            return
        view = self._window.current_view
        menu.clear()
        for action in self._owned_command_actions:
            action.deleteLater()
        self._owned_command_actions = []
        self.command_actions = {}
        self.view_actions = {}
        available = {
            command.command_id
            for command in (self.commands_for(view) if view is not None else ())
        }
        for local_id, action in self._slot_actions.items():
            action.setEnabled(local_id in available and self.command_available(local_id, view))
        # The window re-syncs Markdown Preview itself afterwards (it stays
        # enabled while a preview is open, to allow closing it).
        for feature, action in self._host_actions.items():
            action.setEnabled(self.offers_host_feature(view, feature))
        self._sync_plain_mode_action(view)
        if view is None:
            menu.menuAction().setText("Environment")
            menu.addAction(self._no_document_action)
        else:
            self._populate_for_view(menu, view)
            menu.addSeparator()
            self._sync_document_environment_menu(view)
            menu.addMenu(self.document_environment_menu)
        menu.addAction(self.assignment_action)

    def _add_view_switcher(self, menu: QMenu, view: "UNITITextView") -> None:
        """"View As" block: the tab's mode — Plain Text (the Source editor)
        or one of the environment's rich views shown in its place (SFM:
        Standard, Preview; ADR-0017)."""

        rich_views = self._window._rich_views
        providers = rich_views.providers_for(view)
        if not providers:
            return
        menu.addSeparator()
        group = QActionGroup(self._window)
        group.setExclusive(True)
        self._owned_command_actions.append(group)  # deleted on rebuild too
        showing = rich_views.key_for(view)
        entries = [(None, PLAIN_TEXT_LABEL)] + [(provider.key, provider.label) for provider in providers]
        self.view_actions = {}
        for key, label in entries:
            action = QAction(label, self._window)
            action.setCheckable(True)
            action.setChecked(key == showing)
            action.triggered.connect(
                lambda _checked=False, key=key, view=view: rich_views.set_mode(key, view)
            )
            group.addAction(action)
            menu.addAction(action)
            self._owned_command_actions.append(action)
            self.view_actions[key] = action

    def _sync_plain_mode_action(self, view: "UNITITextView | None") -> None:
        action = self.plain_mode_action
        if action is None:
            return
        applicable = view is not None and self.descriptor_for(view.document).key != PLAIN_ENVIRONMENT_KEY
        failed = applicable and self.active_for(view.document).failed
        blocked = action.blockSignals(True)
        action.setChecked(bool(applicable and self.is_plain_mode(view)))
        action.blockSignals(blocked)
        action.setEnabled(bool(applicable and not failed))

    def _sync_document_environment_menu(self, view: "UNITITextView") -> None:
        override = self.environment_override_for(view.document)
        extension_label = descriptor_for_key(self.extension_environment_key(view.document)).label
        self.document_environment_actions[None].setText(f"By Extension ({extension_label})")
        selected = self.document_environment_actions.get(
            override if override in ENVIRONMENTS_BY_KEY else None
        )
        if selected is not None and not selected.isChecked():
            selected.setChecked(True)
        for key, action in self.document_environment_actions.items():
            if key in PROJECT_ENVIRONMENTS:
                # USFM assumes a Paratext project (T1).
                available = environment_available(key, view.document.path)
                action.setEnabled(available)
                label = descriptor_for_key(key).label
                action.setText(label if available else f"{label} (needs a Paratext project)")

    def _populate_for_view(self, menu: QMenu, view: "UNITITextView") -> None:
        descriptor = self.descriptor_for(view.document)
        active = self.active_for(view.document)
        plain = self.is_plain_mode(view)
        is_plain_environment = descriptor.key == PLAIN_ENVIRONMENT_KEY
        menu.menuAction().setText(
            descriptor.label + (" (Plain Text)" if plain and not is_plain_environment else "")
        )
        if active.failed:
            self._failed_action.setText(f"{descriptor.label} failed to load — showing Plain Text")
            menu.addAction(self._failed_action)
            menu.addSeparator()
        commands = self.commands_for(view)
        group: str | None = None
        for command in commands:
            if command.host_feature is not None:
                action = self._host_actions.get(command.host_feature)
                if action is None:
                    continue
            elif command.command_id in self._slot_actions:
                action = self._slot_actions[command.command_id]
                action.setText(command.label)
            else:
                action = QAction(command.label, self._window)
                action.triggered.connect(
                    lambda _checked=False, command_id=command.command_id: self.run_command(command_id)
                )
                action.setEnabled(view.isEnabled() and not plain)
                self._owned_command_actions.append(action)
            if group is not None and command.group != group:
                menu.addSeparator()
            group = command.group
            menu.addAction(action)
            self.command_actions[command.command_id] = action
        self._add_view_switcher(menu, view)
        if is_plain_environment:
            menu.addAction(self._no_tools_action)
            # Plain text files get an environment window too.
            self._add_window_entries(menu, view, descriptor.key)
            return
        self._add_window_entries(menu, view, descriptor.key)
        menu.addSeparator()
        menu.addAction(self.plain_mode_action)

    def _add_window_entries(self, menu: QMenu, view: "UNITITextView", environment_key: str) -> None:
        """Environment window (ADR-0017) and, for scripture, reference sync."""

        from uniti.ui.environment_window import REFERENCE_ENVIRONMENTS

        window = self._window
        menu.addSeparator()
        move = QAction("Move to Environment Window", window)
        move.setToolTip("Move this file to a window of its environment")
        in_place = window.environment_window is not None and window.environment_window[0] == environment_key
        move.setEnabled(window._service is not None and not in_place)
        move.triggered.connect(lambda _checked=False, view=view: window.move_to_environment_window(view))
        menu.addAction(move)
        self._owned_command_actions.append(move)
        self.move_to_window_action = move
        self.rename_window_action = None
        if window.environment_window is not None:
            rename = QAction("Rename Window…", window)
            rename.setToolTip(f"Rename {window.environment_window_name()}")
            rename.triggered.connect(lambda _checked=False: window.rename_environment_window())
            menu.addAction(rename)
            self._owned_command_actions.append(rename)
            self.rename_window_action = rename
        if environment_key in REFERENCE_ENVIRONMENTS:
            menu.addAction(window._chapter_view.action)
            menu.addAction(window._reference_sync.action)
            menu.addMenu(self._versification_menu(view))
        configuration = QAction("Configuration Files…", window)
        configuration.setToolTip("The configuration files of this environment: open, edit or create them")
        configuration.triggered.connect(lambda _checked=False, view=view: self.show_configuration_files(view))
        menu.addAction(configuration)
        self._owned_command_actions.append(configuration)
        self.configuration_action = configuration

    def show_configuration_files(self, view: "UNITITextView | None" = None):
        """Configuration Files… for `view`'s environment (round 2 R8)."""

        from uniti.ui.configuration_files import ConfigurationFilesDialog

        view = view if view is not None else self._window.current_view
        if view is None:
            return None
        if self.configuration_dialog is not None:
            self.configuration_dialog.close()
        self.configuration_dialog = ConfigurationFilesDialog(self._window, view)
        self.configuration_dialog.show()
        self.configuration_dialog.raise_()
        return self.configuration_dialog

    # --- versification (plan P4) ---------------------------------------------

    def versification_override_for(self, document: "Document") -> str | None:
        entry = self._entry_for(document)
        if entry is not None:
            return entry.versification
        return self._standalone_versifications.get(document)

    def versification_for(self, document: "Document"):
        """The `TextVersification` `document` uses: its own choice, else its
        project's, else English."""

        from uniti.core.environments.sfm.versification import versification_for

        return versification_for(document.path, self.versification_override_for(document))

    def set_versification(self, stem: str | None, view: "UNITITextView | None" = None) -> None:
        """Give `view`'s text its own versification (`None`: its project's,
        or English)."""

        view = view if view is not None else self._window.current_view
        if view is None:
            return
        document = view.document
        entry = self._entry_for(document)
        if entry is not None:
            entry.versification = stem
        elif stem is None:
            self._standalone_versifications.pop(document, None)
        else:
            self._standalone_versifications[document] = stem
        chosen = self.versification_for(document)
        message = f"{document.path.name} now uses {chosen.label} versification"
        self._window.statusBar().showMessage(message, 5000)
        self.refresh()

    def _versification_menu(self, view: "UNITITextView") -> QMenu:
        """An exclusive "Versification" picker, like Environment for This Document."""

        from uniti.core.environments.sfm.paratext_project import project_for_file
        from uniti.core.environments.sfm.versification import (
            DEFAULT_STEM,
            available_versifications,
            paratext_root_for,
            versification_for,
            versification_name,
            versification_path,
        )

        window = self._window
        if self.versification_menu is not None:
            # Rebuilt with the menu; deferred, as a rebuild can come from
            # one of its own actions.
            self.versification_menu.deleteLater()
        menu = QMenu("Versification", window)
        group = QActionGroup(menu)
        group.setExclusive(True)
        override = self.versification_override_for(view.document)
        default = versification_for(view.document.path, None)
        source = "Project" if project_for_file(view.document.path) is not None else "Default"
        self.versification_actions = {}
        entries = [(None, f"{source} ({default.label})")]
        root = paratext_root_for(view.document.path)
        stems = list(available_versifications(root))
        if override is not None and override not in stems:
            stems.append(override)
        entries += [
            (stem, versification_name(stem) + ("" if versification_path(stem, root) is not None else " (file missing)"))
            for stem in stems
        ]
        for stem, label in entries:
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(stem == override)
            action.triggered.connect(lambda _checked=False, stem=stem, view=view: self.set_versification(stem, view))
            group.addAction(action)
            menu.addAction(action)
            self.versification_actions[stem] = action
            if stem is None:
                menu.addSeparator()
        menu.addSeparator()
        folder = QAction("Your Versification Files…", menu)
        folder.setToolTip(
            "Copy Septuagint, Vulgate or Russian .vrs files here from a Paratext installation; "
            f"{versification_name(DEFAULT_STEM)} and Original are built in"
        )
        folder.triggered.connect(lambda _checked=False, view=view: self._show_versification_folder(view))
        menu.addAction(folder)
        self.versification_menu = menu
        return menu

    def _show_versification_folder(self, view: "UNITITextView") -> None:
        dialog = self.show_configuration_files(view)
        if dialog is not None:
            dialog.select_role("Your versification files")

    # --- running commands ---------------------------------------------------

    def run_command(self, command_id: str, argument: str | None = None) -> bool:
        """Run the active view's environment command `command_id`.

        Returns whether the command ran. `argument` answers the command's
        prompt without asking (scripting/tests); otherwise a command with a
        prompt asks for it first.
        """

        view = self._window.current_view
        if not self.command_available(command_id, view):
            return False
        assert view is not None
        command = next(
            command for command in self.commands_for(view) if command.command_id == command_id
        )
        if command.run is None:
            return False
        if command.prompt is not None and argument is None:
            text, accepted = QInputDialog.getText(
                self._window, command.prompt_title or command.label.rstrip("…"), command.prompt
            )
            if not accepted:
                return False
            argument = text
        document = view.document
        revision = document.revision
        try:
            result = command.run(
                EnvironmentContext.for_document(
                    document, caret=view.state.cursor, anchor=view.state.anchor
                ),
                argument,
            )
        except Exception as exc:
            logger.exception("environment command %r failed", command_id)
            QMessageBox.critical(
                self._window,
                command.label.rstrip("…"),
                f"{self.descriptor_for(document).label} could not run this command: {exc}",
            )
            return False
        self._apply(view, result, revision)
        if command_id == "reload_stylesheets":
            self.configuration_changed()
        return True

    # --- undefined markup (round 2 R7) ---------------------------------------

    def undefined_markup_for(self, view: "UNITITextView") -> "ShowUndefinedMarkup | None":
        """Run `view`'s environment's undefined-markup check, if it has one."""

        if not self.command_available(UNDEFINED_MARKUP_COMMAND, view):
            return None
        command = next(c for c in self.commands_for(view) if c.command_id == UNDEFINED_MARKUP_COMMAND)
        try:
            result = command.run(
                EnvironmentContext.for_document(view.document, caret=view.state.cursor, anchor=view.state.anchor),
                None,
            )
        except Exception:
            logger.exception("undefined-markup check failed")
            return None
        return result if isinstance(result, ShowUndefinedMarkup) else None

    def report_undefined_on_open(self, view: "UNITITextView") -> object | None:
        """A file was just opened: pop the report up if anything is undefined."""

        result = self.undefined_markup_for(view)
        if result is None or not result.markers:
            return None
        return self.show_undefined_markup(view, result)

    def show_undefined_markup(self, view: "UNITITextView", result: "ShowUndefinedMarkup"):
        from uniti.ui.undefined_markup_dialog import UndefinedMarkupDialog

        dialog = self.undefined_dialogs.get(view.view_id)
        if dialog is not None and dialog.view is view:
            dialog._show_result(result)
        else:
            dialog = UndefinedMarkupDialog(self._window, view, result)
            self.undefined_dialogs[view.view_id] = dialog
        dialog.show()
        dialog.raise_()
        return dialog

    def configuration_changed(self) -> None:
        """Stylesheets changed (saved, loaded or reloaded): re-render this
        window's rich views and re-run its open undefined-markup reports."""

        window = self._window
        for view in window.views:
            pane = window._rich_views.pane_for(view)
            if pane is not None:
                pane.refresh()
        for view_id, dialog in list(self.undefined_dialogs.items()):
            if window.view_for_id(view_id) is dialog.view:
                dialog.refresh()
            else:
                self.undefined_dialogs.pop(view_id, None)

    def navigate_view(self, view: "UNITITextView", offset: int) -> None:
        self._navigate(view.view_id, offset)

    def _apply(self, view: "UNITITextView", result: CommandResult, revision: int) -> None:
        document = view.document
        if isinstance(result, ReplaceDocumentText):
            if document.revision != revision or not view.isEnabled():
                return
            if self._window._refuse_read_only(view):
                return  # Format/Minify can't change a read-only file (T7)
            document.replace(0, document.total_chars(), result.text)
        elif isinstance(result, NavigateTo):
            offset = max(0, min(result.offset, document.total_chars()))
            from uniti.ui.environment_window import REFERENCE_ENVIRONMENTS

            if self.environment_key_for(document) in REFERENCE_ENVIRONMENTS:
                # Go to Chapter:Verse: land the verse a third of the way
                # down and highlight it in every view mode (R4).
                self._window._reference_sync.navigate_to(view, offset)
            else:
                view.state.move_to(offset)
                view._state_changed()
                view.setFocus()
        elif isinstance(result, ShowFindings):
            self.show_findings(view, result)
        elif isinstance(result, ShowStyleInspector):
            self.show_style_inspector(result)
        elif isinstance(result, SaveTextFile):
            self.save_text_file(view, result)
        elif isinstance(result, ShowUndefinedMarkup):
            self.show_undefined_markup(view, result)
        elif isinstance(result, ShowMessage):
            show = {
                "error": QMessageBox.critical,
                "warning": QMessageBox.warning,
            }.get(result.level, QMessageBox.information)
            show(self._window, result.title, result.text)

    def save_text_file(self, view: "UNITITextView", result: SaveTextFile, path=None) -> bool:
        """Host side of `SaveTextFile`: ask for a path (unless given), then
        write atomically (temp file + replace)."""

        from pathlib import Path

        if path is None:
            from PySide6.QtWidgets import QFileDialog

            chosen, _filter = QFileDialog.getSaveFileName(
                self._window,
                result.title,
                str(view.document.path.parent / result.suggested_name),
                result.file_filter,
            )
            if not chosen:
                return False
            path = chosen
        target = Path(path)
        temporary = target.with_name(f".{target.name}.uniti-tmp")
        try:
            temporary.write_text(result.text, encoding="utf-8", newline="\n")
            temporary.replace(target)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            QMessageBox.critical(self._window, result.title, f"Could not write {target}: {exc}")
            return False
        self._window.statusBar().showMessage(f"Saved {target.name}", 5000)
        return True

    def show_style_inspector(self, result: ShowStyleInspector):
        from uniti.ui.style_inspector import StyleInspector

        if self._style_inspector is None:
            self._style_inspector = StyleInspector(self._window)
        self._style_inspector.set_registry(result.title, result.registry, result.selected)
        self._style_inspector.show()
        self._style_inspector.raise_()
        return self._style_inspector

    def import_stylesheet(self, path=None) -> bool:
        """Host feature for "Load Stylesheet…": layer a chosen `.sty` file onto
        the active document's environment (highest precedence)."""

        view = self._window.current_view
        if view is None or self.is_plain_mode(view):
            return False
        environment = self.active_for(view.document).environment
        importer = getattr(environment, "import_stylesheet", None)
        if importer is None:
            return False
        if path is None:
            from PySide6.QtWidgets import QFileDialog

            chosen, _filter = QFileDialog.getOpenFileName(
                self._window,
                "Load Stylesheet",
                str(view.document.path.parent),
                "Stylesheets (*.sty);;All Files (*)",
            )
            if not chosen:
                return False
            path = chosen
        from pathlib import Path

        if not importer(Path(path)):
            QMessageBox.warning(self._window, "Load Stylesheet", f"Could not read {path}.")
            return False
        self._window.statusBar().showMessage(f"Loaded stylesheet {Path(path).name}", 5000)
        self.configuration_changed()
        return True

    def show_findings(self, view: "UNITITextView", result: ShowFindings) -> "EnvironmentFindingsDialog":
        from uniti.ui.environment_findings_dialog import EnvironmentFindingsDialog

        view_id = view.view_id
        if self._findings_dialog is None:
            self._findings_dialog = EnvironmentFindingsDialog(lambda _offset: None, self._window)
        dialog = self._findings_dialog
        dialog._on_navigate = lambda offset: self._navigate(view_id, offset)
        document = view.document

        def line_column(offset: int) -> tuple[int, int]:
            line = document.line_for_char(offset)
            return line + 1, offset - document.line_start(line) + 1

        dialog.set_findings(result.title, document.path.name, result.findings, line_column)
        dialog.show()
        dialog.raise_()
        return dialog

    def _navigate(self, view_id: str, offset: int) -> None:
        view = self._window.view_for_id(view_id)
        if view is None:
            return
        self._window._select_view(view)
        self._apply(view, NavigateTo(offset), view.document.revision)
