# UNITI Current Status

Date: 2026-09-02

## Canonical baseline

| Item | Current value |
|---|---|
| Repository branch | `main` |
| Remote baseline | `origin/main` at `e36348d` |
| Verified a18 implementation sequence | `d56da90` through `99e9597`, followed by this freeze closure |
| Local integration state | a18 is implemented and verified locally; push remains a separate approved action |
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
| Open / first paint | 16.62 ms | 6.27 / 6.27 MiB |
| Far Go to Line | 1.83 ms interaction; 5.09 s completion; 29.06 ms max heartbeat | 20.08 / 20.08 MiB |
| Typing | 17.88 ms p95; 18.96 ms max | 9.75 / 9.75 MiB |
| Wrapped/unwrapped scroll | 12.25 ms p95; 14.56 ms max | 7.36 / 7.36 MiB |
| Giant line | 14.75 ms p95; 22.59 ms max | 2.94 / 0.00 MiB |
| Sparse Find All | 45.50 ms completion; 0.31 ms max heartbeat | 1.08 / 1.08 MiB |
| Dense Find All | 810.69 ms; 1.33 ms cancellation | 4.56 / 4.56 MiB |
| Replace All planning/apply checks | 989.16 ms; 1.31 ms max heartbeat | 5.08 / 5.08 MiB |
| Save | 556.36 ms; 4.45 ms cancellation; 10.56 ms max heartbeat | 112.38 / 16.45 MiB |
| Save As | 531.00 ms; 4.52 ms cancellation; 9.10 ms max heartbeat | 110.09 / 16.38 MiB |
| Critical-to-normal recovery | 0.07 ms max transition | 0.00 / 0.00 MiB |

The sparse 1 GiB design target passed with 14.52 ms Open/first paint, 0.26 ms lazy far-marker access, and 458.37 ms sparse Find All. Peak deltas were 4.02 MiB, 0.22 MiB, and 3.59 MiB respectively. Native Cocoa quick passed all eleven daily-use scenarios; representative medians were 16.17 ms Open, 9.80 ms maximum typing interaction, 7.89 ms maximum scroll interaction, 15.21 ms maximum giant-line interaction, 92.45 ms dense search, 107.87 ms Replace All planning, 56.76 ms Save, and 53.13 ms Save As.

## Defects found during acceptance

Acceptance exposed and closed three harness defects under regression tests: a scroll integrity probe that accidentally warmed the entire random-access cache, APFS seek/write behavior that required `F_PUNCHHOLE` for marker-bearing sparse fixtures, and a sparse navigation probe that translated a known byte marker through the full Unicode map. The corrected 100 MiB scroll retained about 5 MiB rather than the artificial 132 MiB result, and the 1 GiB navigation probe now measures the intended lazy byte-source path. No product data-loss, text-integrity, stale-result, output-identity, or blocking basic-usability defect remains known.

The a18 milestone, design, and implementation plan are retained in [Implemented](../03_implemented/README.md). See [Scope](SCOPE.md), [Architecture](ARCHITECTURE.md), [Development](DEVELOPMENT.md), [Roadmap](../02_plans/ROADMAP.md), and the [Current Handover](../06_handovers/CURRENT_HANDOVER.md).
