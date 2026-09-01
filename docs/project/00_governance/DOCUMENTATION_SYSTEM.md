# UNITI Project Documentation and Handover System

Date: 2026-09-01
Status: implemented and authoritative

## Goal

Maintain one durable, tool-neutral project record that makes five things immediately clear:

1. what UNITI currently is;
2. what will be implemented next, and in what order;
3. what has already been implemented;
4. what is intentionally outside the current architecture or scope; and
5. what another development session needs in order to continue safely.

The documentation must distinguish implemented facts from planned intent. It must not rely on a chat transcript, agent prompt, or handover bundle as its only source of truth.

## Design principles

- **Current truth is separate from future intent.** Current architecture and scope describe implemented behavior only.
- **Plans form an ordered commitment queue.** A planned item has been approved for sequential implementation; it is not merely an idea.
- **Implemented implies historical archive.** The project does not use `implemented_archive` or a separate `archive` status.
- **Parked is outside current scope.** Parked capabilities require explicit re-evaluation before entering the plan queue.
- **Status is structural.** A record's directory and declared status carry more authority than stale checklist marks inside a historical plan.
- **History remains traceable.** Completed plans and their design records are retained rather than deleted or rewritten as current documentation.
- **Handovers are navigational snapshots.** They summarize state and link to canonical records instead of duplicating the whole project.
- **Folder numbering communicates progression.** Two-digit prefixes keep the documentation in its intended reading and lifecycle order.

## Directory structure

```text
docs/project/
├── README.md
├── 00_governance/
│   ├── GRAMMAR.md
│   └── DOCUMENTATION_SYSTEM.md
├── 01_current/
│   ├── STATUS.md
│   ├── SCOPE.md
│   ├── ARCHITECTURE.md
│   └── DEVELOPMENT.md
├── 02_plans/
│   ├── ROADMAP.md
│   └── [approved active and queued milestone/workstream plans]
├── 03_implemented/
│   ├── README.md
│   ├── milestones/
│   │   └── [implemented milestone and workstream plans]
│   └── designs/
│       └── [implemented design and specification records]
├── 04_parked/
│   ├── README.md
│   └── CATALOG.md
├── 05_decisions/
│   ├── README.md
│   └── [architecture decision records]
└── 06_handovers/
    ├── CURRENT_HANDOVER.md
    └── history/
        └── [immutable dated handover snapshots]
```

The top-level progression is:

```text
governance -> current state -> planned work -> implemented history
```

Parked capabilities, decisions, and handovers follow as supporting records.

## Directory responsibilities

### `00_governance`

Defines how project documentation is named, interpreted, promoted, moved, and maintained.

- `GRAMMAR.md` defines the controlled project vocabulary and status transitions.
- `DOCUMENTATION_SYSTEM.md` defines document ownership, directory responsibilities, authority, and lifecycle.

Changes to the documentation system are made here before restructuring records.

### `01_current`

Describes the implemented product as it exists at the canonical development baseline. It never describes an active plan as though that plan were already delivered.

- `STATUS.md`: version, baseline commit, tags, verification evidence, known limitations, and active milestone pointer.
- `SCOPE.md`: included product behavior, explicit boundaries, and current architectural invariants.
- `ARCHITECTURE.md`: implemented components, ownership boundaries, data flows, and runtime relationships.
- `DEVELOPMENT.md`: supported setup, launch, test, verification, and contribution workflow.

These files are updated when implementation changes current reality. They are not milestone diaries.

### `02_plans`

Contains every approved, outstanding milestone and no completed or merely speculative work.

- `ROADMAP.md` is the authoritative ordered queue.
- Exactly one milestone may normally be `active`.
- Remaining approved milestones are `queued` in explicit sequence.
- Each milestone has a governing scope record and one or more executable workstream plans.
- Reordering the queue is an explicit roadmap change; filenames do not need renumbering.

### `03_implemented`

Contains completed historical records. The name `implemented` inherently includes archival meaning.

- `milestones/` contains completed milestone and workstream implementation plans.
- `designs/` contains the design/specification records that governed implemented work.
- Old unchecked checklist items may remain as authored history. Directory placement and implementation evidence determine status.
- Records may receive mechanical link corrections or an implementation-status header during migration, but their historical intent is preserved.

A plan enters `03_implemented` only after its own acceptance criteria and proportionate verification have passed. Completing a workstream does not complete its parent milestone. A tag is useful evidence but is not required when Git history and verification establish completion.

### `04_parked`

Contains capabilities deliberately outside the current architecture or scope.

`CATALOG.md` records, at minimum:

- capability name;
- reason it is parked;
- boundary or assumption that excludes it;
- dependencies or risks already known;
- trigger for re-evaluation; and
- last review date.

Parked records are not ordered delivery promises. Promotion from parked to planned requires a scope and architecture review, an explicit decision, and placement in `ROADMAP.md`.

### `05_decisions`

Contains durable architecture decision records for choices that affect product boundaries, system ownership, compatibility, dependencies, or development policy.

Each decision records context, decision, consequences, date, and status. Superseded decisions remain present and point to their replacement.

Not every implementation detail needs a decision record. Decisions exist where future maintainers would otherwise need to rediscover why a consequential choice was made.

### `06_handovers`

Maintains continuity between development sessions without becoming a competing specification.

