from __future__ import annotations

from pathlib import Path
import sys

import pytest

from benchmarks.corpus import CorpusKind, CorpusSpec, generate_corpus


def test_ordinary_corpus_is_exact_and_deterministic(tmp_path: Path):
    spec = CorpusSpec(CorpusKind.ORDINARY_LINES, size_bytes=1 << 20, seed=18)

    first = generate_corpus(spec, tmp_path / "one")
    second = generate_corpus(spec, tmp_path / "two")

    assert first.path.stat().st_size == 1 << 20
    assert first.digest == second.digest
    assert first.schema == 1
    assert first.spec == spec


def test_unicode_corpus_is_valid_utf8_at_an_awkward_size(tmp_path: Path):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.MIXED_UNICODE, size_bytes=65_537, seed=18),
        tmp_path / "unicode",
    )

    text = manifest.path.read_text(encoding="utf-8")

    assert manifest.path.stat().st_size == 65_537
    assert "Привет" in text
    assert "Café" in text


def test_small_sparse_corpus_has_exact_size_and_markers(tmp_path: Path):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.SPARSE_FILE, size_bytes=8 << 20, seed=18),
        tmp_path / "sparse",
    )

    assert manifest.path.stat().st_size == 8 << 20
    assert manifest.digest is None
    assert len(manifest.marker_offsets) == 2
    with manifest.path.open("rb") as handle:
        for offset in manifest.marker_offsets:
            handle.seek(offset)
            assert handle.read(12) == b"UNITI_MARKER"


@pytest.mark.skipif(sys.platform != "darwin", reason="APFS-specific hole punching")
def test_macos_sparse_corpus_retains_holes_around_markers(tmp_path: Path):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.SPARSE_FILE, size_bytes=16 << 20),
        tmp_path / "apfs-sparse",
    )

    stat = manifest.path.stat()
    assert stat.st_blocks * 512 < stat.st_size // 2


def test_sparse_and_dense_search_corpora_have_distinct_match_density(tmp_path: Path):
    sparse = generate_corpus(
        CorpusSpec(CorpusKind.SEARCH_SPARSE, size_bytes=1 << 20, seed=18),
        tmp_path / "search-sparse",
    )
    dense = generate_corpus(
        CorpusSpec(CorpusKind.SEARCH_DENSE, size_bytes=1 << 20, seed=18),
        tmp_path / "search-dense",
    )

    sparse_count = sparse.path.read_bytes().count(b"UNITI_MATCH")
    dense_count = dense.path.read_bytes().count(b"UNITI_MATCH")

    assert 1 <= sparse_count <= 10
    assert dense_count > 1_000


def test_corpus_refuses_nonpositive_size(tmp_path: Path):
    spec = CorpusSpec(CorpusKind.GIANT_LINE, size_bytes=0)

    try:
        generate_corpus(spec, tmp_path / "invalid")
    except ValueError as error:
        assert "positive" in str(error)
    else:
        raise AssertionError("nonpositive corpus size was accepted")
