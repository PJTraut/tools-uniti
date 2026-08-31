from pathlib import Path

from uniti.core.file_identity import FileIdentity


def test_file_identity_captures_stable_stat_fields(tmp_path: Path):
    path = tmp_path / "identity.txt"
    path.write_text("abc", encoding="utf-8")
    identity = FileIdentity.from_path(path)
    stat = path.stat()
    assert identity.size == 3
    assert identity.mtime_ns == stat.st_mtime_ns
    assert identity.inode == getattr(stat, "st_ino", None)
    assert identity.device == getattr(stat, "st_dev", None)
