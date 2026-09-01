import subprocess
import sys
from pathlib import Path

from scripts import bootstrap


def test_candidate_commands_put_explicit_override_first():
    candidates = bootstrap._candidate_commands(
        {"UNITI_PYTHON": "/opt/Python 3.12/bin/python3"},
        "/current/python",
        "linux",
    )

    assert candidates[0] == ("/opt/Python 3.12/bin/python3",)
    assert candidates[1] == ("/current/python",)
    assert ("python3.12",) in candidates


def test_shim_selects_first_process_reporting_python_312_or_newer():
    def probe(command):
        return (3, 11, 8) if command == ("old",) else (3, 12, 1)

    assert bootstrap._select_supported((('old',), ('new',)), probe) == ("new",)


def test_shim_compiles_and_reports_help_under_supported_python():
    script = Path(__file__).parents[2] / "scripts" / "bootstrap.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--local" in result.stdout
