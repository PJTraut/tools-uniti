# UNITI Current Status

Date: 2026-09-02

## Canonical baseline

| Item | Current value |
|---|---|
| Repository branch | `main` |
| Remote baseline | `origin/main` at `e36348d` |
| Verified a17 implementation checkpoint | `e36348d` — a17 implementation and documentation closure |
| Local integration state | local `main` contains the proposed a18 design after the synchronized remote a17 closure; later integration remains a separate decision |
| Latest implemented milestone | `v0.001a17` — Text Integrity Alpha |
| Active product milestone | `v0.001a18` — Large-File Alpha |
| Display/package metadata | `v0.001a17` / `0.1a17` |
| Latest immutable release tag | `v0.001a15` at `10f419e` |
| Queued milestones | `v0.001a19` through `v0.001a23` |

The `v0.001a15` tag remains immutable. a16 and a17 are implemented on `main` without new tags. No future tag or push is implied by milestone completion.

## Implemented a17 behavior

- the canonical registry contains 11 exact profiles: UTF-8 with/without BOM, Windows-1252, UTF-16 LE/BE with/without BOM, and UTF-32 LE/BE with/without BOM;
- encoding confidence, contradictory BOM evidence, and malformed preview bytes are serious input decisions, while line-ending evidence remains a separate report;
- low-confidence or malformed Open requires exact-profile confirmation before tab creation; mixed EOL uses a modeless `Keep | LF | CRLF | CR` report and never normalizes automatically;
- Reinterpret uses the exact profile flow and remains blocked on dirty documents;
- the status bar renders saved and pending format compactly, such as `UTF-8, CRLF -> UTF-16 LE BOM, LF`;
- Save and Save As stage, sync, verify, and atomically replace only after exact BOM, byte-order, decoding, EOL, logical-text, byte-length, digest, revision, and destination-identity checks pass;
- same-profile `PRESERVE` copies unresolved malformed source spans byte-for-byte; format transformation remains blocked while malformed spans remain;
- the application-owned Save As dialog keeps filename, exact encoding, and EOL controls together;
- in-place Save advances the current document only after success; different-path Save As preserves the source tab and opens the verified copy in a new active tab;
- an existing target requires normal overwrite confirmation, a distinct exact encoding-change warning when applicable, and a second confirmation when a clean target tab is already open; dirty targets are blocked;
- successful replacement reloads and reuses an existing clean target tab, and destination changes after confirmation abort instead of being silently overwritten; and
- deep self-check exposes `text-integrity`, while `uniti --smoke` runs both core and self-closing real-window probes.

## a17 completion evidence

Fresh automated and native verification reported:

```text
full pytest: 552 passed, 4 skipped in 14.40s
deep self-check: pass; text-integrity=pass; exit_code=0
offscreen combined smoke: core_ok=true; gui_ok=true; qt_platform=offscreen
native combined smoke: core_ok=true; gui_ok=true; qt_platform=cocoa
native smoke timestamp: 2026-09-02 00:33 SAST
native window: shown=true; closed=true; exit_code=0
```

The four skips are one unavailable xattr capability case and three Windows launcher cases unavailable on macOS.

Disposable non-pytest dogfood opened, searched, edited, saved, exported, SHA-256 checked, and reopened these real formats:

```text
UTF-8 no BOM / CRLF       9e1242692a1fc9417362d3c9fbaa3411aae946a4819119051e4378e99ff7a04a
UTF-8 BOM / LF            594d6b0b2facccb8b0974bb0b16f55c6f8a1fac0c766dca49c6b1a98ce2b4b39
Windows-1252 / CRLF       f0fde73ce827e3526b93a4760585b5a1302a455f6691ab51b6f86e7123c5a69c
UTF-16 LE no BOM          77b812a69a5d99d7df5e005d7a6cb8770b367e8ef4535983b9c60d44f8270eb5
UTF-16 BE BOM             d4f5fc9fe3db3da9d9de0821fcdc894d35705f1bd9279e9281e7a01539b564de
UTF-32 LE BOM             27ca19902dcdcf30ef036c2de2d774d24f553ecd631077e5a55336a62fb00a2b
Mixed EOL preserve        9b3540a97ca4ccbc0b281159acf7d8b5497407a3ab377914b7ab0f2082e22232
Malformed UTF-8 preserve  e73c25ee494df25f567d0c028ff4d45d0233435573c5dbd606059bdd7a7411a2
```

Each search returned one match before edit; Save As matched the saved source bytes; the second exact-profile reopen matched logical text. The malformed case retained byte `FF`. The first dogfood harness run compared `/var` and `/private/var` lexically; rerunning with resolved file identity passed and confirmed the intended macOS alias handling. No product defect was found, and no known data-loss, silent encoding/EOL, malformed-byte, identity, or save-state defect remains.

All a17 acceptance gates are therefore recorded as passed. The milestone, approved design, and implementation plan reside in [`03_implemented`](../03_implemented/README.md), and a18 is the active outstanding milestone.

See [Scope](SCOPE.md), [Architecture](ARCHITECTURE.md), [Development](DEVELOPMENT.md), [Roadmap](../02_plans/ROADMAP.md), and [the implemented a17 milestone](../03_implemented/milestones/2026-09-01-uniti-v0.001a17-text-integrity-alpha.md).
