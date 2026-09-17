# Pool 1 — Task-Pool Fairness and Session-Schema Flexibility — Implementation Plan

Date: 2026-09-17
Status: implemented and verified, integrated on `main`. Both BF-040 (round-robin per-document task-pool fairness) and BF-042 (session-schema `extra` blob) landed as scoped below, with no deviations from the confirmed mechanism choices. Full suite: 1960 passed, 6 skipped, 8 failed — the 8 failures are a pre-existing local bootstrap/metadata-mismatch environment issue, confirmed to reproduce identically on unmodified `main` before this work started, unrelated to either change.
Feedback: [BF-040 \[P2\]](../../BETA_FEEDBACK.md#bf-040-p2--per-document-task-pool-fairness-and-multi-document-benchmark-foundation), [BF-042 \[P4\]](../../BETA_FEEDBACK.md#bf-042-p4--session-schema-is-being-bumped-one-field-at-a-time)
Milestone: new workstream inside the active [B3 milestone](../../02_plans/v0.001b3-find-replace-and-editor-refinement-beta.md); source of this pairing was the outstanding-work-pools index's former Pool 1 ("Escalated architecture findings, unscheduled"), closed and removed from that index on completion — remaining pools renumbered accordingly (see the [outstanding-work-pools index](../../02_plans/2026-09-16-outstanding-work-pools.md)'s "Recently closed" section)

## Scope (confirmed with the user)

- **BF-040 mechanism: round-robin per document within each priority tier.** Rejected: reserved per-document worker slots (complicates pool sizing as document count grows) and full weighted fair queuing (correct under sustained load, but more complex than the reported problem needs). Also rejected: benchmarking first and deciding the mechanism from the data — the escalation note's own reasoning already establishes fairness as a precondition for trustworthy benchmarks, so this plan implements the fix first and lets BF-030/031 (Pool 1, after renumbering) benchmark the corrected pool.
- **BF-042: build the versioned "extra fields" sub-blob now**, as infrastructure, even though the three backlog candidates named in the original finding (current-group scope state, saved recipes, step-through state) turned out, on inspection, not to need it yet (see "Why the named backlog candidates don't block this" below). This is deliberately built ahead of a concrete consumer, since the whole point is to stop the *next* one from forcing a hard schema bump.

## BF-040 — per-document task-pool fairness

