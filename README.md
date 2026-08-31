# UNITI

**Unicode Intelligent Text Interchange** — a focused, cross-platform power text editor.

The project is being built from the frozen UNITI Architecture v0.1. The first implementation slice proves the byte-oriented core before any custom Qt viewport work.

## Current build scope

Phase 1A establishes:

- immutable file-backed byte access without whole-file copies;
- encoding metadata and deterministic first-pass detection;
- error-preserving lazy decoding;
- byte/local-character mapping within decoded windows;
- EOL analysis over byte streams;
- streaming byte-preserving copy/save primitives.

The piece table, global sparse offset index, custom `UNITITextView`, and regex UI follow after these contracts are proven.