- `CURRENT_HANDOVER.md` is the single replaceable continuation snapshot.
- `history/` contains snapshots captured at milestone completion or another meaningful project boundary. Git history preserves the original; a factual misclassification may be renamed and receive an explicit correction note.
- Handovers state facts and next context; they do not contain agent commands that override the canonical project workflow.
- Handovers link to current architecture, scope, roadmap, the active plan, decisions, and verification instead of copying them wholesale.

## Project grammar

The controlled vocabulary is:

| Term | Meaning |
|---|---|
| `current` | Implemented and authoritative at the canonical development baseline. |
| `milestone` | A bounded, versioned delivery unit with acceptance criteria. |
| `workstream` | A bounded implementation unit within a milestone. |
| `planned` | Approved for inclusion in the ordered implementation queue. |
| `active` | The one planned milestone presently being implemented. |
| `queued` | A planned milestone waiting behind the active milestone. |
| `implemented` | Completed and verified historical work. This inherently means archived. |
| `parked` | Outside current architecture or scope and awaiting explicit re-evaluation. |
| `decision` | A durable record of a consequential architectural or project-policy choice. |
| `handover` | A concise continuation snapshot that points to canonical documentation. |
| `verified` | Supported by fresh, recorded evidence appropriate to the change. |

The folder/status name `archive` is not used. `Implemented` is the canonical term for completed historical work.

## Lifecycle and transitions

### Planned work

```text
approved idea -> queued -> active -> verified -> implemented
```

1. An idea becomes `planned` only after its design and scope are approved.
2. It is added to `ROADMAP.md` at an explicit sequence position and receives a plan file.
3. The first executable plan is marked `active`; all later plans remain `queued`.
4. Work proceeds against the active plan.
5. Completion requires acceptance criteria and fresh verification evidence.
6. A verified workstream plan moves to `03_implemented/milestones/`; the parent milestone stays active until its complete acceptance gate passes.
7. A fully verified milestone moves to `03_implemented`, leaves the outstanding roadmap, and activates the next queued milestone.
8. Current status, scope, architecture, development guidance, roadmap, and handover are updated wherever implementation changed them.

If approved work is deliberately removed from the queue before implementation, it moves to `04_parked/` with the decision and rationale recorded. It does not move to `03_implemented`.

### Parked work

```text
out-of-scope idea -> parked -> re-evaluation -> decision -> planned or remains parked
```

Parked work never flows directly into active implementation. Re-evaluation must confirm that it fits the intended product, architecture, dependencies, and resource envelope.

### Current documentation

Current documents change only when implemented evidence changes the authoritative baseline. During active development, planned deltas remain in the active plan until they are verified and integrated into current truth.

## Authority and conflict resolution

When records disagree, use this order:

1. canonical repository code, tests, version metadata, and Git state;
2. accepted architecture decisions;
3. `01_current` documentation;
4. `02_plans/ROADMAP.md` and active/queued plans for future intent;
5. `06_handovers/CURRENT_HANDOVER.md`;
6. implemented and historical handover records.

A lower-authority document never silently overrides a higher-authority source. Instead, correct the stale document and record a decision when the correction changes policy.

## Handover contract

`CURRENT_HANDOVER.md` contains only the information needed to resume safely:

1. canonical branch, commit, version, and working-tree state;
2. latest verification evidence and environmental exceptions;
3. links to current status, scope, architecture, and development workflow;
4. active milestone and exact active-plan position;
5. queued milestone summary;
6. unresolved decisions, blockers, or external validation gates;
7. the next safe action; and
8. warnings about immutable tags, artifacts, or other historical constraints.

The handover must not duplicate full architecture descriptions or parked-feature catalogs. It must not instruct a future session to treat its prose as more authoritative than the repository.

A historical handover snapshot is created when:

- a milestone becomes implemented;
- the canonical baseline changes in a way another environment must receive;
- a major external verification gate completes; or
- responsibility is transferred with meaningful unfinished work.

## Initial migration record

The first implementation of this system will:

1. create the full numbered directory structure and navigation README;
2. create the grammar, current-state, roadmap, parked, decision, and handover records;
3. move all completed Phase 1A through `v0.001a15` plans into `03_implemented/milestones/`;
4. move their completed design/specification records into `03_implemented/designs/`;
5. synthesize current architecture, scope, development, and status from the repository and the supplied handover;
6. create an ordered roadmap and distinguish versioned milestones from their implementation workstreams;
7. retain completed startup/bootstrap/initialization work as an implemented a16 foundation while the complete a16 product gate remains active;
8. create a parked catalog for explicitly deferred capabilities such as project/workspace systems, plugins, LSP, Git UI, terminal, AI/cloud features, hex editing, full syntax highlighting, and polished platform installers;
9. create a factual current handover and a dated post-`v0.001a15`/hotfix historical snapshot; and
10. update repository documentation links and remove the superseded `docs/superpowers` hierarchy once all records are accounted for.

The supplied 2026-08-31 handover is reference material. Its technical facts and approved `v0.001a16` direction are incorporated, but its chat-start commands are not adopted as project policy.

## Validation

The migration is complete when:

- every existing plan and design record is accounted for exactly once;
- only outstanding approved milestones remain in `02_plans`;
- every completed milestone or workstream plan is under `03_implemented`;
- current documents contain no unimplemented `v0.001a16` behavior stated as fact;
- parked features are not presented as queued commitments;
- all repository-relative links resolve;
- the roadmap, status, version metadata, and Git baseline agree;
- the current handover points to canonical records and contains no controlling prompts; and
- `git diff --check` and documentation consistency checks pass.
