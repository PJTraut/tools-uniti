# UNITI Current Development Workflow

Date: 2026-09-08
Version: `v0.001a22` / `0.1a22`

## Requirements and policy

- Python 3.12 or newer must already be installed.
- `regex==2026.5.9` is the authoritative regex engine.
- PySide6 6.8 or newer is required for the desktop UI.
- pytest 9 or newer is selected by the development extra.
- Bootstrap may mutate only a verified UNITI-owned virtual environment.
- Ordinary UNITI startup never invokes pip, repairs dependencies, or installs into the host Python.

## Source bootstrap

From the repository root:

```bash
python3.12 scripts/bootstrap.py --dev
```

This creates or safely adopts exactly `.venv`, installs `.[ui,dev]` through `.venv/bin/python -m pip`, validates imports and `pip check`, writes ownership/setup state, and launches UNITI. Explicit alternatives:

Initial setup emits flushed first-use progress before environment creation/adoption or dependency installation. A healthy validated launch remains quiet. Treat the progress stream as stderr diagnostics; machine-readable JSON remains on stdout.

```bash
python3.12 scripts/bootstrap.py --no-launch --dev
python3.12 scripts/bootstrap.py --repair --dev
python3.12 scripts/bootstrap.py --self-check --deep --json
```

Root launchers provide the normal source-checkout path on macOS, Linux, and Windows while retaining the same bootstrap ownership and validation rules. `uniti.command` is the POSIX launcher for macOS and Linux:

```bash
./uniti.command
./uniti.command file.txt
```

Windows Command Prompt (`cmd.exe`):

```bat
uniti.bat
uniti.bat file.txt
```

PowerShell:

```powershell
.\uniti.bat
.\uniti.bat file.txt
```

The launchers preserve the caller's working directory, honor a nonempty `UNITI_PYTHON`, forward every argument exactly once, and return the bootstrap/application exit code. They invoke only `scripts/bootstrap.py`; that shim rejects unsupported interpreters and selects Python 3.12 or newer. Their default install is `.[ui]`; pass `--dev` to include the development dependency group.

Application-local mode is explicit:

```bash
python3.12 scripts/bootstrap.py --local
```

An existing unmarked application-local target is refused. UNITI never deletes or clears a managed environment automatically.

## Launch and CLI

```bash
.venv/bin/uniti
.venv/bin/uniti file.txt other.csv
.venv/bin/python -m uniti
.venv/bin/uniti --version
.venv/bin/python -m uniti --smoke
```

`--deep` and `--json` require `--self-check` on the application CLI. Bootstrap `--deep` implies self-check. `--smoke` runs the core workflow plus a real self-closing main window on the selected Qt platform. Use `--` before a filename beginning with `-`.

## Self-check

```bash
.venv/bin/uniti --self-check
.venv/bin/uniti --self-check --json
QT_QPA_PLATFORM=offscreen .venv/bin/uniti --self-check --deep --json
```

Exit codes:

| Code | Meaning |
|---:|---|
| `0` | success |
| `1` | unexpected internal failure |
| `2` | CLI usage error |
| `10` | unsupported runtime Python |
| `11` | unsafe or mismatched runtime ownership |
| `12` | dependency failure |
| `13` | path, persisted state, or schema failure |
| `14` | functional self-check failure |
| `15` | GUI/Qt/platform failure |

## Verification

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src scripts benchmarks tests
.venv/bin/python -m uniti --self-check --deep
QT_QPA_PLATFORM=offscreen .venv/bin/python -m uniti --smoke
.venv/bin/python -m uniti --smoke
git diff --check
```

### A21 cross-platform CI

`.github/workflows/a21-cross-platform.yml` defines four fail-closed lanes on fixed runner labels: `macos-py312`, `windows-py312`, `linux-py312`, and `linux-latest`. The workflow has read-only repository permission and uses immutable action revisions. It deliberately avoids dependency caching so each lane proves the public POSIX or Windows bootstrap and its UNITI-owned `.venv`.

After bootstrap, every lane invokes `python scripts/a21_ci.py` for runtime validation, complete pytest/JUnit, compile-all, deep self-check, deterministic offscreen smoke, native Cocoa/Windows/XCB smoke, and exact skip verification. The local equivalents are:

```bash
.venv/bin/python scripts/a21_ci.py runtime --family macos
.venv/bin/python scripts/a21_ci.py pytest --family macos
.venv/bin/python scripts/a21_ci.py compile --family macos
.venv/bin/python scripts/a21_ci.py self-check --family macos
.venv/bin/python scripts/a21_ci.py smoke --mode offscreen --family macos
.venv/bin/python scripts/a21_ci.py smoke --mode native --family macos
.venv/bin/python scripts/a21_ci.py verify-skips --family macos
```

On a failed hosted lane, `sanitize` parses only the fixed runtime, self-check, smoke, and JUnit inputs; applies the per-file and aggregate budgets; strips streams/properties and unapproved fields; redacts workspace/home/temp/runner roots; and prepares `ci-results/sanitized` for a seven-day failure-only upload. `ci-results/` is ignored and should be removed after local inspection. A remote run and its resulting URLs require a separately authorized push; the workflow never publishes a package or release.

The host-aware A20 user-experience suite uses the packaged policy table in `src/uniti/resources/performance_policy.toml`. Quick and routine tiers include `session_restore`; the design-target tier intentionally remains focused on sparse large-file behavior:

```bash
# 10 MiB, three isolated repetitions per daily-use scenario
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/performance_suite.py --tier quick

