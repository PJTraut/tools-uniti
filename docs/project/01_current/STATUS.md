# UNITI Current Status

Date: 2026-09-02

## Canonical baseline

| Item | Current value |
|---|---|
| Repository branch | `main` |
| Remote baseline | `origin/main` at `84407e3` |
| Verified a18 implementation sequence | `d56da90` through `40009ad`, followed by the recorded freeze evidence |
| Local integration state | local and remote `main` contain the verified a18 closure; the proposed a19 design follows locally and awaits written review |
| Latest implemented milestone | `v0.001a18` — Large-File Alpha |
| Active product milestone | `v0.001a19` — Regex Intelligence Alpha |
| Display/package metadata | `v0.001a18` / `0.1a18` |
| Latest immutable release tag | `v0.001a15` at `10f419e` |
| Queued milestones | `v0.001a20` through `v0.001a23` |

The `v0.001a15` tag remains immutable. a16, a17, and a18 are implemented on `main` without new tags. No tag or push is implied by this milestone closure.

## Implemented a18 behavior

- one packaged schema-1 policy owns performance tiers, absolute UX gates, host eligibility, cache limits, pressure behavior, and compatible-baseline comparison;
- read-only host profiling records CPU generation, architecture, physical/logical cores, RAM, load, RSS, filesystem, free disk, sparse support, Python, Qt, and display evidence where available;
- `ResourceManager` owns adaptive Normal/Busy/Constrained/Critical state, byte-accounted priority cache, active worker limits, task admission, background pause, cancellation, progress, and diagnostics;
- immutable document snapshots and revision/identity checks prevent index, EOL, navigation, search, replacement-plan, or output work from publishing stale results;
- Open constructs a usable tab after bounded encoding/EOL inspection, then completes EOL analysis in the background;
- decoded boundary storage, document line summaries/details, wrapped rows, match results, and replacement plans are compact, bounded, or spillable;
- far Go to Line and document-end navigation, Find All, Replace All planning, Save, and Save As run progressively without owning the GUI thread;
- Replace All applies only an admitted current-revision plan and remains one atomic Undo operation;
- progressive Save/Save As locks only the source tab, reports stage/verification progress, preserves targets on cancellation/failure, and commits a verified identity-sealed temporary;
- status text exposes resource state and task progress; constrained/critical notices are nonmodal and coalesced; `Pause Background Work` does not pause foreground Save;
- macOS sparse corpus creation uses supported hole deallocation so marker-bearing 1 GiB fixtures remain physically sparse; and
- the isolated suite covers Open, nearby/far navigation, typing, wrapped/unwrapped scroll, giant lines, sparse/dense search, cancellation, replacement admission/refusal, Save/Save As, pressure transitions, recovery, memory, integrity, and cleanup.

## Freeze verification

Fresh automated verification on the freeze tree reported:

```text
full pytest: 674 passed, 4 skipped
compileall: pass for src, scripts, benchmarks, and tests
deep self-check: pass; text-integrity=pass; large-file=pass; exit_code=0
offscreen combined smoke: core/gui pass; qt_platform=offscreen
native combined smoke: core/gui pass; qt_platform=cocoa; shown/closed=true
git diff --check: pass
```

The four skips are one unavailable xattr capability case and three Windows launcher cases unavailable on macOS. The deep large-file check created and removed a marker-bearing source beyond 1 GiB, proved lazy Open/early read with incomplete indexes, verified streaming cache bypass, and observed cooperative task cancellation.

## Selected performance evidence

The selected schema-1 results are [controlled 100 MiB routine](../../../benchmarks/baselines/v0.001a18-mac15-8-routine.json), [sparse 1 GiB design target](../../../benchmarks/baselines/v0.001a18-mac15-8-design-target.json), and [native Cocoa 10 MiB quick](../../../benchmarks/baselines/v0.001a18-mac15-8-native-quick.json).

