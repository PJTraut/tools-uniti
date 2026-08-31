import os
import subprocess
import sys
from pathlib import Path


def test_core_probe_reports_file_metadata(tmp_path: Path):
    path = tmp_path / "sample.txt"
    path.write_bytes(b"alpha\r\nbeta\r\n")
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    result = subprocess.run(
        [sys.executable, "scripts/core_probe.py", str(path), "--window", "8"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "size: 13" in result.stdout
    assert "encoding: utf-8" in result.stdout
    assert "eol: CRLF" in result.stdout
