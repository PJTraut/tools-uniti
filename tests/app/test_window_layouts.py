"""Window layouts per screen configuration: signature, book and storage."""

from __future__ import annotations

import json

import pytest

from uniti.app.window_layouts import (
    MAX_LAYOUTS,
    Layout,
    LayoutBook,
    Placement,
    ScreenSpec,
    WindowLayoutStore,
    screen_signature,
)

LAPTOP = ScreenSpec("laptop", (0, 0, 1440, 900), 2.0)
EXTERNAL = ScreenSpec("external", (1440, 0, 2560, 1440), 1.0)


def _layout(screens=(LAPTOP,), **kwargs) -> Layout:
    return Layout(screen_signature(screens), screens, **kwargs)


def test_signature_ignores_the_order_the_platform_lists_screens_in():
    assert screen_signature((LAPTOP, EXTERNAL)) == screen_signature((EXTERNAL, LAPTOP))


def test_signature_differs_for_a_different_size_origin_scale_or_monitor():
    base = screen_signature((LAPTOP, EXTERNAL))
    resized = ScreenSpec("external", (1440, 0, 1920, 1080), 1.0)
    moved = ScreenSpec("external", (-2560, 0, 2560, 1440), 1.0)
    rescaled = ScreenSpec("external", (1440, 0, 2560, 1440), 2.0)
    other = ScreenSpec("projector", (1440, 0, 2560, 1440), 1.0)
    signatures = {screen_signature((LAPTOP, item)) for item in (resized, moved, rescaled, other)}
    assert base not in signatures and len(signatures) == 4


def test_book_records_the_newest_layout_and_makes_it_active():
    book = LayoutBook().with_layout(_layout(windows={"w": Placement((10, 20, 300, 200))}))
    again = book.with_layout(_layout(windows={"w": Placement((50, 60, 300, 200))}))
    assert len(again.layouts) == 1
    assert again.get(screen_signature((LAPTOP,))).windows["w"].geometry == (50, 60, 300, 200)
    assert again.active == screen_signature((LAPTOP,))
    assert again.get(screen_signature((LAPTOP,))).serial == 2


def test_book_keeps_only_the_most_recently_recorded_layouts():
    book = LayoutBook()
    signatures = []
    for index in range(MAX_LAYOUTS + 3):
        screens = (ScreenSpec(f"screen-{index}", (0, 0, 1000 + index, 800), 1.0),)
        signatures.append(screen_signature(screens))
        book = book.with_layout(_layout(screens))
    assert len(book.layouts) == MAX_LAYOUTS
    assert book.get(signatures[0]) is None
    assert book.get(signatures[-1]) is not None


def test_latest_excludes_the_given_configuration():
    both = (LAPTOP, EXTERNAL)
    book = LayoutBook().with_layout(_layout()).with_layout(_layout(both))
    assert book.latest().signature == screen_signature(both)
    assert book.latest(exclude=screen_signature(both)).signature == screen_signature((LAPTOP,))
    assert LayoutBook().latest() is None


def test_store_round_trips_a_book(tmp_path):
    store = WindowLayoutStore(tmp_path / "window-layouts.json")
    book = LayoutBook().with_layout(
        _layout(
            (LAPTOP, EXTERNAL),
            windows={"w1": Placement((1500, 20, 900, 700), "maximized")},
            find=(100, 100, 820, 320),
            toggles={"compare": (200, 200, 900, 600)},
        )
    )
    store.save(book)
    assert store.load() == book


def test_store_reads_a_missing_file_as_empty(tmp_path):
    assert WindowLayoutStore(tmp_path / "none.json").load() == LayoutBook()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(schema=2),
        lambda p: p["layouts"][0].update(windows={"w": {"geometry": [0, 0, -1, 5], "state": "normal"}}),
        lambda p: p["layouts"][0].update(windows={"w": {"geometry": [0, 0, 5, 5], "state": "bogus"}}),
        lambda p: p["layouts"][0].update(find=[0, 0, 5]),
        lambda p: p["layouts"][0].update(screens=[]),
        lambda p: p["layouts"][0]["screens"][0].update(scale=0),
        lambda p: p["layouts"].append(dict(p["layouts"][0])),
        lambda p: p.update(extra=1),
    ],
)
def test_store_reads_an_invalid_file_as_empty(tmp_path, mutate):
    store = WindowLayoutStore(tmp_path / "window-layouts.json")
    store.save(LayoutBook().with_layout(_layout(windows={"w": Placement((0, 0, 100, 100))})))
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    mutate(payload)
    store.path.write_text(json.dumps(payload), encoding="utf-8")
    assert store.load() == LayoutBook()


def test_store_reads_garbage_as_empty(tmp_path):
    path = tmp_path / "window-layouts.json"
    path.write_text("{not json", encoding="utf-8")
    assert WindowLayoutStore(path).load() == LayoutBook()


def test_layout_rejects_oversized_geometry():
    with pytest.raises(ValueError):
        Placement((0, 0, 10**9, 100))
