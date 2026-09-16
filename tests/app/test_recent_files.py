import pytest


def test_empty_store_loads_as_empty_tuple(tmp_path):
    from uniti.app.recent_files import RecentFilesStore

    store = RecentFilesStore(tmp_path / "recent-files.json")
    assert store.load() == ()


def test_record_opened_inserts_most_recent_first(tmp_path):
    from uniti.app.recent_files import RecentFilesStore

    store = RecentFilesStore(tmp_path / "recent-files.json")
    store.record_opened("/a.txt")
    store.record_opened("/b.txt")
    assert store.load() == ("/b.txt", "/a.txt")


def test_record_opened_moves_existing_path_to_front_without_duplicating(tmp_path):
    from uniti.app.recent_files import RecentFilesStore

    store = RecentFilesStore(tmp_path / "recent-files.json")
    store.record_opened("/a.txt")
    store.record_opened("/b.txt")
    store.record_opened("/a.txt")
    assert store.load() == ("/a.txt", "/b.txt")


def test_record_opened_is_bounded_to_ten_entries(tmp_path):
    from uniti.app.recent_files import MAX_RECENT_FILES, RecentFilesStore

    store = RecentFilesStore(tmp_path / "recent-files.json")
    for index in range(MAX_RECENT_FILES + 5):
        store.record_opened(f"/file-{index}.txt")
    paths = store.load()
    assert len(paths) == MAX_RECENT_FILES
    assert paths[0] == f"/file-{MAX_RECENT_FILES + 4}.txt"


def test_clear_empties_the_list(tmp_path):
    from uniti.app.recent_files import RecentFilesStore

    store = RecentFilesStore(tmp_path / "recent-files.json")
    store.record_opened("/a.txt")
    store.clear()
    assert store.load() == ()


def test_store_recovery_does_not_overwrite_damage(tmp_path):
    from uniti.app.recent_files import RecentFilesStore

    path = tmp_path / "recent-files.json"
    original = b'{"schema": 99, "paths": []}'
    path.write_bytes(original)

    assert RecentFilesStore(path).load() == ()
    assert path.read_bytes() == original


def test_record_opened_reads_disk_first_so_concurrent_windows_merge(tmp_path):
    from uniti.app.recent_files import RecentFilesStore

    path = tmp_path / "recent-files.json"
    store_a = RecentFilesStore(path)
    store_b = RecentFilesStore(path)
    store_a.record_opened("/a.txt")
    store_b.record_opened("/b.txt")
    assert store_a.load() == ("/b.txt", "/a.txt")
