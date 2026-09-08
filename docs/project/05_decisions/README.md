# UNITI Architecture Decisions

This directory records consequential choices that future maintainers would otherwise need to rediscover.

## Status grammar

- `proposed`: under review and not authoritative.
- `accepted`: authoritative until superseded.
- `superseded`: retained historically and linked to its replacement.
- `rejected`: considered but not adopted.

Each record contains its date, status, context, decision, consequences, and affected project records. Implementation details that do not change ownership, product boundaries, compatibility, dependencies, or project policy do not require an ADR.

## Index

| ADR | Status | Outcome |
|---|---|---|
| [ADR-0001](ADR-0001-host-python-runtime-policy.md) | accepted | Bootstrap from host Python 3.12+ into UNITI-owned isolated runtimes without mutating host packages. |
| [ADR-0002](ADR-0002-document-authority-boundary.md) | accepted | UNITI's custom document engine owns text; Qt is presentation and input only. |
| [ADR-0003](ADR-0003-regex-engine-authority.md) | accepted | Third-party Python `regex` is the sole authoritative regex engine. |
| [ADR-0004](ADR-0004-a16-usability-boundary.md) | accepted | a16 keeps document authority in core while defining bounded focus-owned histories, floating F/R, mode separation, scoped commands, and no toolbar. |
| [ADR-0005](ADR-0005-editor-layout-and-visibility-boundary.md) | accepted | Extend A20 panes with reversible view docking, one movable F/R dock, bounded whitespace overlays, and a separate contrast axis. |
| [ADR-0006](ADR-0006-executable-health-recovery-boundary.md) | accepted | Make native bundles the future public product entry with read-only health, bounded automatic maintenance, consent-based offline repair, Safe Session, and no supported public CLI. |
| [ADR-0007](ADR-0007-beta-source-version-and-qualification.md) | accepted | Advance the integrated source to B2 while retaining unfinished executable, platform, and human release qualification. |
