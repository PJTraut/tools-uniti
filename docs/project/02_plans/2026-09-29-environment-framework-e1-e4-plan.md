# Isolated File-Type Environments (E0–E4) — Implementation Plan

Date: 2026-09-29
Status: **Phases E1–E3 implemented.** E4 planned, not yet implemented. See "Scope" below for what E0–E4 covers and what it deliberately does not.
Origin: an external architecture spec (`@externalresources/UNITI_Claude_Code_Environment_Handover_Spec.md`) proposing isolated file-type environments layered on the canonical document, reviewed and reconciled against this codebase before any code was written. See [ADR-0013](../05_decisions/ADR-0013-environment-framework-ownership-boundary.md) for the reconciliation decisions this plan implements.
Milestone: a new engineering-track initiative alongside the active [B4 milestone](v0.001b4-compare-character-inspector-and-per-view-settings-beta.md) — not a version-qualification item itself, and not blocking B4. Referenced from [ROADMAP.md](ROADMAP.md)'s "Current work" section.

## Why this plan exists

The spec is architecturally sound (Core owns the document; environments only observe and request; Plain fallback always available; lazy activation; degrade rather than refuse on large files) but was written without seeing this repository. [ADR-0013](../05_decisions/ADR-0013-environment-framework-ownership-boundary.md) records the reconciliation against what already exists (`Document`/`EditHistory`, `syntax_profiles.py`, `bootstrap.environment.EnvironmentManager`, `DocumentRegistry`/`RecoveryManager` service ownership, the existing per-view syntax override). This document is the phase-by-phase task breakdown that ADR implies, kept separate so the ADR stays a decision record and this stays a working plan.

Goal of E0–E4: prove the environment seam is real — lazy activation, Plain fallback on any failure, headless testability with zero PySide6 dependency, zero regression to existing behavior — using formats (JSON/XML/YAML) that already have partial support via `syntax_profiles.py`, before betting the materially harder SFM/STY rich-environment work on an unproven abstraction.

## Scope

**In scope (this document):** Phases E0–E4 — bridge documentation, the core environment skeleton, service/window wiring, and JSON/XML/YAML as light-environment proofs.

**Explicitly out of scope (future, separate design docs):** generic SFM detection and lossless tokenizer, `.STY` raw/normalized parsing and layering, USFM validation/navigation, a generic rich-view/source-map framework, SFM Standard/Formatted editable views, and a Markdown rich environment. Per this project's documentation rules, SFM/STY design deserves its own record once E4 has proven the framework — it is not designed here, only named as Phase E5+ for sequencing.

## Progress

**Phase E1 implemented 2026-09-29**, matching the design below:

- `core/environment.py`: `EnvironmentContext` (constructed via `EnvironmentContext.for_document(document)`, holding an `EnvironmentEditFacade` and a `ResourceProfile`), the `Environment` protocol (`activate`/`deactivate`/`decoration_provider`), and `PlainEnvironment` — the always-available fallback, wrapping `syntax_profiles.PLAIN_TEXT` via `SyntaxProfileDecorationAdapter` rather than returning no provider at all, so every environment (including Plain) has a uniform, non-optional decoration contract.
- `core/environment_edit.py`: `EnvironmentEditFacade`, delegating straight to `Document.insert`/`delete`/`replace`/`replace_many`/`revision`/`snapshot`/`iter_text` — no new transaction shape.
- `core/decoration.py`: `DecorationProvider` protocol and `SyntaxProfileDecorationAdapter`, wrapping (not reimplementing) `syntax_profiles.SyntaxProfile`.
- `core/resource_profile.py`: `ResourceProfile(size_bytes)` with `tier() -> "small"|"large"` (threshold `ENVIRONMENT_LARGE_FILE_BYTES = 1 << 20`, matching the order of magnitude of the existing ad hoc gate in `main_window.py` without sharing state with it) and an `allow_full_parse` convenience property.
- Tests: `tests/test_file_environment.py` (10 cases — named to avoid a pytest module-name collision with the pre-existing `tests/bootstrap/test_environment.py`, which covers the unrelated bootstrap/runtime `EnvironmentManager`) and `tests/test_resource_profile.py` (4 cases). Both are pure Python, zero PySide6 — constructing a real `Document.open(tmp_path)` and exercising the facade/context directly.
- Full suite green: 2,184 passed, 6 platform skips, no regressions.

**Phase E2 implemented 2026-09-29**, matching the design below:

