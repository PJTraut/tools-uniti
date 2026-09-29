from __future__ import annotations

import pytest

from uniti.core.resource_profile import ENVIRONMENT_LARGE_FILE_BYTES, ResourceProfile


def test_small_file_is_small_tier_and_allows_full_parse():
    profile = ResourceProfile(size_bytes=1024)
    assert profile.tier() == "small"
    assert profile.allow_full_parse is True


def test_file_over_threshold_is_large_tier_and_denies_full_parse():
    profile = ResourceProfile(size_bytes=ENVIRONMENT_LARGE_FILE_BYTES + 1)
    assert profile.tier() == "large"
    assert profile.allow_full_parse is False


def test_file_at_exact_threshold_is_still_small():
    profile = ResourceProfile(size_bytes=ENVIRONMENT_LARGE_FILE_BYTES)
    assert profile.tier() == "small"


def test_negative_size_is_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        ResourceProfile(size_bytes=-1)
