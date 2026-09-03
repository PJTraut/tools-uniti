# UNITI Current Status

Date: 2026-09-03

## Canonical baseline

| Item | Current value |
|---|---|
| Repository branch | `main` |
| Remote baseline | `origin/main` at `84407e3` |
| Verified a19 implementation sequence | `45d7a20` through `06d644d`, followed by the a19 freeze closure |
| Local integration state | local `main` contains the verified a19 closure; `origin/main` remains pre-a19 until a separate push is authorized |
| Latest implemented milestone | `v0.001a19` — Regex Intelligence Alpha |
| Active product milestone | `v0.001a20` — Recovery & Session Alpha |
| Display/package metadata | `v0.001a19` / `0.1a19` |
| Latest immutable release tag | `v0.001a15` at `10f419e` |
| Queued milestones | `v0.001a21` through `v0.001a23` |

The `v0.001a15` tag remains immutable. a16 through a19 are implemented on `main` without new tags. No tag or push is part of this closure.

## Implemented a19 behavior

- cross-thread task notifications are wake-ups over monotonically generated authoritative snapshots, so stale queued/no-progress delivery cannot replace newer task progress;
- Qt-free immutable analysis provides pattern/replacement tokens, delimiter pairs, inline switches, group identities, and structured diagnostics, while `regex==2026.5.9` remains the sole semantic authority;
- successful pattern metadata is reconciled all-or-nothing with engine group facts, and replacement references share the matching numbered/named group identity;
- a 150 ms debounce sends live compilation through one serialized latest-request task slot without blocking the GUI thread;
- expression generations immediately invalidate stale analysis, search, replacement, and capture work; document-backed publication also checks document identity/revision, result-store identity, and match index;
- every engine-emitted zero-width result is retained in stable order, navigated by result index, painted with an insertion marker, wrapped deterministically, and applied exactly once by Replace or atomic one-Undo Replace All;
- capture reports resolve current and next matches asynchronously through a model, read no more than 65,536 characters per match, retain at most five previews of at most 80 characters per group, and cap one report payload at 1 MiB;
- incomplete bounded resolution produces one explicit unavailable record rather than a partial group list, and the bounded path does not measure the whole document;
- superseded/canceled work and closed UI release snapshots, stores, plans, task records, and pending request resources; and
- deep self-check and the isolated quick/routine suite include regex analysis, cancellation, reports, zero-width planning, responsiveness, memory, integrity, and cleanup facts.

## Freeze verification

Fresh verification on the freeze tree reported:

```text
focused a19 + inherited integrity/resource suites: 273 passed
full pytest: 779 passed, 4 skipped
compileall: pass for src, scripts, benchmarks, and tests
deep self-check: pass; runtime ownership marker valid; regex-intelligence=pass;
  text-integrity=pass; large-file=pass; exit_code=0
offscreen combined smoke: core/gui pass; qt_platform=offscreen
native combined smoke: core/gui pass; qt_platform=cocoa; shown/closed=true
native visual/interaction checklist: pass
controlled quick: 12/12 PASS
controlled 100 MiB routine: 12/12 PASS
native Cocoa 10 MiB quick: 12/12 PASS
```

The four skips are one unavailable xattr capability case and three Windows `cmd.exe` launcher cases unavailable on macOS. Two inherited UI acceptance tests were corrected to wait for the newly asynchronous debounced pattern compilation before invoking actions directly; the product correctly keeps those actions disabled while analysis is pending.

## Selected performance evidence

Selected schema-1 a19 results are the [controlled 100 MiB routine](../../../benchmarks/baselines/v0.001a19-mac15-8-routine.json) and [native Cocoa 10 MiB quick](../../../benchmarks/baselines/v0.001a19-mac15-8-native-quick.json) runs. The [a18 sparse 1 GiB design target](../../../benchmarks/baselines/v0.001a18-mac15-8-design-target.json) remains inherited evidence because a19 does not change that tier.

Host fingerprint: Apple M3 Max, arm64, 16 physical/logical cores, 48 GiB RAM, Darwin 25.6.0, Python 3.12.4, and Qt/PySide6 6.11.2. The native run recorded 2× scale and 120 Hz. Both a19 files record Git commit `06d644d`; their host metadata records `0.1a18` because the controlled evidence was deliberately captured before the post-acceptance version advancement. Every required evaluation is `PASS`, with no `WARN`, `FAIL`, `INVALID`, or `NOT RUN` result.

