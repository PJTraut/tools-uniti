from pathlib import Path

import pytest

from uniti.app.paths import AppPaths
from uniti.bootstrap import cli
from uniti.bootstrap.model import (
    BootstrapMode,
    BootstrapRequest,
    BootstrapResult,
    RuntimeMarker,
)


def _marker(tmp_path: Path) -> RuntimeMarker:
    return RuntimeMarker(
        1,
        "uniti-editor",
        "id",
        BootstrapMode.SOURCE,
        tmp_path / ".venv",
        tmp_path,
        {},
        {},
        "created",
        "updated",
        "fingerprint",
        True,
    )


def test_parse_args_selects_local_deep_self_check_and_forwarded_file(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "source_root", lambda: tmp_path)
    monkeypatch.setattr(
        AppPaths,
        "current",
        classmethod(
            lambda cls: AppPaths(
                tmp_path / "cfg", tmp_path / "data", tmp_path / "state", tmp_path / "cache"
            )
        ),
    )

    request = cli.parse_args(["--local", "--deep", "--json", "--", "-notes.txt"])

    assert request.mode is BootstrapMode.LOCAL
    assert request.self_check is True
    assert request.deep is True
    assert request.json_output is True
    assert request.forwarded == ("-notes.txt",)


def test_json_requires_self_check():
    with pytest.raises(SystemExit) as caught:
        cli.parse_args(["--json"])

    assert caught.value.code == 2


def test_managed_command_forwards_self_check_flags_and_files(tmp_path: Path):
    request = BootstrapRequest(
        BootstrapMode.SOURCE,
        tmp_path,
        self_check=True,
        deep=True,
        json_output=True,
        forwarded=("notes.txt",),
    )

    assert cli.managed_command(tmp_path / ".venv/bin/python", request) == (
        str(tmp_path / ".venv/bin/python"),
        "-m",
        "uniti",
        "--self-check",
        "--deep",
        "--json",
        "notes.txt",
    )


def test_main_propagates_managed_launch_exit(monkeypatch, tmp_path: Path):
    marker = _marker(tmp_path)
    result = BootstrapResult(
        tmp_path / ".venv",
        tmp_path / ".venv/bin/python",
        marker,
        "fingerprint",
        False,
        7,
    )
    monkeypatch.setattr(cli, "run_bootstrap", lambda request: result)
    monkeypatch.setattr(cli, "source_root", lambda: tmp_path)

    assert cli.main(["--", "notes.txt"]) == 7


def test_no_launch_prints_exact_managed_command(monkeypatch, tmp_path: Path, capsys):
    marker = _marker(tmp_path)
    result = BootstrapResult(
        tmp_path / ".venv",
        tmp_path / ".venv/bin/python",
        marker,
        "fingerprint",
        True,
        None,
    )
    monkeypatch.setattr(cli, "run_bootstrap", lambda request: result)
    monkeypatch.setattr(cli, "source_root", lambda: tmp_path)

    assert cli.main(["--no-launch"]) == 0
    assert "-m uniti" in capsys.readouterr().out