**Implemented as scoped.** `PriorityWorkerPool` (`src/uniti/resources/workers.py`) now holds `{priority tier: {document_key: deque[_WorkItem]}}` instead of a flat `PriorityQueue`, with `_pop_next_locked` round-robining across documents within a tier via `OrderedDict.move_to_end`. `TaskCoordinator._dispatch` (`src/uniti/resources/tasks.py`) passes `handle.spec.document_key` through to `pool.submit`. Verification: `tests/resources/test_workers.py::test_round_robin_prevents_one_document_from_starving_another_at_same_priority` (a 5-task burst from one document no longer strictly precedes a second document's single task at the same priority — confirmed to fail on pre-fix code by stashing the fix and re-running), plus coordinator-level and deferred-background-replay regressions in `tests/resources/test_tasks.py`. No mechanism change from what's designed below.

### Confirmed root cause

- `PriorityWorkerPool` (`src/uniti/resources/workers.py`) holds one stdlib `PriorityQueue` of `_WorkItem`, ordered strictly by `(priority: int, sequence: int)` — `sequence` is a global monotonic counter, so within one `WorkPriority` tier dispatch is pure FIFO by submission order, with no concept of which document a task belongs to.
- `TaskSpec` (`src/uniti/resources/tasks.py`) already carries `document_key`, but `TaskCoordinator._dispatch` does not pass it down to `PriorityWorkerPool.submit` — the pool has no document identity to schedule on even if it wanted to.
- Concretely: if document A submits a burst of `SEARCH`-priority tasks (e.g. a large Find-in-Selection or regex analysis) and document B then submits one `SEARCH` task, B's task sits behind all of A's in strict submission order, even though both are "interactive-ish" work the user is actively waiting on in two different windows.

### Design

1. **Pass `document_key` through to the pool.** Add `document_key: str | None` to `_WorkItem` (`compare=False`, matching how `future`/`fn`/`args` are already excluded from ordering). `PriorityWorkerPool.submit` gains a `document_key: str | None = None` keyword parameter. `TaskCoordinator._dispatch` passes `handle.spec.document_key`.
2. **Replace the flat `PriorityQueue` with a two-level structure**, keyed first by priority tier, then by document:
   - `self._tiers: dict[int, dict[str | None, deque[_WorkItem]]]` — an ordered-by-first-insertion mapping of `document_key → deque[_WorkItem]` per priority level. `None` (session-level / not-document-scoped tasks, e.g. `TaskKind.SESSION`) is just another bucket.
   - `self._rotation: dict[int, deque[str | None]]` per tier — the round-robin order of document keys currently known to have pending work at that tier.
   - A worker becoming free picks the lowest-numbered non-empty tier, pops the next document key from that tier's rotation (rotating it to the back if the document still has more queued items after this pop, dropping it from rotation otherwise), and dequeues that document's oldest item.
   - This preserves cross-tier priority ordering exactly as today (`INTERACTIVE` still always preempts `SEARCH`, etc.) — round-robin only changes *tie-breaking among items already at the same tier*.
3. **Concurrency**: reuse the existing `self._condition` (already guarding `_active_count`/`_active_limit`); the blocking `self._queue.get()` in `_worker` is replaced with a condition-wait loop that wakes on `submit()` and pops from the tier/rotation structure under the same lock. `shutdown()`'s sentinel-item approach needs an equivalent (e.g. a `_shutting_down` flag checked after each wait, rather than posting one stop `_WorkItem` per thread into a now-structured queue).
4. **No behavior change for the common case**: a single document with no concurrent siblings sees identical ordering to today (its own deque is strict FIFO). The change is only observable with ≥2 documents contending at the same priority tier.

### Verification plan

- Direct regression test on `PriorityWorkerPool` (or `TaskCoordinator`, whichever level makes the intent clearest): submit N `SEARCH`-tier tasks for document A back-to-back, then 1 `SEARCH`-tier task for document B, on a pool sized smaller than N (to force real queuing) — assert B's task's start time/dispatch order does not scale with N (bounded wait, not "after all of A's"). Confirm this fails against pre-fix strict-FIFO behavior before accepting the fix, per this project's existing verification convention.
- Existing cross-tier ordering tests (`INTERACTIVE` before `SEARCH` before `INDEX`, etc.) must stay green unmodified — the tier structure itself doesn't change, only same-tier tie-breaking.
- `pause_background`/deferred-task replay in `TaskCoordinator` (background kinds re-dispatched on unpause) needs to still route through `document_key` correctly — add a regression covering unpause with multiple documents' deferred background tasks.

### Sequencing with Pool 1 (BF-030/031, renumbered after this pool closed)

This lands first. BF-030 (many concurrently open documents) and BF-031 (large cut/paste or undo/redo at scale) then benchmark the *corrected* pool — running them against today's unfair pool would measure starvation, not give a basis the user could act on, which is exactly what the original escalation flagged. Once this fairness fix is in, the round-robin regression test above becomes the seed scenario for BF-030's benchmark (same shape: many documents, one heavy, checking bounded wait for the others), scaled up toward the real ~80-file bible-project workload.

## BF-042 — session-schema extensibility

**Implemented as scoped.** `SESSION_SCHEMA` bumped 5 → 6 (`src/uniti/app/session.py`) — the deliberate last hard bump. `extra: Mapping[str, object]` added to `ViewRecord`, `DocumentRecord`, and `FindReplaceManifestRecord` (not `WindowRecord`, per the design below), validated by new `_require_extra`/`_validate_extra_value` helpers (string keys, JSON-safe values, bounded to 64 entries / depth 8) and frozen via `MappingProxyType`, matching the existing pattern in `core/recovery.py`. Verification in `tests/app/test_session.py`: schema 1/2/3/5 migration tests assert `extra` defaults to `{}`; a round-trip test carries real `extra` values through all three record types; a dedicated forward-compatibility test confirms a key this build doesn't recognize survives a load-then-resave unchanged; a rejection test covers invalid `extra` (non-string key, non-JSON value, too many entries). Also fixed stale hardcoded schema-literal assertions this bump broke in `test_session.py` and `test_setup_state.py`.

### Confirmed root cause

`SESSION_SCHEMA` (`src/uniti/app/session.py:29`, currently `5`) is one global integer version for the entire manifest. Every optional field added to any record type — `ViewRecord` gained `dock_return` (schema 2) then `font_weight` (schema 5); `DocumentRecord` gained `group_id` (schema 4); the find/replace manifest gained `placement` (schema 2) then `find_wrap`/`replace_wrap` (schema 3) — has required a full version bump plus a 3-way migration branch (`source_schema == 1` / `>= N` checks) in `_manifest_from_payload`, even when the field is small and purely additive.

### Why the named backlog candidates don't block this

The three examples named in the original finding were checked against the current codebase and none currently live in the session schema:

- **Saved recipes** exist (`src/uniti/app/find_replace_recipes.py`, `src/uniti/ui/find_replace_recipe_editor.py`) but are persisted through `settings.py`, not the session manifest.
- **Current-group replace scope** is a `ReplaceScope.CURRENT_GROUP` enum value (`src/uniti/ui/find_replace.py`) selected against the document's existing, already-schema-4 `group_id` — no new persisted state.
- **Step-through replace state** exists as in-session UI behavior (`find_replace.py`) but nothing found in `session.py` persisting a mid-step-through position across restarts.

This means BF-042 is being scoped as **preventative infrastructure**, not as an unblock for a field that's stuck today — consistent with the confirmed decision to build it now rather than wait for a concrete consumer.

### Design

1. **One last hard bump, this pass: `SESSION_SCHEMA = 6`.** This is the deliberate final "one field at a time" bump the mechanism itself needs — every schema-adding change after this one should be able to avoid a bump for purely optional/experimental state.
2. **Add an `extra: dict[str, JSON]` field** to the three record types that have shown this incremental-bump pattern:
   - `ViewRecord` (per-view/per-panel state — already grew `dock_return`, `font_weight`)
   - `DocumentRecord` (per-document state — already grew `group_id`)
   - `FindReplaceManifestRecord` (already grew `placement`, `find_wrap`/`replace_wrap`)

   `WindowRecord` is deliberately excluded — it has never needed a field added since schema 1, and there's no evidence pattern justifying speculative symmetry there.
3. **Namespaced keys, not a flat dict free-for-all.** Callers write into `extra` using a `"<feature>.<field>"` key convention (e.g. `"find_replace.step_through_position"`) so unrelated features can't collide. This is a convention enforced by review, not by code — no runtime key-format validation is planned, to keep the blob genuinely schema-free.
4. **Unknown-key round-tripping is the actual point.** `_manifest_from_payload`'s existing `_keys(payload, required, ...)` strict-key check applies to each record's *named* fields only; `extra`'s own contents are read as an opaque `dict` and written back byte-for-byte on the next save, without inspecting its keys. This means a session saved by a newer build with an `extra` key an older build doesn't understand still round-trips that key correctly through the older build (open, edit unrelated state, save) — verified directly, not assumed, per the plan's verification section below.
5. **Migration for schema < 6**: every record's `extra` defaults to `{}` when absent, exactly like `font_weight` defaulted to `400` for `source_schema < 5`.
6. **What still requires a real bump**: this mechanism only covers *optional* state that a client can safely ignore or default when absent. A genuinely required new field (something that changes the meaning of existing state if missing, not just adds an optional extra) still needs a real schema version and full migration — `extra` is scoped to avoid the routine case, not to eliminate schema bumps altogether.

### Verification plan

- Round-trip test: save a manifest with `extra = {"some.future.field": 123}` on a `ViewRecord`, reload it, assert the key/value survive unchanged.
- Forward-compatibility test: construct a schema-6 payload by hand with an `extra` key not recognized by any current feature, load it through `_manifest_from_payload`, re-save, and assert the unrecognized key is still present byte-for-byte in the re-saved payload (this is the test that would have caught a naive implementation that only round-trips *known* extra keys).
- Migration test: load a schema-5 payload (no `extra` key present on any record) and confirm each record's `extra` defaults to `{}`, matching the existing `source_schema < 5` → `font_weight` default pattern.
- Full existing session-schema migration suite must stay green (schema 1→6 chain, not just 5→6).

## Out of scope for this pass

- Any concrete feature that would *use* the `extra` blob (current-group scope, step-through persistence, or anything else) — this plan only builds the mechanism.
- BF-030/031 benchmark execution itself — tracked separately as Pool 1 (renumbered after this pool closed), sequenced to start after BF-040 lands (see "Sequencing" above).
- Any change to `WorkPriority`'s tier values or count, or to `PriorityWorkerPool`'s fixed thread-count sizing — this plan only changes same-tier ordering.