# inherited controlled 100 MiB a19 baseline
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/performance_suite.py \
  --tier routine --mode baseline \
  --output benchmarks/baselines/v0.001a19-mac15-8-routine.json

# sparse 1 GiB lazy-open/design probe
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/performance_suite.py \
  --tier design-target --mode baseline \
  --output benchmarks/baselines/v0.001a18-mac15-8-design-target.json

# real macOS window-system A20 UX run (no baseline is selected by default)
.venv/bin/python scripts/performance_suite.py --tier quick --native-gui
```

Use `--scenario NAME` to isolate a workflow, `--compare BASELINE.json` only for a compatible host fingerprint, and `--temp-root PATH` only for an owned location with adequate capacity. `PASS`, `WARN`, `FAIL`, `INVALID`, and `NOT RUN` are distinct; never describe an ineligible or contended controlled run as passing.

Qt-focused coverage:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/test_a20_recovery_session_acceptance.py \
  tests/test_a21_cross_platform_acceptance.py \
  tests/test_a17_text_integrity_acceptance.py \
  tests/test_a16_startup_bootstrap_acceptance.py \
  tests/test_a16_usable_alpha_acceptance.py tests/app tests/ui
```

The completed A21 gate reports 1,257 passed and six exact policy-allowed macOS skips locally, plus a passing 21-check deep self-check, offscreen/native combined smoke, and all thirteen unchanged quick performance scenarios. Hosted run `33945017353` passed the same complete gate on macOS 15, Windows 2025, Ubuntu 24.04/Python 3.12, and Ubuntu 24.04/latest stable Python at exact commit `8b24f4b`. The A20 `session_restore` scenario and all a17 byte-integrity, a18 large-file, and a19 regex-intelligence gates remain inherited. No new performance baseline was selected.

## Editor layout and display change discipline

- Keep one process-lifetime `UNITIService`, one global Find/Replace surface, and one authoritative `Document` per native source identity across every window, pane, and placement.
- Move a view transactionally during Dock/Undock. Preserve its return anchor and independent cursor/presentation state; never transfer or duplicate document/history authority.
- Splits create independent views. Assign Document selects or adds a view without closing or replacing another pane tab.
- Keep Find/Replace attached only as a full-width bottom dock following the active window, or detached as the same single modeless topmost surface.
- Paint whitespace only from committed visible slices using existing row layout geometry. Keep the 4,096-operation frame budget and reserve visible overflow aggregation.
- Keep logical terminator classification exact and bounded to at most two direct document characters; do not infer CRLF from normalized display text.
- Preserve appearance and contrast as independent global settings and update complete application/editor theme tokens together.
- Follow the [LTR text layout contract](../../../docs/ltr-text-layout.md): keep document positions in code points, convert Qt/IME positions with bounded UTF-16 maps, and use one shaped geometry authority for paint, selection, matches, hit testing, caret, tabs, wrap and preedit.
- Keep the platform monospace face primary and bundled Noto fonts application-local. Preserve locale-ordered Han fallback, exact manifest/notice bytes, and explicit capability failure when an asset is missing.
- Keep public shaped windows and grapheme context within 8,192 code points; add at most 512 wrap rows per advance; retain no more than 512 shaped/provider entries and the existing 2,048-row block bound. Cold unknown geometry remains pending instead of approximate.
- Test exact code-point inspection separately from user grapheme navigation/deletion. Synthetic IME events are regressions, not native Windows/macOS/Linux qualification.
- Never create, reserve, or fill real LOWDISK state. Inject capacity and write/fsync failures.

## Recovery/session change discipline