- `app/document_registry.py`: `DocumentEntry` gains `environment_key: str = "plain_text"`. `adopt()` and `replace_document()` gain an optional `environment_key` parameter; when omitted, a new private `_default_environment_key(path)` resolves it via `profile_for_extension(path.suffix).key` (no overrides — this registry stays self-sufficient, no new `Settings` dependency). `replace_document()` only recomputes the key when the path actually changes, leaving an explicitly-set key untouched across a same-path replacement (e.g. a reload).
- `app/file_environment_manager.py` (new): `FileEnvironmentManager` — `resolve_key(suffix, overrides)` (thin wrapper over `profile_for_extension`, so both the new per-document default and the pre-existing per-view manual override share one resolution path) and `activate_for(document, environment_key)`, which is deliberately **stateless** — see the module's own docstring for why a persistent per-document binding table (mirroring `RecoveryManager.attach`/`detach`) is deferred rather than built speculatively.
- `app/service.py`: `UNITIService` gains `self.file_environments = file_environments or FileEnvironmentManager()`, alongside `self.documents`/`self.recovery` — matching decision 4 in ADR-0013 exactly.
- `ui/main_window.py`: constructor gains `file_environment_manager: FileEnvironmentManager | None = None`, resolved the same defensive way `recovery_manager`/`settings_store` already are. `_add_document()`'s `documents.adopt(...)` call and the Save-As/reload `documents.replace_document(...)` call both now pass `environment_key=self._file_environment_manager.resolve_key(path.suffix, self._settings.syntax_extension_overrides)` — the existing `view.set_syntax_profile(profile_for_extension(...))` line is untouched.
- Tests: `tests/test_file_environment_manager.py` (6 cases), 3 new cases in `tests/app/test_document_registry.py` (default resolution, explicit override, recompute-only-on-path-change), and one service+window integration test in `tests/app/test_service.py` (`test_opening_a_document_through_a_service_owned_window_sets_environment_key`, following the existing `service.new_window()` + `open_path()` pattern used by neighboring tests in that file).
- Full suite green: 2,195 passed, 6 platform skips, no regressions.

**Phase E3 implemented 2026-09-29**, matching the design below, with one naming decision made concrete: this codebase's "Diagnostics" (`app/diagnostics.py`, `DiagnosticsDialog`) already means app-health/startup telemetry, unrelated to a per-document validation finding, so the new result type is `EnvironmentFinding` (`core/environment_findings.py`), not `Diagnostic` — a fourth same-name-different-meaning collision avoided in this initiative (after `FileEnvironmentManager` and the `EditTransaction` reconciliation).

- `core/environment_findings.py` (new): `FindingSeverity` (`INFO`/`WARNING`/`ERROR`) and `EnvironmentFinding(start, end, severity, message, code)`.
- `core/environment.py`: the `Environment` protocol gains `validate(context) -> tuple[EnvironmentFinding, ...]`; `PlainEnvironment.validate` returns `()`.
- `core/environments/__init__.py`, `core/environments/json_environment.py` (new): `JsonEnvironment` adapts `syntax_profiles.JSON` via `SyntaxProfileDecorationAdapter` for `decoration_provider`, and its `validate()` adds real bracket-match validation (`{}`/`[]` nesting, ignoring brackets inside string literals, handling escaped quotes) — streamed chunk-by-chunk via `context.edits.iter_text()`, so it never materializes the whole document and needed no resource-profile gate.
- `app/service.py`: when `file_environments` isn't injected, `UNITIService.__init__` registers `JsonEnvironment` into the freshly-constructed `FileEnvironmentManager` (an injected manager is left exactly as the caller built it — this composition-root wiring is deliberately not inside `FileEnvironmentManager` itself, keeping it format-agnostic and independently testable).
- Tests: `tests/test_json_environment.py` (7 cases), pure Python.

## Task breakdown

**E4 — XML and YAML light environments.** Same pattern as E3, proving the framework generalizes before committing to the materially larger SFM/USFM design.

**E5+ (named only, no design here):** generic SFM detection + lossless tokenizer + `.STY` raw/normalized parsing; USFM validation/navigation; generic rich-view/source-map framework; SFM Standard View; SFM Formatted View; Markdown rich environment. Each gets its own plan/design record once E4 lands.

## Regression risks and how this plan avoids them

- **View > Syntax Profile manual override** (`main_window.py:787-804`, `text_view.py:490-511`): preserved unchanged — see ADR-0013 decision 3. `DocumentEntry.environment_key` decides only the environment's *default*; the per-view override path is untouched code.
- **Compare pane's two independent `set_syntax_choice` calls** (`compare_pane.py:754,817,832`): these operate on two separate `Document`s (left/right of a diff), so per-document environment identity does not affect them.
- **`RecoveryManager` keys bindings by `id(document)`**, not path or environment key: `environment_key` stays a fully separate field; E2–E4 do not touch `recovery_manager.py`.
- **No project-level settings tier exists today** (`Settings` is flat/global via `SettingsStore`): this plan does not introduce or imply one. If SFM `.STY` layering (E5+) eventually needs project-level stylesheets, that is an explicit, separately-designed addition to the settings system.
- **Find/Replace has no format-aware restriction hook today** (`ui/find_replace.py`'s `ReplaceScope` is document/selection-scoped, not format-scoped): E1–E4 do not add one, to avoid silently implying that gap is closed.

## Verification

- After each phase: the phase's own new pure-Python test module(s), then the full suite (`pytest tests/`) must stay green — no existing test changes expected except where `DocumentEntry` gains a field (any test constructing it positionally rather than by keyword needs updating).
- Manual smoke once E2 lands: open a `.json`, `.xml`, `.yaml`, and a `.txt` file; confirm status bar/behavior unchanged from the current build; confirm View > Syntax Profile manual override still works per view; confirm a deliberately-broken environment (temporarily raising inside `activate()`) falls back to Plain without closing the document or blocking save.
