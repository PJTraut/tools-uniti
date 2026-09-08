from pathlib import Path
from types import SimpleNamespace

import pytest

from uniti.app.paths import AppPaths
from uniti.app.platform_policy import UnsupportedPlatformError
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


def test_unsupported_bootstrap_platform_returns_runtime_exit_without_traceback(
    monkeypatch,
    capsys,
):
    def unsupported(cls):
        raise UnsupportedPlatformError("freebsd14")

    monkeypatch.setattr(AppPaths, "current", classmethod(unsupported))

    assert cli.main(["--no-launch"]) == 10

    error = capsys.readouterr().err
    assert error.strip() == (
        "UNITI bootstrap failed: Unsupported UNITI platform: freebsd14"
    )
    assert "Traceback" not in error


def test_parse_args_forwards_application_options_in_original_order():
    request = cli.parse_args(["--version", "notes.txt"])

    assert request.forwarded == ("--version", "notes.txt")


def test_double_dash_forwards_names_that_overlap_bootstrap_options():
    request = cli.parse_args(["--", "--deep", "notes.txt"])

    assert request.deep is False
    assert request.forwarded == ("--deep", "notes.txt")


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
    def prepared_with_progress(_request):
        cli.report_progress("// prepping UNITI for first use")
        return result

    monkeypatch.setattr(cli, "run_bootstrap", prepared_with_progress)
    monkeypatch.setattr(cli, "source_root", lambda: tmp_path)

    assert cli.main(["--no-launch"]) == 0
    captured = capsys.readouterr()
    assert "-m uniti" in captured.out
    assert captured.err == "// prepping UNITI for first use\n"


def test_json_launch_stdout_remains_parseable_while_progress_uses_stderr(
    monkeypatch, tmp_path: Path, capsys
):
    marker = _marker(tmp_path)
    result = BootstrapResult(
        tmp_path / ".venv",
        tmp_path / ".venv/bin/python",
        marker,
        "fingerprint",
        False,
        0,
    )

    def launched_with_progress(_request):
        cli.report_progress("// validating UNITI setup")
        print('{"checks": 21, "ok": true}')
        return result

    monkeypatch.setattr(cli, "run_bootstrap", launched_with_progress)
    monkeypatch.setattr(cli, "source_root", lambda: tmp_path)

    assert cli.main(["--self-check", "--json"]) == 0
    captured = capsys.readouterr()
    import json

    assert json.loads(captured.out) == {"checks": 21, "ok": True}
    assert captured.err == "// validating UNITI setup\n"


def _run_with_progress_fakes(
    monkeypatch,
    tmp_path: Path,
    *,
    environment_stage: str | None,
    dependency_stages: tuple[str, ...],
    repair: bool = False,
    no_launch: bool = False,
    fail_environment: bool = False,
) -> list[str]:
    marker = _marker(tmp_path)
    runtime = tmp_path / ".venv/bin/python"

    class FakeEnvironmentManager:
        def __init__(self, **kwargs):
            self.progress = kwargs["progress"]

        def lock(self):
            from contextlib import nullcontext

            return nullcontext()

        def ensure(self, *, repair):
            if environment_stage is not None:
                self.progress(environment_stage)
            if fail_environment:
                raise cli.BootstrapError("injected environment failure", 11)
            return runtime, marker

        def mark_healthy(self, current, _fingerprint):
            return current

    class FakeDependencyManager:
        def __init__(self, *_args, **kwargs):
            self.progress = kwargs["progress"]

        def ensure(self, *, marker, repair):
            for stage in dependency_stages:
                self.progress(stage)
            return SimpleNamespace(
                fingerprint="fingerprint",
                versions={},
                fast_path=not dependency_stages,
            )

    monkeypatch.setattr(cli, "validate_source_root", lambda root: root)
    monkeypatch.setattr(cli, "query_python", lambda _command: SimpleNamespace())
    monkeypatch.setattr(cli, "environment_path", lambda _request: tmp_path / ".venv")
    monkeypatch.setattr(cli, "EnvironmentManager", FakeEnvironmentManager)
    monkeypatch.setattr(cli, "DependencyManager", FakeDependencyManager)
    monkeypatch.setattr(cli, "_persist_bootstrap", lambda *_args: None)
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )
    request = BootstrapRequest(
        BootstrapMode.SOURCE,
        tmp_path,
        repair=repair,
        no_launch=no_launch,
    )
    progress: list[str] = []

    if fail_environment:
        with pytest.raises(cli.BootstrapError):
            cli.run_bootstrap(request, progress=progress.append)
    else:
        cli.run_bootstrap(request, progress=progress.append)
    return progress