Host fingerprint: Apple M3 Max, arm64, 16 physical/logical cores, 48 GiB RAM, Darwin 25.6.0, Python 3.12.4, Qt/PySide6 6.11.2. The native run recorded 2× scale and 120 Hz. Every required scenario evaluated `PASS`; no selected result is `WARN`, `FAIL`, `INVALID`, or `NOT RUN`.

Controlled 100 MiB routine medians:

| Scenario | Responsiveness/completion | Peak / retained RSS delta |
|---|---:|---:|
| Open / first paint | 16.04 ms | 4.34 / 4.34 MiB |
| Far Go to Line | 4.70 ms interaction; 4.88 s completion; 23.51 ms max heartbeat | 18.06 / 18.06 MiB |
| Typing | 15.34 ms p95; 16.40 ms max | 5.30 / 5.30 MiB |
| Wrapped/unwrapped scroll | 13.74 ms p95; 14.48 ms max | 8.38 / 8.38 MiB |
| Giant line | 11.87 ms p95; 21.29 ms max | 2.36 / 0.00 MiB |
| Sparse Find All | 45.42 ms completion; 0.27 ms max heartbeat | 1.41 / 1.41 MiB |
| Dense Find All | 828.17 ms; 1.30 ms cancellation | 5.58 / 5.58 MiB |
| Replace All planning/apply checks | 989.61 ms; 1.36 ms max heartbeat | 5.97 / 5.97 MiB |
| Save | 512.02 ms; 4.43 ms cancellation; 10.57 ms max heartbeat | 115.61 / 18.31 MiB |
| Save As | 502.29 ms; 4.39 ms cancellation; 8.29 ms max heartbeat | 106.11 / 8.91 MiB |
| Critical-to-normal recovery | 0.08 ms max transition | 0.00 / 0.00 MiB |

The sparse 1 GiB design target passed with 17.89 ms Open/first paint, 0.25 ms lazy far-marker access, and 452.51 ms sparse Find All. Peak deltas were 4.09 MiB, 0.22 MiB, and 3.80 MiB respectively. Native Cocoa quick passed all eleven daily-use scenarios; representative medians were 16.63 ms Open, 9.56 ms maximum typing interaction, 7.22 ms maximum scroll interaction, 13.54 ms maximum giant-line interaction, 81.22 ms dense search, 99.36 ms Replace All planning, 47.62 ms Save, and 46.27 ms Save As.

## Defects found during acceptance

Acceptance exposed and closed three harness defects under regression tests: a scroll integrity probe that accidentally warmed the entire random-access cache, APFS seek/write behavior that required `F_PUNCHHOLE` for marker-bearing sparse fixtures, and a sparse navigation probe that translated a known byte marker through the full Unicode map. The corrected 100 MiB scroll retained about 8 MiB rather than the artificial 132 MiB result, and the 1 GiB navigation probe now measures the intended lazy byte-source path. No product data-loss, text-integrity, stale-result, output-identity, or blocking basic-usability defect remains known.

The a18 milestone, design, and implementation plan are retained in [Implemented](../03_implemented/README.md). See [Scope](SCOPE.md), [Architecture](ARCHITECTURE.md), [Development](DEVELOPMENT.md), [Roadmap](../02_plans/ROADMAP.md), and the [Current Handover](../06_handovers/CURRENT_HANDOVER.md).

## Post-freeze baseline finding

Fresh verification while designing a19 exposed an intermittent status-delivery ordering defect in `tests/ui/test_progressive_save.py::test_progressive_save_as_locks_only_source_and_cancel_preserves_target`. Concurrent Qt and worker emitters can deliver an older `SAVE queued/no-progress` snapshot after newer `SAVE Writing` progress, causing the status bar to clear the active operation. An instrumented diagnostic run reproduced the inversion after eight passing iterations. The save task, cancellation, and target-preservation paths remain unaffected; the defect is in presentation of task progress. The proposed a19 asynchronous-task design requires the GUI to refresh from latest coordinator state rather than trust cross-thread snapshot delivery order.
