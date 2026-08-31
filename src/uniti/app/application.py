"""UNITI desktop application launcher with lazy optional Qt imports."""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ModuleNotFoundError:
        print(
            "UNITI desktop UI requires PySide6. Install with: pip install 'uniti-editor[ui]'",
            file=sys.stderr,
        )
        return 2

    from uniti.app.paths import AppPaths
    from uniti.app.recovery_manager import RecoveryManager
    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    arguments = list(sys.argv if argv is None else argv)
    program = arguments[0] if arguments else "uniti"
    app = QApplication.instance() or QApplication([program])
    paths = AppPaths.current()
    paths.ensure()
    recovery_manager = RecoveryManager(paths.recovery_dir)
    settings_store = SettingsStore(paths.settings_file)
    window = UNITIMainWindow(
        recovery_manager=recovery_manager,
        settings_store=settings_store,
    )
    window.recover_startup_sessions()
    for raw_path in arguments[1:]:
        path = Path(raw_path)
        try:
            window.open_path(path)
        except Exception as exc:
            QMessageBox.critical(window, "Open Failed", f"{path}\n\n{exc}")
    window.show()
    return int(app.exec())
