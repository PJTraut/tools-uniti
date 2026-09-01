# ADR-0001: Host Python and UNITI-Owned Runtime Policy

Date: 2026-08-31
Status: accepted

## Context

UNITI needs a reliable startup/bootstrap lifecycle without placing application dependencies into global, system, user-site, or unrelated virtual environments. Bundling Python and maintaining signed platform installers would add a separate packaging architecture before the local runtime lifecycle is mature.

## Decision

Require a discoverable host Python 3.12 or newer as the bootstrap prerequisite. Use that interpreter to create or maintain a UNITI-owned isolated environment: repository `.venv` for a source checkout and an OS-appropriate application-local runtime for a normal local installation.

UNITI may install or repair its declared dependencies only inside that controlled environment. It must not install or replace host Python, invoke an OS package manager to do so, or mutate host/system/user-site packages. A missing or outdated host Python produces an actionable failure.

Python bundling and polished `.app`/`.exe` installers remain separate parked decisions.

## Consequences

- Source development and local installation share one environment-ownership policy.
- Bootstrap needs reliable interpreter discovery, ownership proof, environment fingerprinting, and relaunch behavior across macOS, Windows, and Linux.
- Dependency installation may require network access during setup, while normal editor startup remains local and account-free.
- Users must install a supported host Python before UNITI setup.
- Embedded-runtime packaging is neither blocked forever nor silently included in the current startup milestone.

## Affected records

- [Implemented v0.001a16 Startup/Bootstrap](../03_implemented/milestones/2026-09-01-uniti-v0.001a16-startup-bootstrap.md)
- [Current Development Workflow](../01_current/DEVELOPMENT.md)
- [Parked Capability Catalog](../04_parked/CATALOG.md)
