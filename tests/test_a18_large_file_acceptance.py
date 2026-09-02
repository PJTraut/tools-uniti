import ast
import json
import sys
import tomllib
from pathlib import Path

import uniti

from uniti.app.paths import AppPaths
from uniti.app.self_check import CheckStatus, SelfCheckRunner
from uniti.resources.policy import load_performance_policy


def test_a18_release_metadata_is_canonical():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert Path("VERSION").read_text(encoding="utf-8").strip() == "v0.001a18"
    assert uniti.__version__ == "0.1a18"
    assert uniti.__display_version__ == "v0.001a18"
    assert project["project"]["version"] == "0.1a18"


def _has_qt_imports(*roots: Path) -> bool:
    for root in roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(
                    alias.name.startswith("PySide6") for alias in node.names
                ):
                    return True
                if isinstance(node, ast.ImportFrom) and (
                    node.module or ""
                ).startswith("PySide6"):
                    return True
    return False


def test_a18_policy_and_architecture_contract():
    policy = load_performance_policy()

    assert policy.tiers["routine"].size_mib == 100
    assert policy.tiers["design_target"].sparse_size_gib == 1
    assert policy.resources.max_cache_mib == 512
    assert not _has_qt_imports(
        Path("src/uniti/core"),
        Path("src/uniti/regex"),
        Path("src/uniti/resources"),
    )


def test_a18_deep_self_check_includes_large_file(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    paths = AppPaths(
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "state",
        tmp_path / "cache",
    )
    paths.ensure()
    marker = tmp_path / ".uniti-runtime.json"
    marker.write_text(
        json.dumps(
            {
                "schema": 1,
                "owner": "uniti-editor",
                "environment_id": "a18-test-runtime",
                "mode": "source",
                "healthy": True,
            }
        ),
        encoding="utf-8",
    )

    report = SelfCheckRunner(
        paths,
        marker_path=marker,
        runtime_python=Path(sys.executable),
    ).run(deep=True)

    assert report.status is CheckStatus.PASS
    large_file = next(item for item in report.results if item.name == "large-file")
    assert large_file.status is CheckStatus.PASS
    assert large_file.details["sparse_bytes"] > 1 << 30
    assert large_file.details["allocated_bytes"] < large_file.details["sparse_bytes"] // 2
    assert large_file.details["cleanup_ok"] is True
