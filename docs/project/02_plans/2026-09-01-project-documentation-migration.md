# UNITI Project Documentation Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the workflow-specific documentation layout with the approved, numbered UNITI project documentation and handover system while preserving every historical plan and design record.

**Architecture:** `docs/project` becomes the tool-neutral documentation root. Current truth, ordered future intent, implemented history, parked scope, durable decisions, and continuation handovers each have one explicit owner; existing records move through Git so their history remains traceable.

**Tech Stack:** Markdown, Git, POSIX shell validation, Python 3.12 for repository-relative link validation, pytest for package regression verification.

**Spec:** `docs/project/00_governance/DOCUMENTATION_SYSTEM.md`

## Global Constraints

- Number project folders with two-digit prefixes in progression order.
- Use `implemented`, never `implemented_archive` or `archive`, for completed historical work.
- Keep only approved outstanding milestones in `02_plans`.
- Treat `current` as implemented truth, never active implementation intent.
- Treat `parked` as outside current architecture or scope and require re-evaluation before promotion.
- Preserve the existing `v0.001a15` tag at `10f419e`.
- Treat `6b81185` as the verified post-tag product-code baseline supplied by the 2026-08-31 handover.
- Incorporate technical facts from the handover without adopting its chat-start commands as project policy.
- Preserve existing plan/design history through `git mv`.
- Do not change application code or version metadata during this documentation migration.

---

## File map

### Governance and navigation

- `docs/project/README.md`: entry point and reading order.
- `docs/project/00_governance/GRAMMAR.md`: canonical terms, statuses, and transitions.
- `docs/project/00_governance/DOCUMENTATION_SYSTEM.md`: approved ownership and lifecycle design.

### Current truth

- `docs/project/01_current/STATUS.md`: canonical version/code baseline, verification, limitations, and active milestone.
- `docs/project/01_current/SCOPE.md`: implemented product scope, exclusions, and invariants.
- `docs/project/01_current/ARCHITECTURE.md`: implemented components and data flows through `6b81185`.
- `docs/project/01_current/DEVELOPMENT.md`: current setup, launch, test, and verification workflow.

### Future and historical delivery

- `docs/project/02_plans/ROADMAP.md`: authoritative ordered milestone queue.
- `docs/project/02_plans/v0.001a16-startup-bootstrap.md`: approved outstanding startup/bootstrap milestone.
- `docs/project/03_implemented/README.md`: historical-record interpretation and evidence rules.
- `docs/project/03_implemented/milestones/*.md`: the 15 completed Phase 1A through `v0.001a15` plans.
- `docs/project/03_implemented/designs/*.md`: the four completed design/specification records.

### Parked scope and decisions

- `docs/project/04_parked/README.md`: promotion/re-evaluation rules.
- `docs/project/04_parked/CATALOG.md`: explicitly deferred capability catalog.
- `docs/project/05_decisions/README.md`: decision-record format and index.
- `docs/project/05_decisions/ADR-0001-host-python-runtime-policy.md`: accepted `v0.001a16` host/runtime isolation policy.
- `docs/project/05_decisions/ADR-0002-document-authority-boundary.md`: custom document engine remains authoritative over Qt.
- `docs/project/05_decisions/ADR-0003-regex-engine-authority.md`: third-party `regex` remains authoritative.

### Handovers

- `docs/project/06_handovers/CURRENT_HANDOVER.md`: concise replaceable continuation snapshot.
- `docs/project/06_handovers/history/2026-08-31-v0.001a15-post-hotfix.md`: factual snapshot synthesized from the supplied handover.

### Repository entry point

- `README.md`: links to project documentation, current state, roadmap, and current handover.

---

### Task 1: Establish navigation and project grammar

**Files:**
- Create: `docs/project/README.md`
- Create: `docs/project/00_governance/GRAMMAR.md`
- Existing: `docs/project/00_governance/DOCUMENTATION_SYSTEM.md`
- Existing: `docs/project/02_plans/2026-09-01-project-documentation-migration.md`

**Interfaces:**
- Consumes: approved terminology and directory responsibilities from `DOCUMENTATION_SYSTEM.md`.
- Produces: the canonical navigation order and vocabulary used by every later task.

- [ ] **Step 1: Create the project entry point**

Write `docs/project/README.md` with:

- the purpose of the project record;
- the numbered reading order `00_governance` through `06_handovers`;
- a direct link to every top-level owner document;
- the authority rule that current facts and roadmap intent remain separate; and
- a maintenance summary for promoting plans and refreshing handovers.

- [ ] **Step 2: Create the controlled grammar**