@pytest.mark.parametrize(
    ("environment_stage", "expected_stage"),
    [
        ("// creating UNITI runtime", "// creating UNITI runtime"),
        ("// adopting existing UNITI runtime", "// adopting existing UNITI runtime"),
    ],
)
def test_first_use_message_precedes_initial_or_adopted_runtime_work(
    monkeypatch, tmp_path, environment_stage, expected_stage
):
    progress = _run_with_progress_fakes(
        monkeypatch,
        tmp_path,
        environment_stage=environment_stage,
        dependency_stages=(
            "// installing UNITI dependencies",
            "// validating UNITI setup",
        ),
    )

    assert progress == [
        "// prepping UNITI for first use",
        expected_stage,
        "// installing UNITI dependencies",
        "// validating UNITI setup",
        "// launching UNITI",
    ]


def test_first_use_message_precedes_first_dependency_install(monkeypatch, tmp_path):
    progress = _run_with_progress_fakes(
        monkeypatch,
        tmp_path,
        environment_stage=None,
        dependency_stages=(
            "// installing UNITI dependencies",
            "// validating UNITI setup",
        ),
        no_launch=True,
    )

    assert progress[:2] == [
        "// prepping UNITI for first use",
        "// installing UNITI dependencies",
    ]


def test_repair_uses_repair_wording_and_failure_keeps_earlier_progress(
    monkeypatch, tmp_path
):
    repair_progress = _run_with_progress_fakes(
        monkeypatch,
        tmp_path,
        environment_stage="// repairing UNITI runtime",
        dependency_stages=(
            "// installing UNITI dependencies",
            "// validating UNITI setup",
        ),
        repair=True,
    )
    failure_progress = _run_with_progress_fakes(
        monkeypatch,
        tmp_path,
        environment_stage="// creating UNITI runtime",
        dependency_stages=(),
        fail_environment=True,
    )

    assert repair_progress[0] == "// repairing UNITI setup"
    assert "first use" not in "\n".join(repair_progress)
    assert failure_progress == [
        "// prepping UNITI for first use",
        "// creating UNITI runtime",
    ]


def test_healthy_launch_is_quiet_and_no_launch_omits_launch_stage(monkeypatch, tmp_path):
    healthy = _run_with_progress_fakes(
        monkeypatch,
        tmp_path,
        environment_stage=None,
        dependency_stages=(),
    )
    no_launch = _run_with_progress_fakes(
        monkeypatch,
        tmp_path,
        environment_stage="// creating UNITI runtime",
        dependency_stages=(
            "// installing UNITI dependencies",
            "// validating UNITI setup",
        ),
        no_launch=True,
    )

    assert healthy == []
    assert no_launch[-1] == "// validating UNITI setup"
    assert "// launching UNITI" not in no_launch


def test_progress_is_flushed_to_stderr_without_corrupting_stdout(monkeypatch, capsys):
    flushed: list[bool] = []
    written: list[str] = []

    class Stream:
        def write(self, value):
            written.append(value)
            return len(value)

        def flush(self):
            flushed.append(True)

    monkeypatch.setattr(cli.sys, "stderr", Stream())
    cli.report_progress("// stage")
    assert "".join(written) == "// stage\n"
    assert flushed == [True]

    monkeypatch.undo()
    print('{"ok": true}')
    cli.report_progress("// prepping UNITI for first use")
    captured = capsys.readouterr()
    assert captured.out == '{"ok": true}\n'
    assert captured.err == "// prepping UNITI for first use\n"
