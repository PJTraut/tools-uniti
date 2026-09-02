"""Deterministic bounded corpus generation for UX performance scenarios."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from uniti.app.sparse import deallocate_file_range


class CorpusKind(StrEnum):
    ORDINARY_LINES = "ordinary-lines"
    NEWLINE_DENSE = "newline-dense"
    GIANT_LINE = "giant-line"
    MIXED_UNICODE = "mixed-unicode"
    SEARCH_SPARSE = "search-sparse"
    SEARCH_DENSE = "search-dense"
    MIXED_EOL = "mixed-eol"
    MALFORMED_UTF8 = "malformed-utf8"
    SPARSE_FILE = "sparse-file"


@dataclass(frozen=True, slots=True)
class CorpusSpec:
    kind: CorpusKind
    size_bytes: int
    seed: int = 18


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    schema: int
    spec: CorpusSpec
    path: Path
    digest: str | None
    marker_offsets: tuple[int, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "kind": self.spec.kind.value,
            "size_bytes": self.spec.size_bytes,
            "seed": self.spec.seed,
            "path": str(self.path),
            "digest": self.digest,
            "marker_offsets": list(self.marker_offsets),
        }

    @classmethod
    def from_dict(cls, payload: object) -> "CorpusManifest":
        if not isinstance(payload, dict):
            raise ValueError("corpus manifest must be an object")
        required = {
            "schema",
            "kind",
            "size_bytes",
            "seed",
            "path",
            "digest",
            "marker_offsets",
        }
        if set(payload) != required or payload["schema"] != 1:
            raise ValueError("invalid corpus manifest")
        digest = payload["digest"]
        offsets = payload["marker_offsets"]
        if digest is not None and not isinstance(digest, str):
            raise ValueError("invalid corpus digest")
        if not isinstance(offsets, list):
            raise ValueError("invalid corpus marker offsets")
        return cls(
            schema=1,
            spec=CorpusSpec(
                CorpusKind(str(payload["kind"])),
                int(payload["size_bytes"]),
                int(payload["seed"]),
            ),
            path=Path(str(payload["path"])),
            digest=digest,
            marker_offsets=tuple(int(offset) for offset in offsets),
        )


_PATTERNS = {
    CorpusKind.ORDINARY_LINES: b"00000000 alpha beta gamma delta\n",
    CorpusKind.NEWLINE_DENSE: b"x\n",
    CorpusKind.GIANT_LINE: b"abcdefghijklmnopqrstuvwxyz012345",
    CorpusKind.MIXED_UNICODE: "Café Привет Καλημέρα 東京 🙂\n".encode("utf-8"),
    CorpusKind.SEARCH_SPARSE: b"ordinary text without the token on this line\n",
    # One match per 256 bytes is dense enough to force bounded result/plan
    # spooling at routine scale without manufacturing millions of records that
    # have no additional user-experience value.
    CorpusKind.SEARCH_DENSE: b"UNITI_MATCH " + (b"x" * 243) + b"\n",
    CorpusKind.MIXED_EOL: b"alpha\nbeta\r\ngamma\r",
    CorpusKind.MALFORMED_UTF8: b"valid\ninvalid:\xff\xfe\n",
}


def _write_pattern(path: Path, pattern: bytes, size_bytes: int) -> str:
    digest = hashlib.sha256()
    block_size = 1 << 20
    full_block = (pattern * (block_size // len(pattern) + 1))[:block_size]
    remaining = size_bytes
    with path.open("wb") as handle:
        while remaining:
            chunk = full_block[: min(remaining, len(full_block))]
            handle.write(chunk)
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def _write_unicode(path: Path, size_bytes: int) -> str:
    pattern = _PATTERNS[CorpusKind.MIXED_UNICODE]
    repetitions, remainder = divmod(size_bytes, len(pattern))
    digest = hashlib.sha256()
    block_repetitions = max(1, (1 << 20) // len(pattern))
    with path.open("wb") as handle:
        while repetitions:
            count = min(repetitions, block_repetitions)
            chunk = pattern * count
            handle.write(chunk)
            digest.update(chunk)
            repetitions -= count
        if remainder:
            tail = b"x" * remainder
            handle.write(tail)
            digest.update(tail)
    return digest.hexdigest()


def _write_sparse(path: Path, size_bytes: int) -> tuple[int, ...]:
    marker = b"UNITI_MARKER"
    if size_bytes < len(marker) * 2 + 8192:
        raise ValueError("sparse corpus size is too small for both markers")
    offsets = (4096, size_bytes - 4096 - len(marker))
    with path.open("wb") as handle:
        handle.truncate(size_bytes)
        for offset in offsets:
            handle.seek(offset)
            handle.write(marker)
        handle.flush()
        if size_bytes > 16_384:
            deallocate_file_range(
                handle.fileno(),
                8192,
                size_bytes - 16_384,
            )
    return offsets


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _write_sparse_search(path: Path, size_bytes: int) -> str:
    marker = b"UNITI_MATCH"
    _write_pattern(path, _PATTERNS[CorpusKind.SEARCH_SPARSE], size_bytes)
    offsets = sorted({size_bytes // 4, size_bytes // 2, size_bytes * 3 // 4})
    with path.open("r+b") as handle:
        for offset in offsets:
            if offset + len(marker) <= size_bytes:
                handle.seek(offset)
                handle.write(marker)
    return _digest_file(path)


def generate_corpus(spec: CorpusSpec, root: Path) -> CorpusManifest:
    """Generate one exact-size corpus without retaining it in memory."""

    if spec.size_bytes <= 0:
        raise ValueError("corpus size must be positive")
    root.mkdir(parents=True, exist_ok=False)
    path = root / f"{spec.kind.value}.txt"
    if spec.kind is CorpusKind.SPARSE_FILE:
        marker_offsets = _write_sparse(path, spec.size_bytes)
        digest = None
    elif spec.kind is CorpusKind.SEARCH_SPARSE:
        marker_offsets = ()
        digest = _write_sparse_search(path, spec.size_bytes)
    elif spec.kind is CorpusKind.MIXED_UNICODE:
        marker_offsets = ()
        digest = _write_unicode(path, spec.size_bytes)
    else:
        marker_offsets = ()
        digest = _write_pattern(path, _PATTERNS[spec.kind], spec.size_bytes)
    if path.stat().st_size != spec.size_bytes:
        raise RuntimeError("generated corpus size mismatch")
    return CorpusManifest(1, spec, path, digest, marker_offsets)