Write `GRAMMAR.md` with exact definitions for `current`, `milestone`, `planned`, `active`, `queued`, `implemented`, `parked`, `decision`, `handover`, and `verified`. Include these transitions:

```text
approved idea -> queued -> active -> verified -> implemented
out-of-scope idea -> parked -> re-evaluation -> decision -> planned or parked
```

State explicitly that `implemented` implies archival history and that `archive` is not a UNITI folder or status name.

- [ ] **Step 3: Validate governance terminology**

Run:

```bash
rg -n "implemented_archive|03_archive|archive/" docs/project
rg -n "current|planned|active|queued|implemented|parked|handover|verified" docs/project/00_governance/GRAMMAR.md
```

Expected: the first command finds only explanatory prohibitions in governance documents; the second finds every controlled term.

- [ ] **Step 4: Commit the governance scaffold and active migration plan**

```bash
git add docs/project/README.md docs/project/00_governance docs/project/02_plans/2026-09-01-project-documentation-migration.md
git diff --cached --check
git commit -m "docs: establish project documentation grammar"
```

### Task 2: Migrate implemented plans and designs

**Files:**
- Create: `docs/project/03_implemented/README.md`
- Move: all 15 files from `docs/superpowers/plans/` to `docs/project/03_implemented/milestones/`, except no active migration file exists in the old directory.
- Move: all four files from `docs/superpowers/specs/` to `docs/project/03_implemented/designs/`.

**Interfaces:**
- Consumes: `implemented` grammar and Git completion evidence through `10f419e`.
- Produces: complete historical plan/design inventory used by current architecture and handovers.

- [ ] **Step 1: Create historical destination directories**

```bash
mkdir -p docs/project/03_implemented/milestones docs/project/03_implemented/designs
```

- [ ] **Step 2: Move the 15 completed milestone plans with Git**

Move these exact files into `docs/project/03_implemented/milestones/` while retaining their filenames:

```text
2026-08-31-uniti-phase1a-core-foundation.md
2026-08-31-uniti-phase1b-document-model.md
2026-08-31-uniti-v0.001a3-edited-navigation.md
2026-08-31-uniti-v0.001a4-streaming-save.md
2026-08-31-uniti-v0.001a5-history-recovery.md
2026-08-31-uniti-v0.001a6-regex-core.md
2026-08-31-uniti-v0.001a7-resources-workers.md
2026-08-31-uniti-v0.001a8-qt-editor-shell.md
2026-08-31-uniti-v0.001a9-text-tools-ui.md
2026-08-31-uniti-v0.001a10-alpha-exit.md
2026-08-31-uniti-v0.001a11-data-integrity.md
2026-08-31-uniti-v0.001a12-editing-performance.md
2026-08-31-uniti-v0.001a13-search-scalability.md
2026-08-31-uniti-v0.001a14-resource-integration.md
2026-08-31-uniti-v0.001a15-desktop-hardening.md
```

- [ ] **Step 3: Move the four implemented design records with Git**

Move these exact files into `docs/project/03_implemented/designs/`:

```text
2026-08-31-uniti-phase1a-core-foundation-design.md
2026-08-31-uniti-phase1b-document-model-design.md
2026-08-31-uniti-v0.001-alpha-completion-design.md
2026-08-31-uniti-v0.001a11-a15-remediation-design.md
```

- [ ] **Step 4: Correct migrated design references mechanically**

In every migrated milestone plan, replace:

```text
docs/superpowers/specs/
```

with:

```text
docs/project/03_implemented/designs/
```

Do not alter historical task descriptions or stale task checkboxes.

- [ ] **Step 5: Document historical interpretation**

Write `03_implemented/README.md` to state:

- directory placement means implementation is completed and historical;
- Git history, release commits, tags, and verification evidence establish completion;
- old unchecked boxes are retained as authored execution history;
- implemented records are never moved back to `02_plans`; and
- superseding work receives a new plan or decision record.

- [ ] **Step 6: Validate inventory and old-path removal**

Run:

```bash
test "$(find docs/project/03_implemented/milestones -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')" = "15"
test "$(find docs/project/03_implemented/designs -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')" = "4"
test ! -d docs/superpowers/plans
test ! -d docs/superpowers/specs
! rg -n "docs/superpowers/(plans|specs)" README.md docs --glob '!**/2026-09-01-project-documentation-migration.md'
```

Expected: all commands exit successfully.

- [ ] **Step 7: Commit the implemented history migration**

```bash
git add docs/project/03_implemented docs/superpowers
git diff --cached --check
git commit -m "docs: migrate implemented milestone history"
```

