from __future__ import annotations

from pathlib import Path
import sys

import pytest

import benchmarks.corpus as corpus
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


def test_exact_format_fixtures_are_bounded_and_have_known_digests(tmp_path: Path):
    fixtures = corpus.generate_format_fixtures(tmp_path / "formats")

    assert tuple(item.name for item in fixtures) == (
        "utf8",
        "utf8_bom",
        "utf16_le_bom",
        "utf16_be_bom",
        "mixed_eol",
        "mixed_unicode",
        "malformed_utf8",
    )
    assert {item.name: item.digest for item in fixtures} == {
        "utf8": "3392c2257db366ca3c938a70ff57220c2c21fc6fe91ed6004faf909a29873087",
        "utf8_bom": "9ed9e48a7d82df5aef9999b65d827ffd46d5c77fdf12930fdc9e6be5ee8c58a0",
        "utf16_le_bom": "7670ef62adef66ec940aaade8af6fa7be9b8887ef0abd474b155cddbec2d21f9",
        "utf16_be_bom": "2a2c14953eaa7a74794345060fb4ae0f1b285bfc79602dfa231ee342255f3ada",
        "mixed_eol": "c487d23b88fa7291e67805566cdcfb2bfe10aec8755f494562421dd66eb97ad6",
        "mixed_unicode": "2f054e7756c66e9df1ec0180056eb63efb37d15cd7577ee63b8455cda63f9832",
        "malformed_utf8": "78339ddb284899d4dd503b4848aa46c2036f677d9dcb829421751327835f5d5a",
    }
    assert sum(item.size_bytes for item in fixtures) == 161
    assert all(item.size_bytes == item.path.stat().st_size for item in fixtures)
