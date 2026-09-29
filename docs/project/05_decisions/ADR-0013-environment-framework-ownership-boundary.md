# ADR-0013: Isolated File-Type Environment Framework — Ownership Boundary

Date: 2026-09-29
Status: accepted (Phases E1–E2 implemented; E3–E4 planned — see the [implementation plan](../02_plans/2026-09-29-environment-framework-e1-e4-plan.md))

## Context

An external architecture spec (`@externalresources/UNITI_Claude_Code_Environment_Handover_Spec.md`) proposed layering "isolated file-type environments" (Plain/Light/Rich, modeled loosely on VS Code's language-extension isolation) on top of UNITI's canonical document, with JSON/XML/YAML as light-environment proofs and SFM/USFM as the eventual rich-environment target. The spec was written without visibility into this repository and, read literally, would have collided with things that already exist:

- `core/history.py`'s `EditTransaction`/`EditOperation`/`EditHistory` already exist, with no revision field and no public propose/commit API — internal recording structures for undo/redo, not a submission boundary. The spec's own proposed `EditTransaction` would have been a second, differently-shaped type under the same name.
- `core/syntax_profiles.py` already implements a bounded, per-logical-line, stateful tokenizer (`SyntaxProfile`) for Plain Text/Markdown/XML/JSON/YAML/SFM/CSV/TSV (BF-027/BF-041, extended by BF-071/BF-063), resolved by `profile_for_extension()` against `Settings.syntax_extension_overrides`. This is real prior art for the spec's `DecorationProvider`.
- `bootstrap/environment.py` already defines a class named `EnvironmentManager`, for Python venv/runtime bootstrap — an unrelated domain. A new file-type controller of the same name would be a same-name, different-meaning collision in the same codebase.
- `app/document_registry.py`'s `DocumentEntry`/`DocumentRegistry` and `app/recovery_manager.py`'s `RecoveryManager` are both owned by `UNITIService` ("own application services independently of editor-window lifetime," `service.py:245`) — not by `UNITIMainWindow` — because a `Document` can be open across multiple windows.
- `ui/main_window.py`'s `set_syntax_choice` already implements a real, user-facing **View > Syntax Profile** override that is explicitly *per view*, independent of the extension→profile mapping (`main_window.py:787-804`).

This decision reconciles the spec's architecture against those facts before further phases (E2 onward) touch shared, central files (`app/service.py`, `app/document_registry.py`, `ui/main_window.py`).

## Decision

1. **No new transaction type.** Environments never construct `EditTransaction`/`EditOperation` directly. A new `core/environment_edit.py` defines `EnvironmentEditFacade`, a narrow wrapper around `Document`'s existing `insert`/`delete`/`replace`/`replace_many`/`revision`/`snapshot`/`iter_text` — restricting `Document`'s surface, not reshaping it. Staleness stays the caller's responsibility, exactly as `apply_replacement_plan` already does it: compare `Document.revision` before and after.
2. **`syntax_profiles.py` is absorbed, not duplicated.** A new `core/decoration.py` defines `DecorationProvider`, shaped to match `SyntaxProfile.tokenize`'s existing signature exactly, and `SyntaxProfileDecorationAdapter`, which wraps any `PROFILES_BY_KEY` entry. `syntax_profiles.py`, `extension_profile_editor.py`, and `Settings.syntax_extension_overrides` are unmodified. This does **not** un-park any part of the [File-type profiles and syntax highlighting](../04_parked/CATALOG.md#file-type-profiles-and-syntax-highlighting) catalog entry — its remaining parked scope (true incremental parsing/language-grammar support, e.g. Tree-sitter-grade tokenization) is untouched by this framework and stays exactly as parked.
3. **Environment identity lives per-document; the existing per-view manual override is preserved unchanged.** `DocumentEntry` gains an `environment_key: str` field (Phase E2), resolved once at open time via `profile_for_extension(...).key` — the same resolver the existing system already uses. This decides an environment's *default* `DecorationProvider` and future capability set. The existing **View > Syntax Profile** per-view override (`main_window.set_syntax_choice`) is untouched: it continues to override the *rendered* profile for one view only, unaffected by which environment is active for the underlying document.
4. **The environment controller is service-owned, named to avoid the bootstrap collision.** Phase E2 adds `app/file_environment_manager.py`: `FileEnvironmentManager`, owned by `UNITIService` alongside `documents` (`DocumentRegistry`) and `recovery` (`RecoveryManager`) — not held as a per-window controller the way UI-only `main_window.py` slices (`ToggleWindowManager`, `DogfoodEvidenceController`) are. `UNITIMainWindow` references it the same defensive way it already references `recovery_manager`/`settings_store`: service-owned when a service exists, an injected standalone instance otherwise, for headless/test construction (`main_window.py:204-226`).
5. **A narrow `ResourceProfile`, explicitly not unified with existing large-file gating.** `core/resource_profile.py`'s `ResourceProfile(size_bytes)` gates only *new* environment capabilities (e.g. a future SFM semantic parse self-downgrading on a huge file). It does not unify with the ad hoc thresholds already scattered in `main_window.py` (`MAX_REFORMAT_CHARS`, the `1 << 20` navigation/index gate, `MAX_COMPARE_CHARS`) or with `resources/manager.py`'s machine-level `HostResourceProfile`. Retrofitting those is out of scope for this initiative.
6. **Core owns the document unconditionally; environments only observe and request.** An environment must never import `UNITIMainWindow`, reach a Qt widget or the piece table, or persist anything itself. Activation failure always falls back to `PlainEnvironment` (`core/environment.py`) without closing the document, losing edits, corrupting undo history, or blocking save — extending the boundary [ADR-0002](ADR-0002-document-authority-boundary.md) already established for the Qt/document split to the new environment seam specifically.

## Consequences

- `core/environment.py`, `core/environment_edit.py`, `core/decoration.py`, `core/resource_profile.py` are new, Qt-free, headless-testable modules (Phase E1, implemented; `tests/test_file_environment.py`, `tests/test_resource_profile.py`).
- Phase E2 added `environment_key` to `DocumentEntry` and `FileEnvironmentManager` to `UNITIService`; Phase E3/E4 will add `core/environments/{json,xml,yaml}_environment.py` as light-environment proofs, each pairing a `syntax_profiles.py` decoration adapter with one bounded, honest validation capability — before any SFM/USFM design work begins.
- SFM/USFM and Markdown rich-environment work (Phase E5 onward) is named but not designed by this decision — per this project's own documentation rules, that needs its own design record once E4 is proven.
- Nothing in this decision changes the status of any [Parked Capability Catalog](../04_parked/CATALOG.md) entry.

## Affected records

- [Current Architecture](../01_current/ARCHITECTURE.md)
- [ADR-0002: UNITI Document Authority and Qt Boundary](ADR-0002-document-authority-boundary.md) — this decision extends its invariant to the new environment seam.
- [Isolated File-Type Environments (E0–E4) — Implementation Plan](../02_plans/2026-09-29-environment-framework-e1-e4-plan.md)
- [Parked Capability Catalog](../04_parked/CATALOG.md) — the [File-type profiles and syntax highlighting](../04_parked/CATALOG.md#file-type-profiles-and-syntax-highlighting) entry's remaining parked scope is unaffected; noted here for clarity only, not changed.