### Task 3: Document the current product baseline

**Files:**
- Create: `docs/project/01_current/STATUS.md`
- Create: `docs/project/01_current/SCOPE.md`
- Create: `docs/project/01_current/ARCHITECTURE.md`
- Create: `docs/project/01_current/DEVELOPMENT.md`

**Interfaces:**
- Consumes: code at `6b81185`, `README.md`, implemented designs, Git history, and verified Mac evidence from the handover.
- Produces: authoritative present-tense documentation linked by roadmap and handovers.

- [ ] **Step 1: Write current status**

Record:

- branch `main`;
- product-code baseline `6b81185`;
- immutable `v0.001a15` tag at `10f419e`;
- package/display metadata still `0.1a15` / `v0.001a15`;
- post-tag Qt completion fix at `6b81185`;
- Mac verification `286 passed, 1 skipped`;
- xattr capability skip; and
- `v0.001a16` as the next active milestone with implementation not yet started.

- [ ] **Step 2: Write current scope**

Separate:

- included capabilities implemented through `a15` plus the hotfix;
- architecture invariants for document ownership, large-file behavior, Unicode/EOL correctness, regex authority, save/recovery, resource bounds, and UI threading; and
- excluded capabilities that link to `04_parked/CATALOG.md`.

Do not describe startup/bootstrap `a16` behavior as implemented.

- [ ] **Step 3: Write current architecture**

Document the implemented editor, search, save, recovery, and resource paths using concise text diagrams. Name the concrete modules responsible for each path and state the ownership boundaries.

- [ ] **Step 4: Write current development workflow**

Record Python 3.12+, source `.venv`, optional PySide6 UI dependency, install/launch commands, headless/full/offscreen tests, compile validation, smoke workflow, and the rule that current development setup does not yet implement the planned `a16` bootstrap lifecycle.

- [ ] **Step 5: Validate current/future separation**

Run:

```bash
rg -n "6b81185|10f419e|286 passed, 1 skipped" docs/project/01_current/STATUS.md
rg -n "not yet implemented|planned" docs/project/01_current
rg -n "QAbstractScrollArea|PieceTable|MatchStore|ResourceManager|RecoveryManager" docs/project/01_current/ARCHITECTURE.md
```

Expected: baseline evidence, explicit future qualifiers, and all core ownership components are present.

- [ ] **Step 6: Commit current-state documentation**

```bash
git add docs/project/01_current
git diff --cached --check
git commit -m "docs: record current UNITI architecture and scope"
```

### Task 4: Establish the ordered roadmap and `v0.001a16` plan

**Files:**
- Create: `docs/project/02_plans/ROADMAP.md`
- Create: `docs/project/02_plans/v0.001a16-startup-bootstrap.md`

**Interfaces:**
- Consumes: approved host-Python policy and startup design direction from the supplied handover.
- Produces: the only approved outstanding milestone and its ordered implementation workstreams.

- [ ] **Step 1: Write the authoritative roadmap**

Create a one-row ordered queue:

| Order | Milestone | Status | Goal |
|---:|---|---|---|
| 1 | `v0.001a16` | active — design finalization | Formal startup, bootstrap, initialization, diagnostics, and self-check lifecycle |

State that future milestones enter only after approval and that parked items are not hidden roadmap entries.

- [ ] **Step 2: Write the `v0.001a16` milestone plan**

Include:

- host Python 3.12+ prerequisite;
- UNITI-owned isolated environments and the prohibition on mutating host/system packages;
- source `.venv` versus application-local runtime behavior;
- dependency validation from canonical package metadata;
- explicit startup phases from `BOOT` through `READY`;
- persisted setup/startup state and environment fingerprint;
- settings/schema migration, resource calibration, stale cleanup, recovery discovery, filesystem and Qt/platform checks;
- fast and deep `uniti --self-check` modes;
- diagnostics integration and actionable failures;
- macOS-first manual acceptance with Windows/Linux designed into discovery/path logic;
- unchanged current architecture constraints; and
- a sequenced implementation outline whose first action is final design approval before code changes.

State that version metadata remains `a15` until the milestone's implementation and verification gate.

- [ ] **Step 3: Validate plan ownership**

Run:

```bash
find docs/project/02_plans -maxdepth 1 -type f -name '*.md' -print | sort
rg -n "Python 3.12|isolated|BOOT|READY|self-check|fingerprint|diagnostics" docs/project/02_plans/v0.001a16-startup-bootstrap.md
rg -n "v0.001a16|active" docs/project/02_plans/ROADMAP.md
```