- Keep one `UNITIService` as the sole settings, session, recovery, document-registry, window-manager, and global Find/Replace authority. A window close is not service shutdown: the last editor window remains visible and usable after its tabs close. Explicit Quit closes the retained window and ends the service.
- Capture immutable GUI state quickly, then serialize, compress, hash, write, sync, discover, replay, and clean through worker tasks. Tests record thread identities for the session-restore path.
- Publish immutable packs before their manifest and the manifest before the current pointer. Retain the previous complete generation until its successor is durably current.
- Persist editor history to the first of 50 transactions or 32 MiB decoded, Find and Replace to at most 50 states each within 4 MiB decoded, and the physical saved-history union within 256 MiB.
- Preserve current state when pruning, keep compatible closed history for seven days subject to the aggregate cap, and never treat recovery journals as disposable history.
- Use SHA-256 over exact saved bytes as history authority. Metadata may avoid unnecessary hashing but may never override a detected content mismatch.
- Keep the 64 MiB recovery compaction threshold and 512 MiB free-space reserve centralized. Exercise low-space behavior only with injected capacity/write/fsync failures; never fill or reserve the real filesystem for a test.
- Quit must resolve Save/Discard/Cancel once per unique modified document. A second crash or failed publication must leave the last complete session/recovery evidence discoverable.

## Regex-intelligence change discipline

- Keep `regex==2026.5.9` as the sole semantic authority; lexer output may describe spans but must be reconciled before claiming group identity.
- Limit interactive pattern/replacement analysis to 65,536 code points and keep engine compilation off the GUI thread after the 150 ms quiet interval.
- Publish analysis and capture results only after every expression, document, revision, result-store, and match-index seal remains current.
- Resolve capture reports from immutable snapshots within the 65,536-character read, five-preview, 80-character-preview, and 1 MiB payload bounds.
- Store and navigate zero-width matches by result index; apply each result exactly once and retain atomic one-step Replace All undo.
- Close snapshots, match stores, replacement plans, documents, task records, and superseded pending requests in tests and measured scenarios.

## Large-file change discipline

- Long index, EOL, navigation, search, replacement-plan, and save work consumes a snapshot and publishes only for its captured revision/identity.
- Use `TaskCoordinator` for admission, priorities, progress, cancellation, and background-pause semantics; do not create competing worker ownership.
- Use `ReadIntent.STREAMING` for sequential scans that must not populate reusable decoded-span cache.
- Account disposable caches by bytes and explicit priority; never put authoritative text, Undo/Redo, recovery, or unsaved state in cache.
- Keep viewport and wrap details bounded. Do not restore one Python or Qt object per line, visual row, or match.
- Add a deterministic scenario and integrity fact when changing a measured daily-use path. Threshold values change only in the packaged policy table after real-use evidence.

## Text-integrity change discipline

- Add or select formats only through `core.text_format.EncodingProfile` and `OutputFormat`; do not recreate codec/BOM/EOL grammar in a menu or dialog.
- Keep encoding assessment serious and independent from line-ending reporting.
- Test all save-path changes against exact bytes, logical reopen text, document state, destination identity, and temporary cleanup.
- Use `Document.save()` only for the current resolved path and `Document.export_copy()` for another path.
- Preserve malformed bytes only under same-profile `PRESERVE`; never introduce replacement-byte conversion silently.
- Keep Qt and tab coordination in `src/uniti/ui`; core/regex/resource modules remain Qt-free.

## Lifecycle files

- Runtime ownership: `<managed-environment>/.uniti-runtime.json`
- Setup/startup state: `AppPaths.setup_state_file`
- Settings: `AppPaths.settings_file`
- Custom theme definitions and active profile: bounded atomic `theme-profiles.json` beside settings
- Startup log: `AppPaths.startup_log_file`, rotated at 5 MiB with ten rotations
- Cache process-session records: `AppPaths.session_dir/<session-id>/session.json`
- Durable generation sessions/history packs: `AppPaths.durable_session_dir`
- Recovery journals: `AppPaths.recovery_dir`; never removed by cache-session stale cleanup
- Single-instance lease: `AppPaths.instance_lock_file`; local endpoint name derives from the resolved application-data identity

Malformed supported state/settings are preserved as timestamped `.invalid` siblings. Future schemas are left untouched and produce exit code 13.

## Versioning and documentation

Display versions use `v0.001aN` in `VERSION` and `uniti.__display_version__`; package versions use `0.1aN` in `pyproject.toml` and `uniti.__version__`. Tags are immutable historical records. `v0.001a20` and `v0.001a21` are implemented without new tags; A22 Dogfood / Performance Alpha is active.

Approved outstanding work belongs in the ordered [Roadmap](../02_plans/ROADMAP.md). Verified plans move to [Implemented](../03_implemented/README.md); current documents and the [Current Handover](../06_handovers/CURRENT_HANDOVER.md) are updated in the same closure.
