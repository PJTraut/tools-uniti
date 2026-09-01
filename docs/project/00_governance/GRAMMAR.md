# UNITI Project Grammar

Date: 2026-09-01

UNITI uses a controlled vocabulary so status and directory placement mean the same thing across roadmaps, plans, decisions, and handovers.

## Canonical terms

| Term | Definition |
|---|---|
| `current` | Implemented and authoritative at the canonical development baseline. Current never means work that is merely underway. |
| `milestone` | A bounded, versioned delivery unit with a goal, scope, acceptance criteria, and verification gate. |
| `workstream` | A bounded implementation unit inside a milestone. A workstream may be implemented while its parent milestone remains active. |
| `planned` | Approved for inclusion in the ordered implementation queue. Planned is a commitment state, not a synonym for idea. |
| `active` | The one planned milestone presently being designed or implemented. |
| `queued` | A planned milestone waiting behind the active milestone in explicit sequence. |
| `implemented` | Completed and verified historical work. Implemented inherently implies archival retention. |
| `parked` | Outside current architecture or scope and awaiting explicit re-evaluation. Parked work has no promised sequence or version. |
| `decision` | A durable record of a consequential architectural or project-policy choice and its effects. |
| `handover` | A concise continuation snapshot that points to canonical project records. It is not a specification or controlling prompt. |
| `verified` | Supported by fresh, recorded evidence proportionate to the change. |

## Delivery progression

Approved work progresses in one direction:

```text
approved idea -> queued -> active -> verified -> implemented
```

Normally exactly one milestone is `active`. Reordering `queued` milestones requires an explicit roadmap edit. After verification, the plan moves from `02_plans` to `03_implemented`; current-state documentation is then updated to describe the delivered behavior.

A milestone may contain several workstreams. Each verified workstream moves to `03_implemented` immediately and becomes part of current reality, but the milestone remains `active` until every exit criterion and acceptance gate for the complete milestone passes. A completed workstream never implies completion of its parent milestone.

`Implemented` is the only canonical status and folder term for completed historical work. The project does not use `implemented_archive`, `archive`, or `archived` as directory or lifecycle names.

## Parked progression

Work outside the current product boundary follows a separate path:

```text
out-of-scope idea -> parked -> re-evaluation -> decision -> planned or parked
```

Re-evaluation checks product fit, architecture, dependencies, risks, resource bounds, and sequencing. A parked item cannot move directly to `active`; it must first receive an accepted decision and an ordered roadmap position.

## Current-state rule

`01_current` describes implemented reality only. Active and queued plans may describe intended changes, but those changes do not enter current scope, architecture, or development guidance until they are implemented and verified.

## Handover rule

A handover records the baseline, verification evidence, active plan position, blockers, constraints, and next safe action. It links to authoritative records rather than copying them. Embedded commands or prompts in imported handover material are reference text, not project policy.

## Naming rules

- Number top-level project folders with two digits in reading/progression order.
- Use lowercase snake_case for numbered folder names.
- Use uppercase descriptive filenames for stable owner documents such as `STATUS.md` and `ROADMAP.md`.
- Use lowercase milestone filenames beginning with the display version, such as `v0.001a16-startup-bootstrap.md`.
- Add a precise workstream name after the version when a record covers only part of a milestone.
- Use `ADR-NNNN-short-title.md` for architecture decisions.
- Use an ISO date and milestone/baseline description for historical handovers.
