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
        [sys.executable, "scripts/core_probe.py", str(path), "--window", "8", "--full-eol"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "size: 13" in result.stdout
    assert "encoding: utf-8" in result.stdout
    assert "eol: CRLF" in result.stdout


def test_core_probe_uses_detected_encoding_for_eol(tmp_path: Path):
    path = tmp_path / "utf16.txt"
    path.write_bytes("alpha\r\nbeta\r\n".encode("utf-16-le"))
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    result = subprocess.run(
        [sys.executable, "scripts/core_probe.py", str(path), "--window", "16", "--full-eol"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "encoding: utf-16-le" in result.stdout
    assert "eol: CRLF" in result.stdout


def test_core_probe_does_not_full_scan_eol_by_default(tmp_path: Path):
    path = tmp_path / "bounded.txt"
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
    assert "eol: not-scanned" in result.stdout
    assert "offset-index-complete: false" in result.stdout
    assert "source-line-index-complete: false" in result.stdout


def test_core_probe_window_never_reports_split_utf8_as_decode_error(tmp_path: Path):
    path = tmp_path / "utf8-boundary.txt"
    path.write_bytes("AB€CD".encode("utf-8"))
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    result = subprocess.run(
        [sys.executable, "scripts/core_probe.py", str(path), "--window", "4"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "decode-errors: 0" in result.stdout
    assert "document-text: 'AB'" in result.stdout