Controlled 100 MiB routine medians:

| Scenario | Responsiveness/completion | Peak / retained RSS delta |
|---|---:|---:|
| Open / first paint | 14.34 ms | 4.53 / 4.53 MiB |
| Far Go to Line | 5.50 ms interaction; 5.09 s completion; 21.03 ms max heartbeat | 20.88 / 20.88 MiB |
| Typing | 16.81 ms p95; 16.84 ms max | 6.80 / 6.80 MiB |
| Wrapped/unwrapped scroll | 12.84 ms p95; 13.04 ms max | 6.73 / 6.56 MiB |
| Giant line | 14.90 ms p95; 23.07 ms max | 2.73 / 0.00 MiB |
| Sparse Find All | 45.78 ms completion; 0.31 ms max heartbeat | 1.12 / 1.12 MiB |
| Dense Find All | 958.52 ms; 1.31 ms cancellation | 5.86 / 5.86 MiB |
| Replace All planning/apply checks | 1.12 s; 1.47 ms max heartbeat | 5.69 / 5.69 MiB |
| Regex intelligence | 3.48 ms analysis; 49.11 ms report; 21.45 ms zero-width plan; 6.33 ms max heartbeat; 1.30 ms cancellation | 25.36 / 25.36 MiB |
| Save | 533.69 ms; 4.26 ms cancellation; 10.53 ms max heartbeat | 117.78 / 21.56 MiB |
| Save As | 541.78 ms; 4.17 ms cancellation; 9.62 ms max heartbeat | 116.47 / 24.14 MiB |
| Critical-to-normal recovery | 0.07 ms max transition | 0.00 / 0.00 MiB |

Native Cocoa quick passed the same twelve scenarios. Representative medians were 15.09 ms Open, 9.74 ms maximum typing interaction, 8.28 ms maximum scroll interaction, 14.76 ms maximum giant-line interaction, 96.00 ms dense search, 114.12 ms replacement, 49.84 ms Save, and 47.35 ms Save As. Regex intelligence measured 3.27 ms analysis, 48.27 ms capture reporting, 21.60 ms zero-width planning, 6.42 ms maximum heartbeat, 1.30 ms cancellation, and 21.53 MiB retained RSS.

The native Cocoa visual/interaction checklist was also performed against real widgets. Direct keyboard input retained Find-field focus; eight distinct group colors and the same replacement-reference colors were visible; paired group identities and `(?i-s:...)` scoped-switch analysis were confirmed; the invalid-pattern wave underline and exact status/accessibility text rendered; current/next capture rows were readable; Next/Previous navigation and one-result wrapping were exact; cancellation showed `Cancelling…` then `cancelled`; and insertion markers rendered at an internal line end and the document end. Temporary native captures were visually inspected at original resolution and are not selected benchmark artifacts.

## Defects found and closed during a19

- the post-a18 task-status delivery race was replaced with generation-monotonic authoritative snapshots and deterministic reordered-delivery regression coverage;
- task cancellation before worker start and the worker-future publication race were sealed so canceled/superseded tasks cannot publish ghost work;
- mixed repeated empty captures now retain their exact occurrence semantics, and capture callbacks cannot publish after Qt shutdown;
- bounded capture resolution no longer calls whole-document `total_chars()` on its normal path; and
- the regex performance harness releases documents, tasks, snapshots, stores, plans, and closures before retained-RSS sampling.

No known regex-correctness, infinite-navigation, GUI-freeze, stale-publication, partial-replacement, data-loss, text-integrity, or runtime-ownership blocker remains. Editor whitespace visualization and a keyboard command for inspecting selected or preceding Unicode characters are recorded as future editor-display work, not a19 behavior.

The a19 milestone, design, and implementation plan are retained in [Implemented](../03_implemented/README.md). See [Scope](SCOPE.md), [Architecture](ARCHITECTURE.md), [Development](DEVELOPMENT.md), [Roadmap](../02_plans/ROADMAP.md), and the [Current Handover](../06_handovers/CURRENT_HANDOVER.md).