Expected: only the roadmap, active migration plan, and one approved product milestone are present.

- [ ] **Step 4: Commit roadmap and milestone plan**

```bash
git add docs/project/02_plans/ROADMAP.md docs/project/02_plans/v0.001a16-startup-bootstrap.md
git diff --cached --check
git commit -m "docs: queue UNITI v0.001a16 startup milestone"
```

### Task 5: Record parked scope and durable architecture decisions

**Files:**
- Create: `docs/project/04_parked/README.md`
- Create: `docs/project/04_parked/CATALOG.md`
- Create: `docs/project/05_decisions/README.md`
- Create: `docs/project/05_decisions/ADR-0001-host-python-runtime-policy.md`
- Create: `docs/project/05_decisions/ADR-0002-document-authority-boundary.md`
- Create: `docs/project/05_decisions/ADR-0003-regex-engine-authority.md`

**Interfaces:**
- Consumes: scope exclusions, architectural invariants, and approved `a16` policy.
- Produces: re-evaluation gates and rationale linked from current scope and future plans.

- [ ] **Step 1: Write parked-work governance**

Explain that parked capabilities are outside current architecture/scope, have no delivery order, and require scope/architecture review plus an accepted decision before roadmap promotion.

- [ ] **Step 2: Create the parked catalog**

Record separate entries for:

- project/workspace concepts;
- plugins;
- LSP;
- Git UI;
- integrated terminal;
- AI/cloud features;
- hex editing;
- full programming-language syntax highlighting; and
- polished platform installers with embedded runtimes.

Each entry records why it is outside current scope and a concrete re-evaluation trigger. Do not assign versions or queue order.

- [ ] **Step 3: Create decision governance and index**

Define decision statuses `proposed`, `accepted`, `superseded`, and `rejected`. Index ADR-0001 through ADR-0003 with status and one-line outcome.

- [ ] **Step 4: Record the three accepted decisions**

ADR-0001 records host Python 3.12+ as bootstrap prerequisite and UNITI-owned dependency isolation without host/system package mutation.

ADR-0002 records the UNITI `Document`/piece-table engine as authoritative and prohibits Qt text widgets/documents from owning file content.

ADR-0003 records `regex==2026.5.9` as the authoritative search/replace engine rather than stdlib `re` or Qt regex APIs.

Each ADR includes date, status, context, decision, consequences, and links to affected current or planned records.

- [ ] **Step 5: Validate parked/planned separation and ADR completeness**

Run:

```bash
! rg -n "v0\.001a[0-9]+|Order|queued|active" docs/project/04_parked/CATALOG.md
test "$(find docs/project/05_decisions -maxdepth 1 -name 'ADR-*.md' | wc -l | tr -d ' ')" = "3"
rg -l "## Context" docs/project/05_decisions/ADR-*.md | wc -l | tr -d ' '
rg -l "## Decision" docs/project/05_decisions/ADR-*.md | wc -l | tr -d ' '
rg -l "## Consequences" docs/project/05_decisions/ADR-*.md | wc -l | tr -d ' '
```

Expected: no version/order/status leakage in the parked catalog and each ADR count is `3`.

- [ ] **Step 6: Commit parked scope and decisions**

```bash
git add docs/project/04_parked docs/project/05_decisions
git diff --cached --check
git commit -m "docs: separate parked scope from accepted decisions"
```

### Task 6: Establish factual current and historical handovers

**Files:**
- Create: `docs/project/06_handovers/CURRENT_HANDOVER.md`
- Create: `docs/project/06_handovers/history/2026-08-31-v0.001a15-post-hotfix.md`

**Interfaces:**
- Consumes: all canonical records created in Tasks 1-5 and technical facts from the supplied 2026-08-31 handover.
- Produces: a concise continuation entry point and one immutable imported history snapshot.

- [ ] **Step 1: Write the historical post-hotfix snapshot**

Record only factual project state as of 2026-08-31:

- `main`/`origin/main` at `6b81185`;
- immutable `v0.001a15` at `10f419e`;
- Qt event-loop hotfix cause and outcome;
- `286 passed, 1 skipped` Mac verification;
- xattr skip explanation;
- old `a15` artifact hashes and their pre-hotfix provenance; and
- `v0.001a16` startup/bootstrap direction as not implemented.

Do not copy the handover's chat-start instructions.

- [ ] **Step 2: Write the current handover**

Record:

- canonical branch and product-code baseline;
- current working-tree expectation;
- links to governance, status, scope, architecture, development, roadmap, active `a16` plan, parked catalog, decisions, and historical snapshot;
- latest verified product evidence;
- active milestone phase `design finalization`;
- no additional queued product milestones;
- immutable tag/artifact constraints; and
- next safe action: finalize and approve the detailed `a16` technical design before application-code changes.

Keep detailed architecture and parked entries out of the handover.

- [ ] **Step 3: Validate handover contract**

Run:

```bash
rg -n "6b81185|10f419e|286 passed, 1 skipped|v0.001a16" docs/project/06_handovers/*.md docs/project/06_handovers/history/*.md
! rg -n "Continue the UNITI|Do not redesign|Use the existing Superpowers" docs/project/06_handovers
```

Expected: evidence is present and chat-start commands are absent.

- [ ] **Step 4: Commit the handover system**

```bash
git add docs/project/06_handovers
git diff --cached --check
git commit -m "docs: establish factual UNITI handovers"
```

### Task 7: Link the system, validate it, and record this migration plan as implemented

**Files:**
- Modify: `README.md`
- Move: `docs/project/02_plans/2026-09-01-project-documentation-migration.md`
- Destination: `docs/project/03_implemented/milestones/2026-09-01-project-documentation-migration.md`

**Interfaces:**
- Consumes: the complete project documentation tree.
- Produces: a discoverable, internally consistent system with the migration itself recorded as implemented.

- [ ] **Step 1: Add project-documentation navigation to the repository README**

Add a concise `Project documentation` section linking to:

- `docs/project/README.md`;
- `01_current/STATUS.md`;
- `02_plans/ROADMAP.md`; and
- `06_handovers/CURRENT_HANDOVER.md`.

- [ ] **Step 2: Validate all repository-relative Markdown links**

Run this Python 3.12 link validator. It scans every `*.md` file under the repository, ignores HTTP(S), anchors, and fenced-code examples, resolves relative Markdown link targets from each source file, and exits nonzero with every missing target printed.

```bash
python - <<'PY'
from pathlib import Path
import re
from urllib.parse import unquote

link_pattern = re.compile(r"(?<!!)\[[^]]*\]\(([^)]+)\)")
missing: list[str] = []

for source in sorted(Path(".").rglob("*.md")):
    if ".git" in source.parts:
        continue
    in_fence = False
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in link_pattern.finditer(line):
            raw_target = match.group(1).strip().strip("<>")
            if raw_target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = unquote(raw_target.split("#", 1)[0])
            if not target:
                continue
            destination = (source.parent / target).resolve()
            if not destination.exists():
                missing.append(f"{source}:{line_number}: {raw_target}")

if missing:
    raise SystemExit("Missing Markdown targets:\n" + "\n".join(missing))
PY
```

Expected: no missing local Markdown target.

- [ ] **Step 3: Run final structural and content checks**

```bash
test "$(find docs/project/03_implemented/milestones -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')" = "15"
test "$(find docs/project/03_implemented/designs -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')" = "4"
test "$(find docs/project/05_decisions -maxdepth 1 -name 'ADR-*.md' | wc -l | tr -d ' ')" = "3"
! rg -n "docs/superpowers/(plans|specs)" README.md docs --glob '!**/2026-09-01-project-documentation-migration.md'
git diff --check
PYTHONPATH=src pytest -q tests/test_package.py
python -m compileall -q src scripts tests
```

Expected: counts are exact, no old paths remain, whitespace is clean, package tests pass, and Python compilation succeeds.

- [ ] **Step 4: Move the completed migration plan to implemented history**

```bash
git mv docs/project/02_plans/2026-09-01-project-documentation-migration.md docs/project/03_implemented/milestones/2026-09-01-project-documentation-migration.md
```

After this move, the implemented milestone count becomes `16`; `02_plans` contains only `ROADMAP.md` and the outstanding `v0.001a16` milestone plan.

- [ ] **Step 5: Re-run final checks after the lifecycle transition**

```bash
test "$(find docs/project/03_implemented/milestones -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')" = "16"
test "$(find docs/project/02_plans -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')" = "2"
git diff --check
git status --short
```

Expected: counts are `16` and `2`; only the intended README update and migration-plan move remain for the final commit.

- [ ] **Step 6: Commit the completed documentation system**

```bash
git add README.md docs/project
git diff --cached --check
git commit -m "docs: complete project documentation migration"
```

- [ ] **Step 7: Verify the committed repository state**

```bash
git status --short --branch
git log -7 --oneline --decorate
git show --check --stat --oneline HEAD
```

Expected: `main` is clean and ahead of `origin/main` only by the local documentation commits; no push or tag is performed.
