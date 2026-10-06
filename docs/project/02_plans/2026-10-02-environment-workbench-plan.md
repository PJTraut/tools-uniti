# Environment Workbench — Implementation Record

Date: 2026-10-02
Status: **Implemented.**
Decision: [ADR-0014](../05_decisions/ADR-0014-environment-workbench-and-extension-assignment.md)
Origin: request to give each file-type environment its own functions, tools, features and menus, to assign extensions to environments (e.g. `.USFM` + `.sfm`), and to let every environment fall back to plain text within itself. Builds on the [E1–E4](2026-09-29-environment-framework-e1-e4-plan.md), [E5](2026-09-29-environment-framework-e5-sfm-foundation-plan.md) and [E6](2026-09-30-environment-framework-e6-usfm-layer-plan.md) records.

## What shipped

Core (Qt-free):

- `core/environment_commands.py` — `EnvironmentCommand`, result types, `environment_commands()`, shared `validate_command()` / `reformat_commands()`.
- `core/environments/catalog.py` — `ENVIRONMENTS` (one per syntax profile), extension resolution and assignment (`environment_key_for_extension`, `extension_assignments`, `overrides_for_assignments`).
- `core/environments/markdown_environment.py` (new), `delimited_environment.py` (new CSV/TSV), and `commands()` on JSON (Format, Minify, Check Brackets), XML (Format, Minify, Check Well-Formedness), YAML (Check Indentation), SFM (Check Markers), USFM (Go to Chapter:Verse…, Validate USFM), Markdown (Markdown Preview, Format).
- `app/file_environment_manager.py` — `with_builtin_environments()`, `active_for()`/`release()` with the `failed` fallback flag; `app/document_registry.py` — `set_environment_key()`.

UI:

- `ui/environment_controller.py` — the per-environment menu, Plain Text Mode, command running/result handling.
- `ui/environment_findings_dialog.py`, `ui/environment_assignment_editor.py` (replaces `ui/extension_profile_editor.py`, removed).
- `ui/main_window.py` — Format/Minify removed from Format; Markdown Preview removed from View; "Text-Type Profiles…" → "File Type Environments…"; view profiles come from the environment.

## Follow-up, same day (ADR-0014 decisions 8–9)

- Per-document environment pin: `DocumentEntry.environment_override`, `DocumentRegistry.set_environment_override()`, session capture (`session_runtime.py`) and pre-view restore (`session_controller._restore_entry_environment`), and the **Environment for This Document** picker.
- Plain Text Mode moved onto the view (`UNITITextView.environment_plain_mode`), saved and restored in `ViewRecord.extra`.
- `CommandCategory.ENVIRONMENT` and six `environment.*` command slots with default shortcuts (`ui/shortcut_policy.py`). Markdown Preview became the `environment.preview` slot. USFM's go-to command id is now `go_to`.
- Tests: 4 more in `tests/ui/test_environment_ui.py`, 1 in `tests/app/test_service.py` (a pin survives extension reassignment), 1 session round trip in `tests/app/test_session_orchestration.py`; `tests/ui/test_hotkeys.py` and `tests/ui/test_shortcut_policy.py` updated for the new category/commands.

## Verification

- New tests: `tests/test_environment_catalog.py` (16), `tests/test_environment_commands.py` (24), `tests/ui/test_environment_ui.py` (12), one in `tests/app/test_service.py`; updated `tests/ui/test_main_window_contract.py` (format actions, assignment editor, size cap) and `tests/ui/test_hotkeys.py` (menu bar order). `tests/ui/test_extension_profile_editor.py` removed with the editor it covered.
- Full suite after the follow-up: 2,332 passed, 6 platform skips.
- Offscreen render check of the USFM menu (with shortcuts and the per-document picker), menu bar ("… View  USFM  Tools …") and the File Type Environments dialog.
